#!/usr/bin/env python3
"""Cut dead air (silent pauses) out of videos.

Reads raw videos from input/ and writes the finished videos to output/ with the
same name (as .mp4). The originals in input/ are never changed.

How it works
  1. Decode the audio and measure its loudness every 10 ms.
  2. Pick a silence threshold from the recording's own noise floor and speech
     level (or use --threshold).
  3. Every quiet stretch longer than --min-silence becomes a cut, keeping
     --padding seconds of air next to the speech so words are not clipped.
  4. Render the kept pieces back to back with FFmpeg (re-encoded, so every cut
     is frame-accurate), with tiny audio fades so the joins don't click.
  5. Check the result (length, audio/video in sync), then move it into output/.

Examples (run from the project folder with the .venv python)
  python cut_dead_air.py                    every video in input/ (skips ones already in output/)
  python cut_dead_air.py input/talk.mov     just one file
  python cut_dead_air.py --analyze          show what would be cut, render nothing
  python cut_dead_air.py --preset tight     snappier, social-media style jump cuts
  python cut_dead_air.py --preset gentle    only remove long pauses
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vtools import (AUDIO_EXTS, MediaInfo, SetupError, encoders,  # noqa: E402
                    ffmpeg_version, find_tool, fmt_time, media_files, probe,
                    project_root, run)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("numpy is missing. Use the project's Python in .venv, or run the setup (see README.md).")

PRESETS = {
    # min_silence: shortest pause that gets cut. padding: air kept on each side of speech.
    "gentle": {"min_silence": 1.0, "padding": 0.30},
    "normal": {"min_silence": 0.6, "padding": 0.15},
    "tight": {"min_silence": 0.35, "padding": 0.10},
}
HOP = 0.01              # loudness is measured in 10 ms steps
SAMPLE_RATE = 16000     # analysis sample rate (speech needs no more)
MIN_CUT = 0.15          # cuts shorter than this are not worth a jump cut
TAIL_BEFORE = 10        # speech may grow up to 0.10 s earlier into its quiet onset...
TAIL_AFTER = 30         # ...and up to 0.30 s later into its fade-out (frames of 10 ms)
TAIL_GAP = 12           # while growing, hop quiet dips up to 0.12 s (stop-consonant closures)
FADE = 0.008            # audio fade at every join, removes clicks
X264_SPEEDS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
AUDIO_OUT = {
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


@dataclass
class Plan:
    keeps: list[tuple[float, float]]
    cuts: list[tuple[float, float]]
    threshold: float
    threshold_mode: str
    levels: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def kept(self) -> float:
        return sum(b - a for a, b in self.keeps)


# ----------------------------------------------------------------------------- analysis

def measure_loudness(info: MediaInfo) -> np.ndarray:
    """Loudness (dBFS) of the first audio track, one value per 10 ms."""
    hop = int(SAMPLE_RATE * HOP)
    cmd = [find_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(info.path),
           "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    chunks, rest = [], b""
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf)
        while True:
            data = proc.stdout.read(hop * 2 * 2000)  # about 20 s of audio per read
            if not data:
                break
            data = rest + data
            usable = len(data) - len(data) % (hop * 2)
            rest = data[usable:]
            if usable:
                frames = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32).reshape(-1, hop) / 32768.0
                chunks.append(np.sqrt(np.mean(frames * frames, axis=1)))
        proc.wait()
        if proc.returncode != 0:
            errf.seek(0)
            msg = errf.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"could not decode the audio: {msg[-400:] or 'ffmpeg failed'}")
    rms = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    return 20.0 * np.log10(np.maximum(rms, 1e-5))


def choose_threshold(db: np.ndarray, fixed: float | None) -> tuple[float, float, str, dict, list[str]]:
    """Silence thresholds in dBFS: (speech, tail, mode, levels, warnings).

    `speech` sits between the noise floor and the speech level, nearer the floor.
    `tail` is lower: once speech is found, it lasts until the level drops below `tail`,
    so the quiet start and fade-out of words are kept.
    """
    audible = db[db > -90.0]          # ignore digital silence, it would drag the floor down
    levels, warnings = {}, []
    floor = None
    if audible.size:
        floor = float(np.percentile(audible, 10))
        speech = float(np.percentile(audible, 97))
        levels = {"noise_floor_db": round(floor, 1), "speech_level_db": round(speech, 1)}
    if fixed is not None:
        tail = fixed - 8.0 if floor is None else max(floor + 4.0, fixed - 12.0)
        return float(fixed), min(tail, fixed), "manual", levels, warnings
    if audible.size < 100:
        return -45.0, -53.0, "default", levels, ["Almost no sound in the audio track."]
    spread = speech - floor
    threshold = floor + max(6.0, 0.35 * spread)
    threshold = min(max(threshold, -60.0), -18.0)
    tail = min(threshold, max(floor + 4.0, threshold - 12.0))
    if spread < 15:
        warnings.append(f"Quiet and loud parts are only {spread:.0f} dB apart (background music or constant "
                        "noise?). Dead-air detection may be unreliable: check the preview or set --threshold.")
    return threshold, tail, "auto", levels, warnings


def runs(mask: np.ndarray) -> list[tuple[bool, int, int]]:
    """(value, start, end) for every run of equal values in a boolean array."""
    if mask.size == 0:
        return []
    change = np.flatnonzero(np.diff(mask.astype(np.int8))) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [mask.size]))
    return [(bool(mask[s]), int(s), int(e)) for s, e in zip(starts, ends)]


def keeps_from_cuts(cuts: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    keeps, pos = [], 0.0
    for a, b in cuts:
        if a > pos:
            keeps.append((pos, a))
        pos = max(pos, b)
    if pos < duration:
        keeps.append((pos, duration))
    return keeps


def cuts_from_keeps(keeps: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    cuts, pos = [], 0.0
    for a, b in keeps:
        if a - pos > 1e-6:
            cuts.append((pos, a))
        pos = b
    if duration - pos > 1e-6:
        cuts.append((pos, duration))
    return cuts


def snap_to_frames(keeps, fps: float | None, origin: float, duration: float):
    """Round kept pieces outward to whole video frames so picture and sound stay the same length."""
    if not fps:
        return keeps
    step = 1.0 / fps
    out: list[tuple[float, float]] = []
    for a, b in keeps:
        a2 = max(0.0, origin + math.floor((a - origin) / step + 1e-6) * step)
        b2 = min(duration, origin + math.ceil((b - origin) / step - 1e-6) * step)
        if out and a2 <= out[-1][1] + step / 2:
            out[-1] = (out[-1][0], max(out[-1][1], b2))
        elif b2 - a2 >= step:
            out.append((a2, b2))
    return out


def extend_into_tails(loud: np.ndarray, db: np.ndarray, tail: float) -> np.ndarray:
    """Grow each speech run outward while the level stays above `tail`.

    Words fade in and (especially) fade out below the main threshold; without this
    their quiet edges would be eaten by the cut. Growth is capped so a long reverb
    or a noisy pause cannot swallow the whole gap.
    """
    above = db > tail
    grown = loud.copy()
    n = loud.size
    for value, s, e in runs(loud):
        if not value:
            continue
        # Forward: follow the fade-out, hopping short dips such as the closure
        # before a final "t" or "k" release ("edit it.").
        end, quiet = e, 0
        for j in range(e, min(n, e + TAIL_AFTER)):
            if above[j]:
                end, quiet = j + 1, 0
            else:
                quiet += 1
                if quiet > TAIL_GAP:
                    break
        start, quiet = s, 0
        for k in range(s - 1, max(-1, s - 1 - TAIL_BEFORE), -1):
            if above[k]:
                start, quiet = k, 0
            else:
                quiet += 1
                if quiet > TAIL_GAP:
                    break
        grown[start:end] = True
    return grown


def plan_cuts(db: np.ndarray, info: MediaInfo, threshold: float, tail: float, min_silence: float,
              padding: float, min_sound: float) -> tuple[list, list]:
    """Turn loudness into (keeps, cuts), both lists of (start, end) seconds."""
    duration = info.duration
    offset = max(0.0, info.audio_start - info.format_start)
    loud = db > threshold
    # Picture that runs on after the audio track ends is silent too (common in phone exports):
    # count it as silence so the trailing cut removes it and picture and sound end together.
    missing = round((duration - offset) / HOP) - loud.size
    if missing > 0:
        loud = np.concatenate([loud, np.zeros(missing, dtype=bool)])
        db = np.concatenate([db, np.full(missing, -100.0, dtype=db.dtype)])
    # A blip shorter than min_sound (mouth click, bump, keyboard tap) is not speech.
    shortest_sound = max(1, round(min_sound / HOP))
    for value, s, e in runs(loud):
        if value and e - s < shortest_sound:
            loud[s:e] = False
    if not loud.any():
        return [], [(0.0, duration)]
    loud = extend_into_tails(loud, db, tail)
    shortest_pause = max(1, round(min_silence / HOP))
    n = loud.size
    cuts = []
    for value, s, e in runs(loud):
        if value or e - s < shortest_pause:
            continue
        # Lead-in silence goes from 0, trailing silence runs to the very end;
        # `padding` of air always stays next to the speech.
        start = 0.0 if s == 0 else offset + s * HOP + padding
        end = duration if e == n else offset + e * HOP - padding
        end = min(end, duration)
        if end - start >= MIN_CUT:
            cuts.append((max(0.0, start), end))
    keeps = keeps_from_cuts(cuts, duration)
    if info.has_video:
        keeps = snap_to_frames(keeps, info.fps, max(0.0, info.video_start - info.format_start), duration)
    return keeps, cuts_from_keeps(keeps, duration)


# ----------------------------------------------------------------------------- rendering

def video_codec_args(info: MediaInfo, crf: int, speed: str) -> tuple[list[str], str]:
    enc = encoders()
    if info.is_hdr and "libx265" in enc:
        args = ["-c:v", "libx265", "-preset", speed, "-crf", str(crf + 2), "-pix_fmt", "yuv420p10le",
                "-tag:v", "hvc1", "-x265-params", "log-level=error"]
        for opt, val in (("-color_primaries", info.color_primaries), ("-color_trc", info.color_transfer),
                         ("-colorspace", info.color_space)):
            if val:
                args += [opt, val]
        return args, "HEVC 10-bit (HDR kept)"
    if "libx264" in enc:
        return ["-c:v", "libx264", "-preset", speed, "-crf", str(crf), "-pix_fmt", "yuv420p"], "H.264"
    if "h264_videotoolbox" in enc:
        return ["-c:v", "h264_videotoolbox", "-b:v", "12M", "-pix_fmt", "yuv420p"], "H.264 (VideoToolbox)"
    if "libopenh264" in enc:
        return ["-c:v", "libopenh264", "-b:v", "12M", "-pix_fmt", "yuv420p"], "H.264 (OpenH264)"
    return ["-c:v", "mpeg4", "-q:v", "2"], "MPEG-4 Part 2"


def filter_graph(keeps: list[tuple[float, float]], info: MediaInfo) -> str:
    v_in, a_in = f"[0:v:{info.video_index}]", "[0:a:0]"
    parts, pads = [], []
    for i, (s, e) in enumerate(keeps):
        d = e - s
        f = min(FADE, d / 4)
        if info.has_video:
            parts.append(f"{v_in}trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"{a_in}atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:st=0:d={f:.4f},afade=t=out:st={max(0.0, d - f):.6f}:d={f:.4f}[a{i}]")
        pads.append(f"[v{i}][a{i}]" if info.has_video else f"[a{i}]")
    if info.has_video:
        concat = "".join(pads) + f"concat=n={len(keeps)}:v=1:a=1[cv][outa]"
        # H.264 in yuv420p needs even width and height.
        even = "scale=trunc(iw/2)*2:trunc(ih/2)*2" if (info.width % 2 or info.height % 2) else "null"
        parts += [concat, f"[cv]{even}[outv]"]
    else:
        parts.append("".join(pads) + f"concat=n={len(keeps)}:v=0:a=1[outa]")
    return ";\n".join(parts)


def run_ffmpeg(cmd: list[str], expected: float, label: str) -> None:
    """Run ffmpeg, printing progress every 20 %, and raise with its error text if it fails."""
    started = last_print = time.time()
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True,
                                encoding="utf-8", errors="replace")
        next_mark = 20
        for line in proc.stdout:
            if not line.startswith("out_time_us="):
                continue
            try:
                done = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                continue
            pct = 100 * done / expected if expected > 0 else 0
            while pct >= next_mark and next_mark <= 100:
                if time.time() - last_print >= 5:     # only long renders report progress
                    print(f"    rendering {label}: {next_mark}%  ({time.time() - started:.0f}s)", flush=True)
                    last_print = time.time()
                next_mark += 20
        proc.wait()
        if proc.returncode != 0:
            errf.seek(0)
            tail = errf.read().decode("utf-8", "replace").strip()[-1500:]
            raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")


def output_args(out: Path) -> list[str]:
    return ["-movflags", "+faststart"] if out.suffix.lower() in {".mp4", ".m4a", ".mov"} else []


def render(info: MediaInfo, keeps, dest: Path, graph_file: Path, crf: int, speed: str) -> str:
    graph_file.write_text(filter_graph(keeps, info), encoding="utf-8")
    ffmpeg = find_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(info.path)]
    cmd += ["-/filter_complex", str(graph_file)] if ffmpeg_version() >= (7, 1) \
        else ["-filter_complex_script", str(graph_file)]
    codec = "audio only"
    if info.has_video:
        vargs, codec = video_codec_args(info, crf, speed)
        cmd += ["-map", "[outv]", *vargs, "-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "[outa]", *AUDIO_OUT.get(dest.suffix.lower(), ["-c:a", "aac", "-b:a", "192k"])]
    cmd += ["-map_metadata", "0", *output_args(dest), "-progress", "pipe:1", "-nostats", str(dest)]
    run_ffmpeg(cmd, sum(b - a for a, b in keeps), info.path.name)
    return codec


def copy_whole(info: MediaInfo, dest: Path, graph_file: Path, crf: int, speed: str) -> str:
    """Nothing to cut: copy the streams as they are (re-encode only if the container refuses them)."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(info.path)]
    if info.has_video:
        cmd += ["-map", f"0:v:{info.video_index}"]
        if info.video_codec == "hevc":
            cmd += ["-tag:v", "hvc1"]
    cmd += ["-map", "0:a:0", "-c", "copy", "-map_metadata", "0", *output_args(dest), str(dest)]
    if run(cmd).returncode == 0:
        return "copied without re-encoding"
    return render(info, [(0.0, info.duration)], dest, graph_file, crf, speed)


