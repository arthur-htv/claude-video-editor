"""Build small HyperFrames compositions, render them, and lay them over a video.

Shared by the kinetic-text and morph-shapes skills:
  new_composition()  writes work/hyperframes/<name>/index.html with local GSAP + fonts
  render()           renders it with this folder's HyperFrames (MP4, or WebM with transparency)
  overlay()          lays rendered clips onto a video at given times in one encode
  contact_sheet()    grabs frames into one PNG so the result can be checked by eye
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from vtools import SETUP_HINT, SetupError, find_tool, fmt_time, probe, project_root

SKILL_DIR = Path(__file__).resolve().parent.parent
FONT_DIR = SKILL_DIR / "assets" / "fonts"
GSAP_FILES = ("gsap.min.js", "MorphSVGPlugin.min.js", "DrawSVGPlugin.min.js")

# Fonts every generated composition can use (bundled, OFL licensed).
FONT_CSS = """
@font-face { font-family: 'Montserrat XB'; src: url('assets/fonts/Montserrat-ExtraBold.ttf'); font-weight: 800; }
@font-face { font-family: 'Abril Fatface'; src: url('assets/fonts/AbrilFatface-Regular.ttf'); }
@font-face { font-family: 'Architects Daughter'; src: url('assets/fonts/ArchitectsDaughter-Regular.ttf'); }
@font-face { font-family: 'Inter'; src: url('assets/fonts/Inter-Regular.ttf'); font-weight: 400; }
@font-face { font-family: 'Inter'; src: url('assets/fonts/Inter-SemiBold.ttf'); font-weight: 600; }
@font-face { font-family: 'Inter'; src: url('assets/fonts/Inter-Bold.ttf'); font-weight: 700; }
"""

# Meaningful colors (the editing playbook): red = wrong/loss, teal = concept/keyword, green = action/payoff.
COLORS = {"white": "#ffffff", "teal": "#2ee6d6", "red": "#ff5a5f", "green": "#4ade80",
          "yellow": "#ffd84a", "orange": "#ff9430", "purple": "#a155ff", "blue": "#5db4ff"}


def color(name: str | None, default: str = "white") -> str:
    name = (name or default).strip()
    return name if name.startswith("#") else COLORS.get(name.lower(), COLORS[default])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "clip"


def scripts_html() -> str:
    tags = "".join(f'<script src="assets/{f}"></script>' for f in GSAP_FILES)
    return tags + "<script>gsap.registerPlugin(MorphSVGPlugin, DrawSVGPlugin);</script>"


def _gsap_dir(root: Path) -> Path:
    d = root / "node_modules" / "gsap" / "dist"
    if not (d / "gsap.min.js").is_file():
        raise SetupError(f"GSAP is missing from node_modules. {SETUP_HINT}")
    return d


def new_composition(name: str, html: str) -> Path:
    """Write work/hyperframes/<name>/ with index.html, local GSAP and the bundled fonts."""
    root = project_root()
    d = root / "work" / "hyperframes" / name
    (d / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    gsap = _gsap_dir(root)
    for f in GSAP_FILES:
        shutil.copy2(gsap / f, d / "assets" / f)
    for f in FONT_DIR.glob("*.ttf"):
        shutil.copy2(f, d / "assets" / "fonts" / f.name)
    (d / "index.html").write_text(html, encoding="utf-8")
    return d


def render(comp_dir: Path, out: Path, fps: int = 30, transparent: bool = False) -> Path:
    """Render a composition. transparent=True makes a WebM with an alpha channel (for overlays)."""
    root = project_root()
    cli = root / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if not cli.is_file():
        raise SetupError(f"HyperFrames is not installed. {SETUP_HINT}")
    node, ffmpeg, ffprobe = find_tool("node"), find_tool("ffmpeg"), find_tool("ffprobe")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(ffmpeg).parent), str(Path(node).parent), env.get("PATH", "")])
    env["HYPERFRAMES_FFMPEG_PATH"], env["HYPERFRAMES_FFPROBE_PATH"] = ffmpeg, ffprobe
    env.setdefault("HYPERFRAMES_NO_TELEMETRY", "1")      # no usage telemetry
    env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")       # no silent skill installs into ~/.claude
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [node, str(cli), "render", str(comp_dir), "-o", str(out), "--fps", str(fps), "--quiet"]
    if transparent:
        cmd += ["--format", "webm"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if res.returncode != 0 or not out.is_file():
        tail = (res.stderr or res.stdout or "").strip()[-1200:]
        raise RuntimeError(f"HyperFrames render failed for {comp_dir.name}:\n{tail}")
    return out


def video_fps(info) -> int:
    return int(min(60, max(24, round(info.fps or 30))))


def overlay(video: Path, clips: list[dict], out: Path, crf: int = 18, speed: str = "fast") -> Path:
    """Lay clips over a video in one encode. clips: [{"path": Path, "start": seconds}, ...].
    WebM clips keep their transparency; MP4 clips cover the frame while they play.
    The audio is copied untouched."""
    from cut_dead_air import run_ffmpeg, video_codec_args  # shared encoder choices (HDR, fallbacks)

    info = probe(video)
    w, h = info.width, info.height
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(video)]
    for c in clips:
        if Path(c["path"]).suffix.lower() == ".webm":
            cmd += ["-c:v", "libvpx-vp9"]          # the built-in VP9 decoder drops transparency
        cmd += ["-i", str(c["path"])]
    parts, prev = [], f"[0:v:{info.video_index}]"
    for i, c in enumerate(clips, 1):
        parts.append(f"[{i}:v]scale={w}:{h},setpts=PTS+{float(c['start']):.4f}/TB[o{i}]")
        parts.append(f"{prev}[o{i}]overlay=0:0:eof_action=pass[v{i}]")
        prev = f"[v{i}]"
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2" if (w % 2 or h % 2) else "null"
    parts.append(f"{prev}{even}[vout]")
    root = project_root()
    (root / "work").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=root / "work", delete=False, encoding="utf-8") as g:
        g.write(";\n".join(parts))
        graph = Path(g.name)
    try:
        vargs, _ = video_codec_args(info, crf, speed)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["-/filter_complex", str(graph), "-map", "[vout]", *vargs, "-map", "0:a?", "-c:a", "copy",
                "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
        run_ffmpeg(cmd, info.duration, video.name)
    finally:
        graph.unlink(missing_ok=True)
    res = probe(out)
    if abs(res.duration - info.duration) > 0.5:
        raise RuntimeError(f"result is {fmt_time(res.duration)} long, source is {fmt_time(info.duration)}")
    return out


def contact_sheet(video: Path, times: list[float], out: Path, width: int = 480, cols: int = 3) -> Path:
    """Frames at the given times, tiled into one PNG with the time printed under each."""
    from PIL import Image, ImageDraw

    frames = []
    for t in times:
        data = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                               "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe",
                               "-vcodec", "png", "-"], capture_output=True).stdout
        if data:
            frames.append((t, Image.open(io.BytesIO(data)).convert("RGB")))
    if not frames:
        raise RuntimeError("could not grab any frames")
    fw, fh = frames[0][1].size
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (min(cols, len(frames)) * fw, rows * (fh + 24)), "#111")
    draw = ImageDraw.Draw(sheet)
    for i, (t, img) in enumerate(frames):
        x, y = (i % cols) * fw, (i // cols) * (fh + 24)
        sheet.paste(img, (x, y))
        draw.text((x + 8, y + fh + 5), fmt_time(t), fill="#ddd")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def js(value) -> str:
    """Safe JSON for embedding in a <script> block."""
    return json.dumps(value).replace("</", "<\\/")
