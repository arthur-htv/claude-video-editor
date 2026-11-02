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
  python cut_dead_air.py --self-test        check the cut-edge search

Mistake cuts (run them with cut-mistakes/scripts/apply-cuts.mjs --video, which calls this)
  python cut_dead_air.py work/talk.mp4 --keeps scratch/keeps.json \\
      --words work/talk.transcript.json --render work/talk.clean.mp4
  Keeps only keeps.json's keep_ranges. Every cut edge moves to the quietest frame start within 0.12 s
  of its word edge, never inside a kept word, or onto a dead-air cut in the same pause (from
  work/reports/<name>.json), then renders like a dead-air cut (8 ms fades, same encoder, same check).
  The ranges and source length it used are written back into keeps.json, so give it a scratch copy:
  apply-cuts.mjs builds the EDL, the re-timed transcript and the decisions from them. No --render:
  measure only.
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
from fractions import Fraction
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
REACH = 0.12            # a mistake-cut edge may move this far from its word edge to find a quiet point
TIE_DB = 2.0            # points this close to the quietest count as quiet too: the one nearest the word edge wins
JOIN_SLACK = 0.05       # Whisper rounds to 20 ms: a kept word's edge can sit this far past a dead-air join beside it
MIN_REMOVED = 0.5       # a mistake cut must remove at least this share of its words' sound
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


def frame_times(info: MediaInfo) -> np.ndarray:
    """When every video frame starts, in seconds on the clock ffmpeg's trim filter uses (the file's start is 0).

    Read from the packets' own timestamps, so it is exact for a variable frame rate too, and for a dead-air cut
    of a clip whose video starts late: there the frames are not evenly spaced and probe's fps is an average.
    """
    res = run([find_tool("ffprobe"), "-v", "error", "-select_streams", f"v:{info.video_index}",
               "-show_entries", "stream=time_base:packet=pts,flags", "-of", "json", str(info.path)])
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe could not read the frame times of {info.path.name}: {res.stderr.strip()[-300:]}")
    data = json.loads(res.stdout or "{}")
    tb = Fraction(data["streams"][0]["time_base"])
    # A packet flagged D lies before an edit list's start: decoded, never shown.
    pts = sorted({p["pts"] for p in data.get("packets", []) if "pts" in p and "D" not in p.get("flags", "")})
    return np.array([float(p * tb) for p in pts]) - info.format_start