def verify(dest: Path, expected: float, pieces: int, source: MediaInfo) -> list[str]:
    """Problems found in the finished file (empty list = all good)."""
    out = probe(dest)
    problems = []
    tolerance = 0.5 + 0.04 * pieces
    if abs(out.duration - expected) > tolerance:
        problems.append(f"length is {fmt_time(out.duration)}, expected about {fmt_time(expected)}")
    if source.has_video and not out.has_video:
        problems.append("the result has no video track")
    if not out.has_audio:
        problems.append("the result has no audio track")
    if out.has_video and out.video_duration and out.audio_duration \
            and abs(out.video_duration - out.audio_duration) > 0.3:
        problems.append(f"audio and video lengths differ by {abs(out.video_duration - out.audio_duration):.2f}s")
    return problems


# ----------------------------------------------------------------------------- main flow

def output_ext(src: Path) -> str:
    ext = src.suffix.lower()
    if ext in AUDIO_EXTS:
        return ext if ext in AUDIO_OUT else ".m4a"
    return ".mp4"


def plan_outputs(sources: list[Path], out_dir: Path, suffix: str) -> dict[Path, Path]:
    """Output path per source: same name, .mp4 for video. On a name clash (clip.mov and
    clip.mp4 both in input/) the file that already has the output extension keeps the
    plain name and the other gets its extension added (clip_mov.mp4)."""
    taken: set[str] = set()
    dest: dict[Path, Path] = {}
    for src in sorted(sources, key=lambda s: (s.suffix.lower() != output_ext(s), s.name.lower())):
        ext = output_ext(src)
        name = f"{src.stem}{suffix}{ext}"
        if name.lower() in taken:
            name = f"{src.stem}_{src.suffix.lstrip('.').lower()}{suffix}{ext}"
        taken.add(name.lower())
        dest[src] = out_dir / name
    return dest


