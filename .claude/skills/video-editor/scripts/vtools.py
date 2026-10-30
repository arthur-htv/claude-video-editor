"""Shared helpers for the video-editor scripts.

Finds the project folders (input/, output/, work/) and the tools (ffmpeg, ffprobe,
node), preferring the portable copies that setup puts in tools/, then the PATH.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".ts",
              ".wmv", ".flv", ".3gp", ".mpg", ".mpeg"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

SETUP_HINT = ("Run the setup first (see README.md). Windows: "
              "powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1   macOS/Linux: bash setup.sh")


class SetupError(RuntimeError):
    """A required tool is missing."""


def project_root() -> Path:
    """The folder that holds input/ and output/ (searched upward from the cwd, then from this file)."""
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            if (d / "input").is_dir() and (d / "output").is_dir():
                return d
    return Path.cwd().resolve()


def find_tool(name: str) -> str:
    """Path to ffmpeg / ffprobe / node: the portable copy in tools/ first, then PATH."""
    root = project_root()
    exe = f"{name}.exe" if os.name == "nt" else name
    for candidate in (root / "tools" / "ffmpeg" / "bin" / exe,
                      root / "tools" / "node" / exe,
                      root / "tools" / "node" / "bin" / name):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise SetupError(f"{name} was not found. {SETUP_HINT}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kwargs)


@lru_cache(maxsize=1)
def ffmpeg_version() -> tuple[int, ...]:
    """(major, minor) of ffmpeg. Git builds ('N-12345-...') count as newest."""
    out = run([find_tool("ffmpeg"), "-hide_banner", "-version"]).stdout
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    return (99, 0)


@lru_cache(maxsize=1)
def encoders() -> frozenset[str]:
    """Names of the encoders this ffmpeg build has (libx264, libx265, aac, ...)."""
    names = set()
    for line in run([find_tool("ffmpeg"), "-hide_banner", "-encoders"]).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fps(stream: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            f = Fraction(stream.get(key) or "0/0")
        except (ValueError, ZeroDivisionError):
            continue
        if 1 <= f <= 240:
            return float(f)
    return None


@dataclass
class MediaInfo:
    path: Path
    duration: float
    format_start: float
    has_video: bool
    has_audio: bool
    video_index: int = 0          # position among video streams (skips cover art)
    width: int = 0
    height: int = 0
    fps: float | None = None
    video_codec: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    video_start: float = 0.0
    video_duration: float = 0.0
    audio_codec: str = ""
    audio_channels: int = 0
    audio_start: float = 0.0
    audio_duration: float = 0.0

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS


def probe(path: Path | str) -> MediaInfo:
    """Read a media file's streams and timing with ffprobe."""
    path = Path(path)
    res = run([find_tool("ffprobe"), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path.name}: {res.stderr.strip() or 'unknown error'}")
    data = json.loads(res.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    real_videos = [(i, s) for i, s in enumerate(videos)
                   if not (s.get("disposition") or {}).get("attached_pic")]

    format_start = _num(fmt.get("start_time"))
    duration = _num(fmt.get("duration"))
    if duration <= 0:
        duration = max([_num(s.get("duration")) for s in streams] or [0.0])

    info = MediaInfo(path=path, duration=duration, format_start=format_start,
                     has_video=bool(real_videos), has_audio=bool(audios))
    if real_videos:
        idx, v = real_videos[0]
        info.video_index = idx
        info.width = int(v.get("width") or 0)
        info.height = int(v.get("height") or 0)
        info.fps = _fps(v)
        info.video_codec = v.get("codec_name", "")
        info.color_transfer = v.get("color_transfer", "") or ""
        info.color_primaries = v.get("color_primaries", "") or ""
        info.color_space = v.get("color_space", "") or ""
        info.video_start = _num(v.get("start_time"), format_start)
        info.video_duration = _num(v.get("duration"))
    if audios:
        a = audios[0]
        info.audio_codec = a.get("codec_name", "")
        info.audio_channels = int(a.get("channels") or 0)
        info.audio_start = _num(a.get("start_time"), format_start)
        info.audio_duration = _num(a.get("duration"))
    return info


def fmt_time(seconds: float) -> str:
    """12.3 -> '0:12.3', 3725 -> '1:02:05.0'."""
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h >= 1:
        return f"{int(h)}:{int(m):02d}:{s:04.1f}"
    return f"{int(m)}:{s:04.1f}"


def media_files(folder: Path) -> list[Path]:
    """Video and audio files directly inside a folder, sorted by name."""
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and not p.name.startswith(".")
                   and p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS),
                  key=lambda p: p.name.lower())