def quiet_edges(keeps, words, db: np.ndarray, info: MediaInfo, duration: float, joins=(), silence=None,
                frames=None):
    """Move every cut edge between `keeps` to the quietest frame start within REACH of its word edge.

    `words` are the transcript's (start, end) pairs; a word belongs to the cut when its middle is inside it.
    An edge never moves into a kept word, nor past the middle of a word being cut, so kept words stay whole
    and cut words stay cut; a cut that holds no word's middle and lies inside one word is left out. Between
    those limits the waveform decides, because transcript word edges are often tens of ms off (and usually
    touch, with no gap between words). `frames` are the video's frame start times (frame_times()); without
    them, frames are evenly spaced at info.fps (audio alone uses 10 ms steps). `joins` are cuts the video
    already has (its dead-air cuts): when one sits on the kept side of an edge in the same pause (nothing
    louder than `silence` dB between them, by default the dead-air cutter's own threshold), the edge moves
    onto it however far it is, so no sliver of a few frames is left between two jump cuts. It then takes the
    nearest frame start on the kept side of the join, so no frame of the piece being cut can show: after a
    join, the first frame can start a few ms early or late (variable-rate or late-starting clips). A kept
    word whose transcript edge lies up to JOIN_SLACK past such a join (Whisper's rounding) counts as ending
    at it. A cut whose edges both settled on one quiet dip (nothing louder between them) and would remove
    less than MIN_REMOVED of its words' sound keeps its approved edges instead. Returns the kept pieces,
    every edge on a frame start.
    """
    if frames is not None and len(frames):
        grid = np.asarray(frames, dtype=float)
    else:
        step = 1.0 / info.fps if info.has_video and info.fps else HOP
        origin = max(0.0, info.video_start - info.format_start) if info.has_video and info.fps else 0.0
        grid = origin + np.arange(math.floor((duration - origin) / step + 1e-6) + 1) * step
    tol = 1e-6               # float noise: a join summed from a report's cuts vs the frame it was cut on
    offset = max(0.0, info.audio_start - info.format_start)
    silence = choose_threshold(db, None)[0] if silence is None else silence
    words = sorted((float(a), float(b)) for a, b in words)
    mids = [(a + b) / 2 for a, b in words]

    def level(t: float) -> float:
        """The louder of the two 10 ms steps that meet at t (past the audio counts as silence)."""
        j = round((t - offset) / HOP)
        seg = db[max(0, j - 1):max(0, j + 1)]
        return float(seg.max()) if seg.size else -100.0

    def same_pause(x: float, y: float) -> bool:
        i, j = sorted(round((t - offset) / HOP) for t in (x, y))
        return not (db[max(0, i):max(0, j)] > silence).any()

    def power(a: float, b: float) -> float:
        """The sound energy between a and b (sum of the 10 ms steps' power)."""
        seg = db[max(0, round((a - offset) / HOP)):max(0, round((b - offset) / HOP))]
        return float((10.0 ** (seg / 10.0)).sum())

    def kept_side(j: float, kept: int) -> float | None:
        """The frame start nearest the join `j` on its kept side."""
        g = grid[grid <= j + tol] if kept < 0 else grid[grid >= j - tol]
        return float(g[-1] if kept < 0 else g[0]) if g.size else None

    def place(t: float, lo: float, hi: float, kept: int) -> float:
        """The edge's new time; `kept` is -1 when the kept side is before it (a cut's start), +1 after it."""
        if lo <= hi:
            t = min(max(t, lo), hi)
        a, b = max(t - REACH, lo, 0.0), min(t + REACH, hi, duration)
        points = grid[(grid >= a - tol) & (grid <= b + tol)]
        if not points.size:
            return t
        levels = [level(p) for p in points]
        best = float(min((p for p, lv in zip(points, levels) if lv <= min(levels) + TIE_DB),
                         key=lambda p: abs(p - t)))
        near = [(abs(j - best), p) for j in joins if lo <= j <= hi and kept * (j - best) >= 0
                and same_pause(j, best) and (p := kept_side(j, kept)) is not None and lo <= p <= hi]
        return min(near)[1] if near else best

    cuts, held = [], []
    for s0, e0 in cuts_from_keeps(keeps, duration):
        s, e = s0, e0
        cut_words = [w for w, m in zip(words, mids) if s0 <= m <= e0]
        if not cut_words and any(a <= s0 and e0 <= b for a, b in words):
            continue                # inside a word that is kept: left out, never moved into the pause beside it
        inner = [(a + b) / 2 for a, b in cut_words] or [(s0 + e0) / 2]     # a cut without words: its middle
        left = max((b for (a, b), m in zip(words, mids) if m < s0), default=0.0)        # kept words: hard limits
        right = min((a for (a, b), m in zip(words, mids) if m > e0), default=duration)
        # A kept word's transcript edge can sit a hair past a dead-air join in the pause beside it (Whisper
        # rounds to 20 ms). The join belongs to that pause, so the limit moves onto it; else it is never used
        # and one frame of the piece being cut shows between two jump cuts.
        for j in joins:
            if right < j <= right + JOIN_SLACK and same_pause(right, j):
                p = kept_side(j, 1)
                right = max(j, p if p is not None else j)
            if left - JOIN_SLACK <= j < left and same_pause(j, left):
                p = kept_side(j, -1)
                left = min(j, p if p is not None else j)
        # An edge that splits a word being cut starts from that word's edge.
        ts = next((a for a, b in cut_words if a < s0 < b), s0)
        te = next((b for a, b in cut_words if a < e0 < b), e0)
        if s0 > 0:
            s = place(ts, left, max(left, min(inner[0], right)), -1)
        if e0 < duration:
            e = place(te, min(right, max(inner[-1], left)), right, 1)
        # Both edges can settle on one quiet dip inside the word being cut (a stop, like the "t" in "first"):
        # the word would stay audible while the transcript drops it. Then the approved edges stand instead.
        # Only on one dip: edges in two gaps around a loud word remove it, even when Whisper drew that word so
        # wide that its span holds the ends of the kept words beside it (and so more sound than it has).
        if cut_words:
            wa, wb = cut_words[0][0], cut_words[-1][1]
            between = db[max(0, round((s - offset) / HOP)):max(0, round((e - offset) / HOP))]
            one_dip = not between.size or between.max() <= max(level(s), level(e)) + TIE_DB
            if one_dip and power(max(s, wa), min(e, wb)) < MIN_REMOVED * power(wa, wb):
                s = max(ts, left) if s0 > 0 else s
                e = min(te, right) if e0 < duration else e
                held.append(fmt_time(wa))
        if e - s > 1e-6:            # a cut squeezed shut lay inside a kept word: it is left out
            cuts.append((s, e))
    if held:
        print(f"    no quiet point between the words at {', '.join(held)}: "
              f"{'those cuts keep' if len(held) > 1 else 'that cut keeps'} the approved edges, so listen there")
    out: list[tuple[float, float]] = []
    for a, b in keeps_from_cuts(sorted(cuts), duration):
        # Outward onto frame starts (edges placed above are on them already), so picture and sound match.
        before, after = grid[grid <= a + tol], grid[grid >= b - tol]
        a = float(before[-1]) if a > 0 and before.size else a
        b = min(float(after[0]), duration) if b < duration and after.size else b
        if out and a <= out[-1][1] + tol:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        elif ((grid >= a - tol) & (grid < b - tol)).any():     # a piece holding no frame start is dropped
            out.append((a, b))
    return out


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
    report["duration_before"] = info.duration
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
                  # 9 decimals, not 3: later passes sum them into joins that must land on the frames cut.
                  cuts=[[round(a, 9), round(b, 9)] for a, b in cuts])

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