def process(src: Path, dest: Path, args, work: Path) -> dict:
    t0 = time.time()
    preset = PRESETS[args.preset]
    min_silence = args.min_silence if args.min_silence is not None else preset["min_silence"]
    padding = args.padding if args.padding is not None else preset["padding"]
    min_silence = max(min_silence, 2 * padding + MIN_CUT)   # a pause must be longer than the air we keep
    report = {"source": str(src), "output": str(dest), "status": "", "preset": args.preset,
              "settings": {"min_silence": min_silence, "padding": padding, "min_sound": args.min_sound}}

    info = probe(src)
    report["duration_before"] = round(info.duration, 3)
    if not info.has_audio:
        report.update(status="skipped", reason="no audio track, so there is no dead air to detect")
        return report
    if info.duration <= 0:
        report.update(status="failed", reason="could not read the length of this file")
        return report

    db = measure_loudness(info)
    threshold, tail, mode, levels, warnings = choose_threshold(db, args.threshold)
    keeps, cuts = plan_cuts(db, info, threshold, tail, min_silence, padding, args.min_sound)
    plan = Plan(keeps, cuts, threshold, mode, levels, warnings)
    removed = info.duration - plan.kept
    report.update(threshold_db=round(threshold, 1), tail_threshold_db=round(tail, 1),
                  threshold_mode=mode, levels=levels,
                  warnings=warnings, duration_after=round(plan.kept, 3),
                  removed_seconds=round(removed, 3),
                  removed_percent=round(100 * removed / info.duration, 1),
                  cut_count=len(cuts),
                  cuts=[[round(a, 3), round(b, 3)] for a, b in cuts])

    if not keeps:
        report.update(status="skipped", reason="no speech or sound found above the silence threshold")
        return report
    if args.analyze:
        report["status"] = "analyzed"
        return report

    work.mkdir(parents=True, exist_ok=True)
    partial = work / f"{dest.stem}.partial{dest.suffix}"
    graph_file = work / f"{dest.stem}.filtergraph.txt"
    try:
        if cuts:
            codec = render(info, keeps, partial, graph_file, args.crf, args.speed)
        else:
            codec = copy_whole(info, partial, graph_file, args.crf, args.speed)
        problems = verify(partial, plan.kept, len(keeps), info)
        if problems:
            report.update(status="failed", reason="; ".join(problems), kept_for_inspection=str(partial))
            return report
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial.replace(dest)
    finally:
        graph_file.unlink(missing_ok=True)
    report.update(status="done", codec=codec, seconds_taken=round(time.time() - t0, 1))
    return report


