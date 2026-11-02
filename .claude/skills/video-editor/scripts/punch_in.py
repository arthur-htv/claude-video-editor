#!/usr/bin/env python3
"""Punch-ins on jump cuts: switch the framing between full and a little tighter at the joins.

Every dead-air and mistake cut is a jump cut at the same framing. Editors hide jump cuts by changing
the framing on the cut: full, then about 112%, then full again. This pass does that after the cuts
and before the graphics.
  - The joins come from the saved cut lists (timemap.py; it stops when they don't fit the video, such as a
    mistake list run on the dead-air cut), or from --joins. Each one is moved onto the
    frame where the picture really jumps: on phone videos (uneven frame times) the lists drift a frame
    or two from the real cut, and a switch a frame early would flash the old shot at the new framing.
  - It starts at full framing and switches at a join only when each framing stays on screen for at
    least 2 s, so a join close to the last switch (or to the start or end) keeps its framing.
  - The tighter framing is centred on the face and never crops it: when the face is too big for the
    zoom, the zoom is lowered for the whole video (below 105% there are no punch-ins). With no face
    found, it is centred on the upper middle of the frame.
  - The picture is encoded once and the sound is copied untouched. Size, frame rate, frame count and
    length stay the same, and the script checks them.
  - It prints the face box at the punch-in (graphics are placed with it), and writes
    work/<name>.punch.json and a check sheet with the frames on both sides of every switch.

Examples (from the project folder, with the .venv python)
  python punch_in.py work/talk.v.mp4 --name talk --out work/talk.p.mp4
  python punch_in.py work/talk.mp4 --joins "2.5,7.1" --out work/talk.p.mp4
  python punch_in.py work/talk.mp4 --name talk --zoom 1.08 --overwrite      a gentler punch-in
  python punch_in.py work/talk.mp4 --name talk --zoom 1.0                   off: copies the video unchanged
  python punch_in.py --self-test
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import math
import re
import subprocess
import sys
import tempfile
from bisect import bisect_left, bisect_right
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timemap  # noqa: E402
from cut_dead_air import output_args, run_ffmpeg, video_codec_args  # noqa: E402
from hfbuild import contact_sheet  # noqa: E402
from layout import analyze  # noqa: E402
from vtools import (MediaInfo, SetupError, ffmpeg_version, find_tool, fmt_time, probe,  # noqa: E402
                    project_root, run)

ZOOM = 1.12        # the punch-in: 112% of the full frame
MAX_ZOOM = 1.5     # past this the picture goes soft and reads as another shot, not a punch-in
MIN_ZOOM = 1.05    # a punch-in lowered below this reads as a camera bump, so there is none
HOLD = 2.0         # seconds each framing stays on screen at least
FACE_PAD = 0.15    # face boxes stop at the brow and the mouth: keep this much of the box more on each side
CRF, SPEED = 18, "fast"
SMALL = 96         # frames shrunk to 96x96 grey to find the cuts: enough to see one, quick to read
VISIBLE = 1.0      # mean grey-level change between two frames that shows as a cut (encoder noise is ~0.3)
STANDS_OUT = 1.3   # a cut changes the picture at least this much more than the frames around it


class Abort(Exception):
    """Stop with a plain-English reason."""


def even(v: float) -> int:
    return int(v) // 2 * 2


def box_text(box) -> str:
    return f"x {box[0]:.2f}-{box[2]:.2f}, y {box[1]:.2f}-{box[3]:.2f}"


def keep_frames() -> list[str]:
    """Every frame keeps its own time: ffmpeg adds or drops none to even out the frame rate."""
    return ["-fps_mode", "passthrough"] if ffmpeg_version() >= (5, 1) else ["-vsync", "passthrough"]


def display_size(info: MediaInfo) -> tuple[int, int]:
    """Width and height as played. A phone clip stored sideways with a rotation flag is turned upright
    by ffmpeg before any filter sees it, so the crop is sized for the upright frame."""
    out = run([find_tool("ffprobe"), "-v", "error", "-select_streams", f"v:{info.video_index}",
               "-show_entries", "stream_side_data=rotation", "-of", "csv=p=0", str(info.path)]).stdout
    m = re.search(r"-?\d+", out)
    turned = bool(m) and abs(int(m.group())) % 180 == 90
    return (info.height, info.width) if turned else (info.width, info.height)


# ----------------------------------------------------------------------------- the plan

def plan_pieces(joins, duration: float, zoom: float) -> list[tuple[float, float, float]]:
    """(start, end, zoom) pieces covering the video: full framing first, then a switch at every join
    that leaves both framings around it on screen for at least HOLD seconds."""
    switches, last = [], 0.0
    for j in sorted({float(j) for j in joins}):
        if j - last >= HOLD - 1e-6 and duration - j >= HOLD - 1e-6:
            switches.append(j)
            last = j
    edges = [0.0, *switches, float(duration)]
    return [(a, b, zoom if i % 2 else 1.0) for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def padded(face):
    x0, y0, x1, y1 = face
    dx, dy = FACE_PAD * (x1 - x0), FACE_PAD * (y1 - y0)
    return max(0.0, x0 - dx), max(0.0, y0 - dy), min(1.0, x1 + dx), min(1.0, y1 + dy)


def fit_zoom(face, zoom: float) -> float:
    """The asked zoom, lowered to the nearest 0.01 that still holds the whole (padded) face."""
    if face is None:
        return zoom
    x0, y0, x1, y1 = padded(face)
    return min(zoom, math.floor(100 / max(x1 - x0, y1 - y0, 0.01)) / 100)


def crop_box(width: int, height: int, zoom: float, face) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the tighter framing in pixels: inside the frame, centred on the face as far as
    the frame allows, and holding the whole padded face. With no face: the upper middle."""
    cw = min(even(width), even(math.ceil(width / zoom) + 1))
    ch = min(even(height), even(math.ceil(height / zoom) + 1))
    x0, y0, x1, y1 = padded(face) if face else (0.5, 1 / 3, 0.5, 1 / 3)
    cx, cy = ((face[0] + face[2]) / 2, (face[1] + face[3]) / 2) if face else (0.5, 1 / 3)

    def place(size: int, crop: int, centre: float, lo_edge: float, hi_edge: float) -> int:
        lo, hi = max(0.0, hi_edge * size - crop), min(lo_edge * size, size - crop)
        return even(min(max(centre * size - crop / 2, lo), hi))

    return place(width, cw, cx, x0, x1), place(height, ch, cy, y0, y1), cw, ch