def cut_keeps(args) -> int:
    """The mistake cutter's renderer: keep the EDL's keep_ranges, every cut edge measured on the waveform."""
    from timemap import TimeMap
    from transcribe import load_words
    t0 = time.time()
    if len(args.files) != 1:
        print("Give exactly one video with --keeps.")
        return 2
    src, edl_path, dest = args.files[0], args.keeps, args.render
    if dest and (project_root() / "input").resolve() in dest.resolve().parents:
        print("Refusing to write into input/: that folder is only for the original videos.")
        return 2
    if dest and dest.exists() and src.exists() and dest.samefile(src):    # samefile: WORK/x.mp4 is work/x.mp4 too
        print("Refusing to write over the video being cut: give the cut video another name.")
        return 2
    info = probe(src)
    if not info.has_audio:
        print(f"{src.name} has no audio track, so its cuts can't be measured.")
        return 2
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    # A transcript's length (faster-whisper's decode) can be a few ms off the file's, either way: the file wins,
    # and a piece kept to the transcript's end is kept to the file's end.
    end = float(edl.get("source_duration") or info.duration)
    duration = info.duration or end
    raw = [(float(k["start"]), duration if float(k["end"]) >= end - 1e-6 else min(float(k["end"]), duration))
           for k in edl["keep_ranges"] if float(k["start"]) < duration]
    words = [(w["start"], w["end"]) for w in load_words(args.words)] if args.words else []
    # When this video is a dead-air cut (work/<name>.mp4), its report says where its joins are. A failed run
    # rewrites the report with cuts this video doesn't have: only "done" counts.
    report, joins, silence = src.parent / "reports" / f"{src.stem}.json", [], None
    if report.is_file():
        try:
            r = json.loads(report.read_text(encoding="utf-8"))
            out, here = Path(r.get("output", "")), src.resolve()
            # The report keeps absolute paths: after the project folder moved, the same folder and file name count.
            ours = out.resolve() == here or (not out.exists() and
                                             (out.parent.name, out.name) == (here.parent.name, here.name))
            if r.get("status") == "done" and r.get("cuts") and ours:
                joins = TimeMap.from_cuts(r["cuts"], float(r["duration_before"])).joins()
                silence = float(r["threshold_db"])
        except (OSError, ValueError, KeyError, TypeError):
            joins = []
            print(f"    note: reports/{report.name} could not be read, so the edges can't line up with "
                  "its dead-air cuts (run the dead-air step again with --overwrite to rewrite it)")
    frames = frame_times(info) if info.has_video else None
    keeps = quiet_edges(raw, words, measure_loudness(info), info, duration, joins, silence, frames)
    # Floored to the microsecond the filter graph is written in, so a piece never ends just past a frame start
    # (with a fine time base, rounding up would keep that frame) nor starts just after one.
    keeps = [(math.floor(a * 1e6 + 1e-3) / 1e6, math.floor(b * 1e6 + 1e-3) / 1e6) for a, b in keeps]
    if not keeps:
        print("Nothing would be left after these cuts.")
        return 1
    kept = sum(b - a for a, b in keeps)
    moved = max((abs(x - y) for p, q in zip(raw, keeps) for x, y in zip(p, q)), default=0.0) \
        if len(raw) == len(keeps) else 0.0
    cuts, pieces = len(cuts_from_keeps(keeps, duration)), len(keeps)
    lost = len(cuts_from_keeps(raw, duration)) - cuts
    plural = lambda n, word: f"{n} {word}" + ("" if n == 1 else "s")  # noqa: E731
    print(f"{src.name}: " + (f"{plural(cuts, 'cut')} measured on the waveform" if cuts else "no cuts to make")
          + (f", edges moved up to {moved:.2f}s to a quiet {'whole frame' if info.has_video else '10 ms step'}"
             if moved >= 0.005 else ""))
    if lost > 0:
        print(f"    {plural(lost, 'approved cut')} merged with a neighbour or left out "
              "(a cut inside a kept word is skipped)")
    print(f"    {fmt_time(duration)} -> {fmt_time(kept)} in {plural(pieces, 'piece')}"
          + (f", {FADE * 1000:.0f} ms fade at every join" if pieces > 1 else ""))
    if args.graph and not dest:
        args.graph.write_text(filter_graph(keeps, info), encoding="utf-8")
    if dest:
        print(f"    rendering the cut video -> {dest}", flush=True)
        partial = dest.with_name(f"{dest.stem}.partial{dest.suffix}")
        graph = args.graph or dest.with_name(f"{dest.stem}.filtergraph.txt")
        codec = render(info, keeps, partial, graph, args.crf, args.speed)
        if not args.graph:
            graph.unlink(missing_ok=True)
        problems = verify(partial, kept, len(keeps), info)
        if problems:
            print(f"    FAILED: {'; '.join(problems)} (kept for inspection: {partial})")
            return 1
        partial.replace(dest)
        print(f"    OK  {dest}  ({codec}; length and A/V sync checked; {time.time() - t0:.1f}s)")
        # verify() allows half a second; the saved timings promise the length to one frame.
        frame = float(np.median(np.diff(frames))) if frames is not None and len(frames) > 1 else 0.0
        off = probe(dest).duration - kept
        if frame and abs(off) > frame + 1e-6:
            print(f"    WARNING: the cut video is {abs(off) * 1000:.0f} ms {'longer' if off > 0 else 'shorter'} "
                  "than the kept pieces (more than one frame), so timings saved from it may drift")
    edl["source_duration"] = round(duration, 6)
    edl["keep_ranges"] = [{"start": round(a, 6), "end": round(b, 6)} for a, b in keeps]
    edl_path.write_text(json.dumps(edl, indent=2), encoding="utf-8")
    return 0