def print_report(i: int, total: int, src: Path, r: dict) -> None:
    print(f"[{i}/{total}] {src.name}", flush=True)
    if "duration_after" in r:
        before, after = r["duration_before"], r["duration_after"]
        print(f"    {fmt_time(before)} -> {fmt_time(after)}   removed {fmt_time(r['removed_seconds'])} "
              f"({r['removed_percent']}%) in {r['cut_count']} cuts")
        lv = r.get("levels") or {}
        extra = (f"; noise floor {lv['noise_floor_db']} dB, speech {lv['speech_level_db']} dB"
                 if lv else "")
        print(f"    silence threshold {r['threshold_db']} dB ({r['threshold_mode']}{extra}) | "
              f"preset {r['preset']}, min pause {r['settings']['min_silence']:.2f}s, "
              f"padding {r['settings']['padding']:.2f}s")
    for w in r.get("warnings") or []:
        print(f"    WARNING: {w}")
    status = r["status"]
    if status == "analyzed":
        cuts = r.get("cuts") or []
        shown = ", ".join(f"{fmt_time(a)}-{fmt_time(b)}" for a, b in cuts[:12])
        more = f" (+{len(cuts) - 12} more)" if len(cuts) > 12 else ""
        print(f"    cuts: {shown or 'none'}{more}")
        print(f"    would write: {r['output']}")
    elif status == "done":
        print(f"    OK  {r['output']}  ({r['codec']}; length and A/V sync checked; {r['seconds_taken']}s)")
    else:
        print(f"    {status.upper()}: {r.get('reason', '')}")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(
        description="Cut dead air (silent pauses) out of videos: input/ -> output/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="presets: " + ", ".join(f"{k} (pause >= {v['min_silence']}s, keep {v['padding']}s)"
                                       for k, v in PRESETS.items()))
    p.add_argument("files", nargs="*", type=Path, help="files to process (default: everything in input/)")
    p.add_argument("--preset", choices=list(PRESETS), default="normal", help="how aggressive (default: normal)")
    p.add_argument("--min-silence", type=float, help="shortest pause in seconds that gets cut (overrides preset)")
    p.add_argument("--padding", type=float, help="seconds of air kept before/after speech (overrides preset)")
    p.add_argument("--min-sound", type=float, default=0.08,
                   help="sounds shorter than this (seconds) count as silence: clicks, bumps (default 0.08)")
    p.add_argument("--threshold", type=float, help="silence threshold in dBFS, e.g. -40 (default: automatic)")
    p.add_argument("--analyze", action="store_true", help="only show what would be cut; render nothing")
    p.add_argument("--overwrite", action="store_true", help="redo files that already exist in output/")
    p.add_argument("--output-dir", type=Path, help="where finished files go (default: output/)")
    p.add_argument("--suffix", default="", help="added to output names, e.g. _cut -> talk_cut.mp4")
    p.add_argument("--crf", type=int, default=18, help="video quality, lower = better and bigger (default 18)")
    p.add_argument("--speed", choices=X264_SPEEDS, default="fast", help="encoder speed preset (default fast)")
    p.add_argument("--json", action="store_true", help="also print all results as JSON at the end")
    args = p.parse_args()

    root = project_root()
    in_dir, work = root / "input", root / "work"
    out_dir = (args.output_dir or root / "output").resolve()
    if out_dir == in_dir.resolve():
        print("Refusing to write into input/: that folder is only for the original videos.")
        return 2

    if args.files:
        sources = []
        for f in args.files:
            cand = f if f.exists() else in_dir / f
            if not cand.is_file():
                print(f"Not found: {f}")
                return 2
            sources.append(cand.resolve())
    else:
        sources = media_files(in_dir)
    if not sources:
        print(f"No videos found in {in_dir}. Put the raw videos in input/ and run this again.")
        return 1

    try:
        find_tool("ffmpeg"), find_tool("ffprobe")
    except SetupError as e:
        print(e)
        return 2

    results, failed = [], 0
    destinations = plan_outputs(sources, out_dir, args.suffix)
    for i, src in enumerate(sources, 1):
        try:
            dest = destinations[src]
            if dest.resolve() == src:
                raise RuntimeError("output would overwrite the original; use --suffix or --output-dir")
            if dest.exists() and not args.overwrite and not args.analyze:
                r = {"source": str(src), "output": str(dest), "status": "skipped",
                     "reason": f"{dest.name} is already in {dest.parent.name}/ (use --overwrite to redo it)"}
            else:
                r = process(src, dest, args, work)
                if r["status"] != "skipped" or "duration_after" in r:
                    reports = work / "reports"
                    reports.mkdir(parents=True, exist_ok=True)
                    (reports / f"{dest.stem}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        except Exception as e:  # keep going with the other files
            r = {"source": str(src), "status": "failed", "reason": str(e)}
        if r["status"] == "failed":
            failed += 1
        results.append(r)
        print_report(i, len(sources), src, r)

    done = sum(r["status"] == "done" for r in results)
    print(f"\nFinished: {done} done, {sum(r['status'] == 'skipped' for r in results)} skipped, "
          f"{sum(r['status'] == 'analyzed' for r in results)} analyzed, {failed} failed.")
    if args.json:
        print(json.dumps(results, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