def frame_plan(width: int, height: int, duration: float, joins, zoom: float, face) -> dict:
    """What the pass does to one video (pieces, zoom, crop, face boxes), with notes for the user."""
    notes = []
    fit = fit_zoom(face, zoom) if zoom > 1.0 else 1.0
    if fit < zoom and fit < MIN_ZOOM:
        notes.append(f"The face is too big to punch in without cropping it (it would be under "
                     f"{MIN_ZOOM * 100:.0f}%), so there are no punch-ins.")
        fit = 1.0
    elif fit < zoom:
        notes.append(f"The face is too big to punch in to {zoom * 100:.0f}% without cropping it, "
                     f"so every punch-in is {fit * 100:.0f}% instead.")
    elif zoom <= 1.0:
        notes.append("Punch-ins are off (zoom 1.0).")
    zoom = fit
    pieces = plan_pieces(joins, duration, zoom) if zoom > 1.0 else [(0.0, float(duration), 1.0)]
    plan = {"zoom": zoom, "pieces": pieces, "crop": None, "face": face, "face_at_punch_in": face, "notes": notes}
    if len(pieces) == 1:
        if zoom > 1.0:
            notes.append(f"No join has {HOLD:g} s on both sides, so there is nothing to punch in on." if joins
                         else "Nothing was cut, so there are no jump cuts to punch in on.")
        return plan
    x, y, cw, ch = plan["crop"] = crop_box(width, height, zoom, face)
    if face:
        notes.append(f"face at {box_text(face)}; the punch-in is centred on it")
        plan["face_at_punch_in"] = ((face[0] * width - x) / cw, (face[1] * height - y) / ch,
                                    (face[2] * width - x) / cw, (face[3] * height - y) / ch)
        notes.append(f"face at the punch-in: {box_text(plan['face_at_punch_in'])}")
    else:
        notes.append("No face found, so the punch-in is centred on the upper middle of the frame.")
    return plan


# ----------------------------------------------------------------------------- finding the real cuts