def print_report(i: int, total: int, src: Path, r: dict) -> None:
    print(f"[{i}/{total}] {src.name}", flush=True)
    if "duration_after" in r:
        before, after = round(r["duration_before"], 3), r["duration_after"]
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
        shown = ", ".join(f"{fmt_time(round(a, 3))}-{fmt_time(round(b, 3))}" for a, b in cuts[:12])
        more = f" (+{len(cuts) - 12} more)" if len(cuts) > 12 else ""
        print(f"    cuts: {shown or 'none'}{more}")
        print(f"    would write: {r['output']}")
    elif status == "done":
        print(f"    OK  {r['output']}  ({r['codec']}; length and A/V sync checked; {r['seconds_taken']}s)")
    else:
        print(f"    {status.upper()}: {r.get('reason', '')}")


def self_test() -> int:
    """Cut-edge search on a made-up loudness track: no media, no ffmpeg."""
    info = MediaInfo(Path("talk.mp4"), duration=4.0, format_start=0.0, has_video=True, has_audio=True, fps=25.0)
    db = np.full(400, -70.0)
    for a, b in [(0.50, 0.90), (1.00, 1.40), (1.50, 1.90), (2.60, 3.00)]:     # where the voice really is
        db[round(a / HOP):round(b / HOP)] = -20.0
    # Transcript times as Whisper gives them: words touch, and their edges are up to 50 ms off the voice.
    words = [(0.45, 0.95), (0.95, 1.45), (1.45, 1.95), (2.55, 3.05)]
    on_frame = lambda keeps: all(abs(t * 25 - round(t * 25)) < 1e-6 for k in keeps for t in k)  # noqa: E731
    near = lambda got, want: len(got) == len(want) and all(  # noqa: E731
        abs(x - y) < 1e-6 for p, q in zip(got, want) for x, y in zip(p, q))

    # The cut starts in the middle of the kept word "one": the edge moves out of it, into the gap after it.
    # Its end, on the touching edge of the kept "two", moves back into the quiet before that word.
    keeps = quiet_edges([(0.0, 0.75), (1.45, 4.0)], words, db, info, 4.0)
    assert near(keeps, [(0.0, 0.96), (1.44, 4.0)]) and on_frame(keeps), keeps
    # The cut ends in the middle of the cut word "two": the edge moves to that word's end, into the gap.
    keeps = quiet_edges([(0.0, 0.95), (1.30, 4.0)], words, db, info, 4.0)
    assert near(keeps, [(0.0, 0.96), (1.44, 4.0)]), keeps
    # In silence an edge stays where it was put (to the nearest frame): the quiet ties, the nearest wins.
    keeps = quiet_edges([(0.0, 2.10), (2.40, 4.0)], words, db, info, 4.0)
    assert abs(keeps[0][1] - 2.10) <= 0.02 + 1e-6 and abs(keeps[1][0] - 2.40) < 1e-6, keeps
    # ...unless the video already has a join on the kept side, in the same pause: then the edge lands on it
    # (on the frame start nearest it on the kept side, for a join a hair off its frame).
    keeps = quiet_edges([(0.0, 2.10), (2.40, 4.0)], words, db, info, 4.0, joins=[2.0004, 2.48])
    assert near(keeps, [(0.0, 2.0), (2.48, 4.0)]), keeps
    # Frames read from a file can be unevenly spaced: after a join the next piece's first frame may start late
    # (2.012: a clip whose video started late) or early (1.996: a variable frame rate). The edge takes the frame
    # start on its kept side of the join, so no frame of the piece being cut shows and the cut map gets no
    # phantom piece between the join and the edge.
    for first, end_edge, start_edge in ((2.012, 1.96, 2.012), (1.996, 1.996, 2.036)):
        frames = np.concatenate([np.arange(50) * 0.04, first + np.arange(50) * 0.04])
        keeps = quiet_edges([(0.0, 2.10), (2.60, 4.0)], words, db, info, 4.0, joins=[2.0], frames=frames)
        assert near(keeps[:1], [(0.0, end_edge)]) and keeps[1][0] in frames, keeps
        keeps = quiet_edges([(0.0, 1.45), (1.95, 4.0)], words, db, info, 4.0, joins=[2.0], frames=frames)
        assert near(keeps, [(0.0, 1.48), (start_edge, 4.0)]), keeps
    # However far it is (0.15 s and 0.27 s from the word edges here, out of REACH), so no sliver of a few
    # frames is left between two jump cuts.
    keeps = quiet_edges([(0.0, 2.55), (3.05, 4.0)], words, db, info, 4.0, joins=[2.40, 3.32])
    assert near(keeps, [(0.0, 2.40), (3.32, 4.0)]), keeps
    # A join on the far side of a sound is never used: the transcript has no "one" and "two" here, so only
    # the waveform knows that cutting from 0.96 would remove them.
    keeps = quiet_edges([(0.0, 1.45), (1.95, 4.0)], words[2:], db, info, 4.0, joins=[0.96])
    assert near(keeps, [(0.0, 1.44), (1.96, 4.0)]), keeps
    # A cut inside a word whose middle is kept would cut into a kept word: it is left out, whether the
    # word touches the one before it or has a pause before it (that pause is not cut either).
    keeps = quiet_edges([(0.0, 1.05), (1.15, 4.0)], words, db, info, 4.0)
    assert near(keeps, [(0.0, 4.0)]), keeps
    keeps = quiet_edges([(0.0, 2.70), (2.75, 4.0)], words, db, info, 4.0)
    assert near(keeps, [(0.0, 4.0)]), keeps
    # A restart word that Whisper starts 10 ms before the dead-air join (2.56), and a kept word it ends 30 ms
    # after one (0.92): the edges still land on the joins, so no frame of the removed take shows.
    keeps = quiet_edges([(0.0, 0.95), (2.55, 4.0)], words, db, info, 4.0, joins=[0.92, 2.56])
    assert near(keeps, [(0.0, 0.92), (2.56, 4.0)]), keeps
    # A stutter in connected speech ("need to to plan", no gaps), with a stop's quiet dip inside the first
    # "to": both edges would settle on that dip (0.80) and leave the word audible, so the approved edges stand
    # (on the whole frames inside them; the kept pieces round outward).
    speech = np.full(400, -70.0)
    speech[40:150] = -20.0
    speech[79:81] = -60.0                       # around the frame start at 0.80
    talk = [(0.40, 0.70), (0.70, 0.90), (0.90, 1.10), (1.10, 1.50)]
    keeps = quiet_edges([(0.0, 0.70), (0.90, 4.0)], talk, speech, info, 4.0)
    assert near(keeps, [(0.0, 0.72), (0.88, 4.0)]), keeps
    # A stutter with real gaps ("need to, to plan") that Whisper draws 80 ms too wide on each side, so its span
    # holds the ends of the kept "need" and "to" (more sound than the cut "to" has): the edges land in the two
    # gaps around it, not on the approved edges inside the kept words.
    gaps = np.full(400, -70.0)
    for a, b in [(0.40, 0.74), (0.84, 0.94), (0.98, 1.20), (1.30, 1.70)]:
        gaps[round(a / HOP):round(b / HOP)] = -20.0
    wide = [(0.40, 0.66), (0.66, 1.06), (1.06, 1.20), (1.20, 1.70)]
    keeps = quiet_edges([(0.0, 0.66), (1.06, 4.0)], wide, gaps, info, 4.0)
    assert near(keeps, [(0.0, 0.76), (0.96, 4.0)]), keeps
    # Without video (audio only) edges land on 10 ms steps instead of frames.
    audio = MediaInfo(Path("talk.m4a"), duration=4.0, format_start=0.0, has_video=False, has_audio=True)
    keeps = quiet_edges([(0.0, 0.75), (1.45, 4.0)], words, db, audio, 4.0)
    assert 0.90 <= keeps[0][1] <= 1.0 and 1.40 <= keeps[1][0] <= 1.45, keeps
    print("cut_dead_air self-test: OK")
    return 0


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
    p.add_argument("--self-test", action="store_true", help="check the cut-edge search and exit")
    m = p.add_argument_group("mistake cuts (cut-mistakes/scripts/apply-cuts.mjs runs these)")
    m.add_argument("--keeps", type=Path, metavar="EDL",
                   help="keep only this mistakes-edl.json's keep_ranges, each cut edge moved to the quietest "
                        "whole frame near its word edge (or onto a dead-air cut in the same pause); the ranges "
                        "and the source length used are written back")
    m.add_argument("--words", type=Path, metavar="TRANSCRIPT", help="the video's word timings: kept words are never cut into")
    m.add_argument("--graph", type=Path, metavar="FILE", help="also save the ffmpeg filter graph here")
    m.add_argument("--render", type=Path, metavar="FILE", help="render the cut video here (without it: measure only)")
    args = p.parse_args()
    if (args.words or args.graph or args.render) and not args.keeps:
        p.error("--words, --graph and --render go with --keeps")
    if args.self_test:
        return self_test()
    if args.keeps:
        try:
            return cut_keeps(args)
        except Exception as e:  # a plain message for the owner, not a traceback
            print(f"FAILED: {e}")
            return 1

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
                # A preview keeps the report of the cut already made: the later steps read its joins.
                if not args.analyze and (r["status"] != "skipped" or "duration_after" in r):
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