def frame_changes(info: MediaInfo) -> tuple[list[float], list[float], float]:
    """(times, changes, origin): each frame's time in seconds after the first frame, how much its
    picture differs from the frame before, and where the first frame sits for an ffmpeg -ss seek."""
    import numpy as np

    listed = run([find_tool("ffprobe"), "-v", "error", "-select_streams", f"v:{info.video_index}",
                  "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(info.path)]).stdout
    pts = sorted(float(v) for v in listed.replace(",", " ").split() if v != "N/A")
    cmd = [find_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(info.path), "-map", f"0:v:{info.video_index}",
           "-vf", f"scale={SMALL}:{SMALL}:flags=area", *keep_frames(), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    changes, prev, size = [], None, SMALL * SMALL
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        while len(buf := proc.stdout.read(size)) == size:
            cur = np.frombuffer(buf, np.uint8).astype(np.int16)
            changes.append(0.0 if prev is None else float(np.abs(cur - prev).mean()))
            prev = cur
    if not pts or len(changes) != len(pts):
        raise Abort(f"Only {len(changes)} of the {len(pts)} frames listed in {info.path.name} could be read, so its "
                    "cuts can't be placed on frames. Run punch-ins on the cut video the cutters wrote: a camera "
                    "file can list frames it never shows.")
    return [t - pts[0] for t in pts], changes, pts[0] - info.format_start


def snap_joins(joins, times, changes, drift: float | None = None,
               length: float | None = None) -> list[tuple[int, bool]]:
    """(frame, seen) for each join: the frame where its new piece starts, and whether the cut shows.

    The cut lists time each join from the kept pieces' lengths. On a video with uneven frame times the
    real cut lands up to a frame or two later, more with each cut; `drift` is how much longer the video
    is than the lists (at `length`). A join takes the frame with the biggest picture change near its
    time when that change clearly stands out. Any other join (no visible jump) goes to the frame
    nearest its time plus the drift measured at the cuts around it. drift=None means times typed by
    hand: searched a little wider (they are rounded), and with no visible jump they keep their time."""
    import numpy as np

    step = times[-1] / (len(times) - 1) if len(times) > 1 else 1 / 30
    pad = 1.5 * step + (0.05 if drift is None else 0.0)
    before, after = pad + max(0.0, -(drift or 0.0)), pad + max(0.0, drift or 0.0)
    seen = {}
    for j in joins:
        near = range(max(1, bisect_left(times, j - before)), min(len(times), bisect_right(times, j + after)))
        if len(near) < 2:
            continue
        best = max(near, key=changes.__getitem__)
        rest = sorted(changes[k] for k in near if k != best)
        if changes[best] >= max(VISIBLE, STANDS_OUT * rest[len(rest) // 2]):
            seen[j] = best
    measured = {} if drift is None else {j: times[k] - j for j, k in seen.items()}
    anchors = sorted({0.0: 0.0, (times[-1] if length is None else length): drift or 0.0, **measured}.items())
    out = []
    for j in joins:
        if j in seen:
            out.append((seen[j], True))
            continue
        t = j + float(np.interp(j, [a for a, _ in anchors], [d for _, d in anchors]))
        i = min(bisect_left(times, t), len(times) - 1)
        out.append((i - 1 if i > 0 and t - times[i - 1] < times[i] - t else i, False))
    return out


# ----------------------------------------------------------------------------- render and check

def audio_args(info: MediaInfo, dest: Path) -> tuple[list[str], str]:
    """The sound is copied untouched, except PCM going into an MP4, which many players won't play."""
    if info.audio_codec.startswith("pcm_") and dest.suffix.lower() == ".mp4":
        return ["-c:a", "aac", "-b:a", "192k"], "PCM sound turned into AAC, which MP4 players expect"
    return ["-c:a", "copy"], "sound copied untouched"


def render(info: MediaInfo, plan: dict, dest: Path, size: tuple[int, int]) -> str:
    """One encode: the full picture, with the tighter framing laid over it on the punched-in frames.
    They are counted by frame number, so a switch lands exactly on its cut frame, and every frame keeps
    its own time. With no crop it is a plain encode (a copy the container refused)."""
    w, h = size
    even_size = "scale=trunc(iw/2)*2:trunc(ih/2)*2" if (w % 2 or h % 2) else "null"
    src = f"[0:v:{info.video_index}]"
    if plan["crop"]:
        x, y, cw, ch = plan["crop"]
        edges = [*plan["frames"], len(plan["times"])]
        tight = "+".join(f"between(n,{a},{b - 1})" for (_, _, z), a, b in zip(plan["pieces"], edges, edges[1:])
                         if z > 1.0)
        graph = (f"{src}split[full][z];[z]crop={cw}:{ch}:{x}:{y},scale={w}:{h}[tight];"
                 f"[full][tight]overlay=format=auto:enable='{tight}',{even_size}[outv]")
    else:
        graph = f"{src}{even_size}[outv]"
    vargs, label = video_codec_args(info, CRF, SPEED)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(info.path), "-filter_complex", graph,
           "-map", "[outv]", *vargs, *keep_frames(), "-map", "0:a?", *audio_args(info, dest)[0],
           "-map_metadata", "0", *output_args(dest), "-progress", "pipe:1", "-nostats", str(dest)]
    run_ffmpeg(cmd, info.duration, info.path.name)
    return label


def copy_through(info: MediaInfo, plan: dict, dest: Path, size: tuple[int, int]) -> str:
    """No switches: copy the streams as they are (encode the picture only if the container refuses it)."""
    hvc1 = ["-tag:v", "hvc1"] if info.video_codec == "hevc" and dest.suffix.lower() in (".mp4", ".mov") else []
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(info.path),
           "-map", f"0:v:{info.video_index}", "-map", "0:a?", "-c", "copy", *hvc1, *audio_args(info, dest)[0],
           "-map_metadata", "0", *output_args(dest), str(dest)]
    if run(cmd).returncode == 0:
        return "copied without re-encoding"
    return render(info, plan, dest, size)


def frame_count(path: Path, index: int) -> int:
    out = run([find_tool("ffprobe"), "-v", "error", "-select_streams", f"v:{index}", "-count_packets",
               "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)]).stdout
    nums = re.findall(r"\d+", out)            # MPEG-TS prints the count twice (program and stream)
    return int(nums[0]) if nums else -1


def verify(src: MediaInfo, dest: Path, size: tuple[int, int]) -> tuple[int, list[str]]:
    """(frames, problems): problems is empty when size, frame rate, frame count and length match the input."""
    out = probe(dest)
    problems = []
    ow, oh = display_size(out)
    if abs(ow - size[0]) > 1 or abs(oh - size[1]) > 1:
        problems.append(f"the picture is {ow}x{oh}, the input is {size[0]}x{size[1]}")
    if abs((out.fps or 0) - (src.fps or 0)) > 0.01:
        problems.append(f"{out.fps} frames a second, the input has {src.fps}")
    n_in, n_out = frame_count(src.path, src.video_index), frame_count(dest, out.video_index)
    if n_out != n_in:
        problems.append(f"{n_out} frames, the input has {n_in}")
    if abs(out.duration - src.duration) > 1 / (src.fps or 30):
        problems.append(f"{out.duration:.3f} s long, the input is {src.duration:.3f} s")
    if src.has_audio and not out.has_audio:
        problems.append("the sound is missing")
    return n_out, problems


def tag_pairs(png: Path, count: int, cols: int) -> None:
    """Write 'before' and 'after' on each pair of frames: the sheet's own time labels round to 0.1 s,
    so both frames of a pair often carry the same one."""
    from PIL import Image, ImageDraw

    img = Image.open(png).convert("RGB")
    cw, ch = img.width // min(cols, count), img.height // -(-count // cols)
    draw = ImageDraw.Draw(img)
    for i in range(count):
        x, y = (i % cols) * cw, (i // cols) * ch
        draw.rectangle((x, y, x + 52, y + 18), fill="#000")
        draw.text((x + 6, y + 4), "after" if i % 2 else "before", fill="#ffd84a" if i % 2 else "#ffffff")
    img.save(png)


def apply(info: MediaInfo, plan: dict, out: Path, sheet: Path, size: tuple[int, int]) -> str:
    """Render (or copy) into `out`, check it, and draw the check sheet. Returns the lines to print."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.stem}.partial{out.suffix}")
    try:
        label = (render if len(plan["pieces"]) > 1 else copy_through)(info, plan, partial, size)
    except BaseException as e:
        partial.unlink(missing_ok=True)       # a failed render leaves nothing half-written behind
        if type(e) is RuntimeError:           # ffmpeg's own error: say what happened first
            raise Abort(f"The punch-in render failed, so nothing was written. {e}") from e
        raise
    frames, problems = verify(info, partial, size)
    if problems:
        raise Abort(f"The result failed its check ({'; '.join(problems)}). It is kept for a look: {partial}")
    partial.replace(out)
    page_name = re.compile(re.escape(sheet.stem) + r"(-\d+)?" + re.escape(sheet.suffix))
    for old in sheet.parent.glob(glob.escape(sheet.stem) + "*" + sheet.suffix):
        if page_name.fullmatch(old.name):     # pages left from an earlier run
            old.unlink()
    line = (f"OK {out} ({label}; {frames} frames and {info.duration:.3f} s, the same as the input; "
            f"{audio_args(info, out)[1] if info.has_audio else 'no sound'})")
    if len(plan["pieces"]) > 1:
        t, origin = plan["times"], plan["origin"]
        seeks = []   # halfway between frames, so the seek can't round onto the neighbour
        for i in plan["frames"][1:]:
            seeks += [origin + (t[i - 2] + t[i - 1]) / 2, origin + (t[i - 1] + t[i]) / 2]
        pages = []   # 6 switches a page: one tall sheet would shrink each frame too far to judge a face
        for i in range(0, len(seeks), 12):
            page = sheet if i == 0 else sheet.with_name(f"{sheet.stem}-{i // 12 + 1}{sheet.suffix}")
            contact_sheet(out, seeks[i:i + 12], page, width=360, cols=4)
            tag_pairs(page, len(seeks[i:i + 12]), 4)
            pages.append(str(page))
        line += (f"\ncheck sheet: {', '.join(pages)} (the last frame before and the first frame after "
                 "each switch, two switches a row)")
    return line


def report(video: Path, out: Path, plan: dict) -> dict:
    r3 = lambda box: [round(v, 3) for v in box] if box else None  # noqa: E731
    crop = dict(zip(("x", "y", "w", "h"), plan["crop"])) if plan["crop"] else None
    frames = plan.get("frames") or [0]
    return {"video": str(video), "output": str(out), "zoom": plan["zoom"], "crop": crop,
            "face": r3(plan["face"]), "face_at_punch_in": r3(plan["face_at_punch_in"]),
            "pieces": [{"start": round(a, 4), "end": round(b, 4), "zoom": z, "first_frame": f}
                       for (a, b, z), f in zip(plan["pieces"], frames)]}


def saved_joins(name: str, work: Path, info: MediaInfo) -> tuple[list[float], float, float]:
    """(joins, drift, length) from the saved cut lists: drift is how much longer the video is than they say."""
    try:
        cut = timemap.load(name, work)
    except FileNotFoundError:
        raise Abort(f"No saved cut lists for '{name}' in {work} (reports/{name}.json or {name}.mistakes-edl.json). "
                    "Without cuts there are no jump cuts to punch in on. Check --name, or give the times with --joins.")
    length = info.video_duration or info.duration
    report, edl = work / "reports" / f"{name}.json", work / f"{name}.mistakes-edl.json"
    joins = len(cut.keeps) - 1
    if report.is_file() and edl.is_file():
        from retime import stale_mistakes     # the mistake list made on another dead-air cut than today's
        problem = stale_mistakes(work, name)
        if problem:
            raise Abort(problem)
        r = json.loads(report.read_text(encoding="utf-8"))
        dead = timemap.TimeMap.from_cuts(r.get("cuts") or [], float(r["duration_before"]))
        if abs(length - dead.duration) + 1e-3 < abs(length - cut.duration):
            raise Abort(f"This video is as long as the dead-air cut ({length:.2f} s), but {edl.name} cuts "
                        f"{dead.duration - cut.duration:.2f} s more, so its joins aren't in this video. Run punch-ins "
                        f"on the video made from the mistake cut (work/{name}.v.mp4, or work/{name}.clean.mp4 if "
                        "the voice level was skipped). If that list is left from an older run "
                        "(step 4 cut nothing this time), move it out of work/ and run this again.")
        joins += len(dead.keeps) - 1          # the mistake list's times carry the dead-air cut's drift too
    # On uneven frame times a cut video runs on past its lists (measured 0.1 to 0.4 frame a join); never short.
    if not -0.05 <= length - cut.duration <= 0.05 + 0.5 * joins / (info.fps or 30):
        raise Abort(f"The saved cut lists for '{name}' describe a {cut.duration:.2f} s cut, but this video is "
                    f"{length:.2f} s long. Use the latest cut video, redo the cuts if the lists are left "
                    "from an older run, or give the join times with --joins.")
    return cut.joins(), length - cut.duration, cut.duration


def punch(info: MediaInfo, size: tuple[int, int], joins, zoom: float, face, drift: float | None = None,
          length: float | None = None) -> dict:
    """The plan for one video, with every switch on the frame where its cut really is
    (drift and length come from the saved cut lists; None for times typed by hand)."""
    joins = sorted({j for j in joins if 0 < j < info.duration})
    plan = frame_plan(*size, info.duration, joins, zoom, face)
    if len(plan["pieces"]) == 1:
        return plan
    times, changes, origin = frame_changes(info)
    snapped = snap_joins(joins, times, changes, drift, length)
    plan = frame_plan(*size, info.duration, [times[k] for k, _ in snapped], zoom, face)
    seen = {times[k] for k, ok in snapped if ok}
    plan.update(times=times, origin=origin, frames=[bisect_left(times, a - 1e-6) for a, _, _ in plan["pieces"]])
    switched = [a for a, _, _ in plan["pieces"][1:]]
    if switched and any(a not in seen for a in switched):
        n = sum(a in seen for a in switched)
        plan["notes"].append((f"{n} of {len(switched)} switches sit on a jump seen in the picture; the others go" if n
                              else "No switch sits on a jump seen in the picture; they go")
                             + " by the join times (nothing jumps visibly there).")
    return plan


# ----------------------------------------------------------------------------- self-test

def self_test() -> int:
    import numpy as np

    near = lambda a, b, tol=1e-9: abs(a - b) <= tol  # noqa: E731
    # Piece math: full first, switch only with 2 s on both sides, alternate, ignore repeats and strays.
    p = plan_pieces([1.0, 2.5, 3.0, 5.0, 7.2], 8.0, 1.12)
    assert p == [(0.0, 2.5, 1.0), (2.5, 5.0, 1.12), (5.0, 8.0, 1.0)], p
    assert plan_pieces([5.0, 2.5, 2.5, -1.0, 9.0, 3.0], 8.0, 1.12) == p
    assert plan_pieces([], 8.0, 1.12) == [(0.0, 8.0, 1.0)]
    assert [z for _, _, z in plan_pieces([2, 4, 6, 8], 10.5, 1.12)] == [1.0, 1.12, 1.0, 1.12, 1.0]

    # The crop: inside the frame, even, the asked zoom, centred on the face and holding all of it.
    w, h = 1080, 1920
    face = (0.35, 0.40, 0.62, 0.56)
    x, y, cw, ch = crop_box(w, h, 1.12, face)
    assert (cw, ch) == (966, 1716) and x % 2 == 0 and y % 2 == 0, (x, y, cw, ch)
    assert 0 <= x <= w - cw and 0 <= y <= h - ch and near(w / cw, 1.12, 0.005)
    assert near(x + cw / 2, 0.485 * w, 2) and near(y + ch / 2, 0.48 * h, 2)
    for f in (face, (0.0, 0.0, 0.3, 0.17), (0.75, 0.80, 1.0, 1.0)):     # middle, and both corners
        x, y, cw, ch = crop_box(w, h, 1.12, f)
        px0, py0, px1, py1 = padded(f)
        assert 0 <= x <= w - cw and 0 <= y <= h - ch
        assert x <= px0 * w + 1 and px1 * w <= x + cw + 1 and y <= py0 * h + 1 and py1 * h <= y + ch + 1, f

    # Zoom fallback: a face too big for 112% lowers the zoom for the whole video; under 105% there is none.
    big = (0.15, 0.30, 0.85, 0.60)                           # 70% wide, 91% with the margin
    plan = frame_plan(w, h, 8.0, [2.5, 5.0], 1.12, big)
    assert plan["zoom"] == 1.09 and "too big" in plan["notes"][0], plan
    assert [z for _, _, z in plan["pieces"]] == [1.0, 1.09, 1.0]
    x, y, cw, ch = plan["crop"]
    assert x <= padded(big)[0] * w + 1 and padded(big)[2] * w <= x + cw + 1
    for huge in ((0.125, 0.30, 0.875, 0.60), (0.0, 0.1, 1.0, 0.9)):       # 102% would be a bump; no room at all
        plan = frame_plan(w, h, 8.0, [2.5, 5.0], 1.12, huge)
        assert plan["zoom"] == 1.0 and len(plan["pieces"]) == 1 and plan["crop"] is None, plan
        assert "no punch-ins" in plan["notes"][0], plan["notes"]
    assert frame_plan(w, h, 8.0, [2.5, 5.0], 1.0, face)["pieces"] == [(0.0, 8.0, 1.0)]       # --zoom 1.0 is off

    # No face: centred across, kept to the top (the upper middle), and said.
    plan = frame_plan(w, h, 8.0, [2.5, 5.0], 1.12, None)
    x, y, cw, ch = plan["crop"]
    assert near(x, (w - cw) / 2, 1) and y == 0 and plan["face_at_punch_in"] is None
    assert any("No face found" in n for n in plan["notes"]), plan["notes"]

    # Finding the real cut: 30 fps with a dropped frame; the lists say 2.5, 5.0, 7.5, 9.0 and the video
    # is 0.1 s longer. The cuts at 2.5 and 7.5 show, 2 frames late. The 5.0 one barely shows: it goes
    # where the drift measured on both sides puts it. Nothing shows at 9.0: it goes by the drift between
    # the 7.5 cut and the end (2 frames + 0.015 s: frame 272).
    times = [n / 30 for n in range(330) if n != 40]
    changes = [1.0 + 0.1 * (n % 3) for n in range(len(times))]
    at = {t: i for i, t in enumerate(times)}
    for t, c in ((77 / 30, 6.0), (152 / 30, 1.25), (227 / 30, 5.0)):
        changes[at[t]] = c
    got = snap_joins([2.5, 5.0, 7.5, 9.0], times, changes, drift=0.1, length=10.9)
    assert [(round(times[k] * 30), ok) for k, ok in got] == [(77, True), (152, False), (227, True), (272, False)], got
    typed = snap_joins([2.5, 5.0], times, changes)          # typed: the cut nearby; else the typed time
    assert [(round(times[k] * 30), ok) for k, ok in typed] == [(77, True), (150, False)], typed
    flat = [0.0] * len(times)                               # a still picture: the frame at the join time
    assert [round(times[k] * 30) for k, _ in snap_joins([2.4, 6.0], times, flat, 0.0, 10.9)] == [72, 180]
    still = punch(MediaInfo(Path("x"), 11.0, 0.0, True, False), (w, h), [], 1.12, face)
    assert still["pieces"] == [(0.0, 11.0, 1.0)] and "Nothing was cut" in still["notes"][0], still

    # A real render: a still picture whose framing jumps 2 frames after each listed join (as on a
    # phone video), a drawn face box, and a tone.
    ffmpeg = find_tool("ffmpeg")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src, out, sheet = d / "clip.mp4", d / "clip.p.mp4", d / "clip.punch-check.png"
        fx, fy, fw, fh, W, H = 90, 76, 60, 76, 240, 428
        jump = "24*(gte(n,77)-gte(n,152))"
        made = run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W * 2}x{H}:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=440:d=8", "-vf",
                    f"trim=end_frame=1,loop=loop=239:size=1,setpts=N/30/TB,crop={W}:{H}:'{jump}':0,"
                    f"drawbox={fx}:{fy}:{fw}:{fh}:white:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)])
        assert made.returncode == 0, made.stderr
        info = probe(src)
        assert display_size(info) == (W, H)
        assert analyze(src, info).face is None                  # a test picture has no face: the fallback path
        turned = d / "turned.mp4"                               # stored sideways with a rotation flag
        assert run([ffmpeg, "-v", "error", "-display_rotation", "90", "-i", str(src), "-c", "copy",
                    str(turned)]).returncode == 0
        assert display_size(probe(turned)) == (H, W)
        ts = d / "clip.ts"                                       # MPEG-TS prints its frame count twice
        assert run([ffmpeg, "-v", "error", "-i", str(src), "-c", "copy", str(ts)]).returncode == 0
        assert frame_count(ts, 0) == 240

        def lists(dead_air_before, mistake=None, made_on=None):  # saved cut lists, as the cutters write them
            (d / "reports" / "talk.json").write_text(json.dumps({"duration_before": dead_air_before, "cuts": [[2.5, 3.5]]}))
            edl, end = d / "talk.mistakes-edl.json", dead_air_before - 1
            edl.unlink(missing_ok=True)
            if mistake:
                edl.write_text(json.dumps({"source_duration": made_on or end, "keep_ranges": [
                    {"start": 0, "end": mistake[0]}, {"start": mistake[1], "end": end}]}))

        def stops(name="talk"):
            try:
                saved_joins(name, d, info)
            except Abort as e:
                return str(e)
            raise AssertionError(f"saved_joins({name!r}) should stop")

        (d / "reports").mkdir()                                  # saved cut lists: used when they match the video
        lists(9)
        assert saved_joins("talk", d, info) == ([2.5], 0.0, 8.0)
        lists(9.15, (4.8, 4.95))                                 # the mistake cut of an 8.15 s dead-air cut
        got = saved_joins("talk", d, info)
        assert [round(v, 6) for v in got[0]] == [2.5, 4.8] and near(got[1], 0.0, 1e-6) and near(got[2], 8.0, 1e-6), got
        lists(9, (4.8, 4.95))                                    # a 0.15 s mistake list, but this is the dead-air cut
        assert "dead-air cut" in stops(), stops()
        lists(9.15, (4.8, 4.95), made_on=9.0)                    # the mistake list was made on another dead-air cut
        assert "Run steps 3 and 4 again" in stops(), stops()
        for before in (9.4, 8.8):                                # left from an older cut: longer, shorter
            lists(before)
            stops()
        stops("other")                                           # missing
        face = (fx / W, fy / H, (fx + fw) / W, (fy + fh) / H)
        plan = punch(info, (W, H), [1.0, 2.5, 3.0, 5.0, 7.2], 1.12, face, drift=0.1, length=7.9)
        assert plan["frames"] == [0, 77, 152], (plan["frames"], plan["pieces"])
        line = apply(info, plan, out, sheet, (W, H))
        assert line.startswith("OK ") and "240 frames" in line and sheet.is_file(), line

        def frames(path: Path):
            raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True).stdout
            return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)

        a, b = frames(src), frames(out)
        assert len(a) == len(b) == 240
        moved = [n for n in range(240) if np.abs(b[n].astype(np.int16) - a[n]).mean() > 6]    # differ from the input
        assert moved == list(range(77, 152)), (moved[:3], moved[-3:])     # exactly the cut frames 77 to 151

        def drawn_face(img):                                                 # white: the test picture has none
            ys, xs = (img.min(axis=2) > 220).nonzero()
            return xs.min(), ys.min(), xs.max(), ys.max(), len(xs)

        assert drawn_face(a[77])[:4] == (fx, fy, fx + fw - 1, fy + fh - 1)
        for n in (77, 110, 151):                                             # the drawn face stays whole
            x0, y0, x1, y1, area = drawn_face(b[n])
            assert 0 < x0 and x1 < W - 1 and 0 < y0 and y1 < H - 1, n
            assert near(area / (fw * fh), plan["zoom"] ** 2, 0.1), area
        hashes = [run([ffmpeg, "-v", "error", "-i", str(f), "-map", "0:a", "-c", "copy", "-f", "md5", "-"]).stdout
                  for f in (src, out)]
        assert hashes[0] and hashes[0] == hashes[1], hashes                  # the sound is the input's, untouched

        off = d / "clip.off.mp4"                                             # --zoom 1.0: a copy, no encode
        apply(info, punch(info, (W, H), [2.5, 5.0], 1.0, face), off, sheet, (W, H))
        vhash = [run([ffmpeg, "-v", "error", "-i", str(f), "-map", "0:v", "-c", "copy", "-f", "md5", "-"]).stdout
                 for f in (src, off)]
        assert vhash[0] and vhash[0] == vhash[1], vhash
        assert not sheet.exists()                                            # no switches: the old sheet is gone

        left = d / "clip.p.partial.mp4"                  # a failed run's leftover as the source: refused, kept
        left.write_bytes(b"leftover")
        argv, sys.argv = sys.argv, ["punch_in.py", str(left), "--joins", "3", "--out", str(out), "--overwrite"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert main() == 2 and left.read_bytes() == b"leftover"
        finally:
            sys.argv = argv
    print("punch-in self-test: OK")
    return 0


# ----------------------------------------------------------------------------- main

def parse_times(text: str) -> list[float]:
    try:
        return [float(v) for v in text.split(",") if v.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError('join times are seconds separated by commas, e.g. "1.2,3.4"')


def parse_box(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError('the face box is four fractions "x0,y0,x1,y1", e.g. "0.35,0.14,0.62,0.30"')
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise argparse.ArgumentTypeError("the face box runs from 0 to 1, left and top first")
    return x0, y0, x1, y1


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Punch-ins on jump cuts: switch between full and tighter framing at the joins.")
    p.add_argument("video", type=Path, nargs="?", help="the cut video (V in the automatic edit)")
    p.add_argument("--name", help="the video's name in work/, for its saved cut lists "
                                  "(default: the file name up to the first dot)")
    p.add_argument("--joins", type=parse_times, help='join times in seconds of this video, e.g. "1.2,3.4" '
                                                     "(default: from the saved cut lists)")
    p.add_argument("--zoom", type=float, default=ZOOM,
                   help=f"the punch-in: 1.12 is 112%% (default), at most {MAX_ZOOM}; "
                        "1.0 turns it off and copies the video unchanged")
    p.add_argument("--face", type=parse_box, help='the face box as fractions "x0,y0,x1,y1" (default: measured)')
    p.add_argument("--out", type=Path, help="output video (default: work/<name>.p.mp4)")
    p.add_argument("--overwrite", action="store_true", help="replace the output and work/<name>.punch.json")
    p.add_argument("--self-test", action="store_true", help="check the maths and a short synthetic render, then exit")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.video:
        p.error("give the cut video (or --self-test)")
    if not 1.0 <= args.zoom <= MAX_ZOOM:
        p.error(f"the zoom is 1.0 (off) up to {MAX_ZOOM}, e.g. 1.12")

    root = project_root()
    work = root / "work"
    video = args.video
    # talk.v.mp4 -> talk; my.talk.v.mp4 -> my.talk, when that is the name the saved lists use.
    parts = video.name.split(".")
    name = args.name or next((n for n in (".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1))
                              if (work / "reports" / f"{n}.json").is_file()
                              or (work / f"{n}.mistakes-edl.json").is_file()), parts[0])
    out = args.out or work / f"{name}.p.mp4"
    saved, sheet = work / f"{name}.punch.json", work / f"{name}.punch-check.png"
    if not video.is_file():
        print(f"Not found: {video}")
        return 2
    if out.resolve() == video.resolve():
        print("The output would overwrite the source. Use --out with a different name.")
        return 2
    if out.with_name(f"{out.stem}.partial{out.suffix}").resolve() == video.resolve():   # apply() renders there
        print(f"{video.name} is the temporary file a punch-in run writes before {out.name} (a failed run keeps it "
              "for a look). Use the cut video, or --out with a different name.")
        return 2
    if (root / "input").resolve() in out.resolve().parents:
        print("Refusing to write into input/: that folder is only for the original videos.")
        return 2
    for f in (out, saved):      # the sidecars describe the punched video the later steps use
        if f.exists() and not args.overwrite:
            print(f"{f} already exists (use --overwrite to replace it, with the video and its check sheet).")
            return 1
    try:
        info = probe(video)
        if not info.has_video:
            raise Abort(f"{video.name} has no picture to punch in on.")
        size = display_size(info)
        drift = length = None                        # times typed by hand have no drift to measure
        if args.zoom <= 1.0:
            joins = []                               # off: no lists needed, the video is copied
        elif args.joins is not None:
            joins = args.joins
        else:
            joins, drift, length = saved_joins(name, work, info)
        face = args.face
        if face is None and args.zoom > 1.0 and len(plan_pieces(joins, info.duration, args.zoom)) > 1:
            face = analyze(video, info).face         # only measured when there is something to punch in on
        plan = punch(info, size, joins, args.zoom, face, drift, length)
        switches = [a for a, _, _ in plan["pieces"][1:]]
        kept = len(joins) - len(switches)
        print(f"{video.name}: {len(joins)} join{'' if len(joins) == 1 else 's'}, "
              + (f"framing switches at {', '.join(fmt_time(a) for a in switches)}" if switches else "no framing switches")
              + (f" (skipped {kept}: each framing holds at least {HOLD:g} s)" if switches and kept else ""))
        for note in plan["notes"]:
            print(f"  {note}")
        if not switches:
            print("  The video is copied without re-encoding.")
        print("  " + apply(info, plan, out, sheet, size).replace("\n", "\n  "))
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(report(video, out, plan), indent=1), encoding="utf-8")
        print(f"  saved {saved}")
    except (Abort, SetupError, RuntimeError) as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
