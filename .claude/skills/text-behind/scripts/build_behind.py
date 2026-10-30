#!/usr/bin/env python3
"""Text behind the speaker: one big word placed behind the person, the person cut out on top.

For each moment:
  1. cut the window (the word's screen time plus small handles) out of the video
  2. matte the person with `hyperframes remove-background` (local u2net model, ~2 fps at 1080p on CPU)
  3. place and size the word so the head and body cover 30-55% of it (measured on the matte),
     in the theme's font and colour, and render it as a transparent HyperFrames clip
  4. one FFmpeg encode: the video, then the word, then the person on top. The person layer is the
     original pixels with the matte as alpha, so nothing shifts in colour; the audio is copied.

Examples (from the project folder, with the .venv python)
  python build_behind.py work/talk.mp4 --at 28.28 --end 28.9 --text "90 DAYS" --theme apple --out work/talk.b.mp4
  python build_behind.py work/talk.mp4 --plan work/talk.behind.json --theme midnight
  python build_behind.py --self-test
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
sys.path.insert(0, str(SKILLS / "video-editor" / "scripts"))
sys.path.insert(0, str(SKILLS / "motion-templates" / "scripts"))
import hfbuild  # noqa: E402
from layout import find_face  # noqa: E402
from tpl import load_theme  # noqa: E402
from vtools import SETUP_HINT, SetupError, find_tool, fmt_time, probe, project_root  # noqa: E402

LEAD = 0.15                 # the word starts rising this long before it is said
IN, OUT = 0.30, 0.25        # entrance and exit
HANDLE = 0.10               # extra matte before and after the word's screen time
COVER = (0.30, 0.55)        # share of the word hidden behind the person (HyperFrames captions.md)
COVER_GOAL = 0.42
LETTER_MAX = 0.5          # no letter more than half hidden, or the word stops reading
MATTE = (0.3, 0.8)        # matte levels: trims the soft fringe that pulls wall pixels over the word as a glow
SIZES = (1.0, 0.86, 0.74)   # tried from big to small
MAX_WINDOW = 6.0            # background removal runs at ~2 fps: keep moments short
MODEL = Path.home() / ".cache" / "hyperframes" / "background-removal" / "models" / "u2net_human_seg.onnx"
FONT_DIR = SKILLS / "video-editor" / "assets" / "fonts"
FONT_FILES = {"Montserrat XB": "Montserrat-ExtraBold.ttf", "Abril Fatface": "AbrilFatface-Regular.ttf",
              "Architects Daughter": "ArchitectsDaughter-Regular.ttf"}
INTER = {400: "Inter-Regular.ttf", 600: "Inter-SemiBold.ttf", 700: "Inter-Bold.ttf"}


class Abort(Exception):
    """A problem the user can fix; printed without a traceback."""


# ---------- timing ----------

def window(word: float, word_end: float | None, dur: float | None, length: float, fps: float) -> dict:
    """Frame-aligned screen time of the word and the (slightly longer) matte window."""
    if word < 0 or word >= length - 0.3:
        raise Abort(f"the word at {word:.2f}s is outside the video (0-{length:.2f}s)")
    spoken = max(0.2, (word_end if word_end is not None else word + 0.5) - word)
    dur = dur or IN + min(2.6, max(1.0, spoken + 0.9)) + OUT
    k0 = round(max(0.0, word - LEAD) * fps)                # first frame of the word clip
    last = math.floor(length * fps + 1e-6) - 1             # last frame of the video
    k1 = min(last, k0 + round(dur * fps) - 1)              # last frame of the word clip
    if (k1 - k0 + 1) / fps < 0.8:
        raise Abort(f"only {(k1 - k0 + 1) / fps:.2f}s left after {word:.2f}s; the word needs at least 0.8s")
    h = round(HANDLE * fps)
    ka, kb = max(0, k0 - h), min(last, k1 + h)
    return {"k0": k0, "clip_start": k0 / fps, "clip_dur": round((k1 - k0 + 1) / fps, 3),
            "ka": ka, "frames": kb - ka + 1, "cut_start": ka / fps,
            "seek": max(0.0, (ka - 0.5) / fps)}            # half a frame early, so frame ka is the first kept


# ---------- background removal ----------

def node_env() -> dict:
    ffmpeg, node = find_tool("ffmpeg"), find_tool("node")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(ffmpeg).parent), str(Path(node).parent), env.get("PATH", "")])
    env["HYPERFRAMES_FFMPEG_PATH"], env["HYPERFRAMES_FFPROBE_PATH"] = ffmpeg, find_tool("ffprobe")
    env.setdefault("HYPERFRAMES_NO_TELEMETRY", "1")
    env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
    return env


def cut_window(video: Path, w: dict, fps: float, out: Path) -> None:
    res = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-ss", f"{w['seek']:.4f}",
                          "-i", str(video), "-frames:v", str(w["frames"]), "-an", "-c:v", "libx264", "-crf", "12",
                          "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)], capture_output=True, text=True)
    if res.returncode or not out.is_file():
        raise RuntimeError(f"could not cut the window: {res.stderr.strip()[-600:]}")


def remove_background(src: Path, out: Path) -> None:
    cli = project_root() / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if not cli.is_file():
        raise SetupError(f"HyperFrames is not installed. {SETUP_HINT}")
    if not MODEL.is_file():
        print("  first run: downloading the background-removal model (u2net_human_seg, ~168 MB, free, "
              "from github.com/danielgatis/rembg) and onnxruntime-node into ~/.cache/hyperframes, once", flush=True)
    res = subprocess.run([find_tool("node"), str(cli), "remove-background", str(src), "-o", str(out)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=node_env())
    if res.returncode or not out.is_file():
        tail = (res.stderr or res.stdout or "").strip()[-800:]
        if not MODEL.is_file() or "onnxruntime" in tail:
            raise Abort("background removal could not set itself up. Its first run downloads the "
                        f"u2net_human_seg model (~168 MB) into {MODEL.parent} and installs onnxruntime-node "
                        "into ~/.cache/hyperframes/optional. Check the internet connection and run again; after "
                        f"that it works offline.\n{tail}")
        raise RuntimeError(f"background removal failed:\n{tail}")


def read_alpha(webm: Path, mw: int, mh: int) -> np.ndarray:
    """Alpha of a transparent WebM as floats 0-1, shape (frames, mh, mw)."""
    raw = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-c:v", "libvpx-vp9", "-i", str(webm),
                          "-vf", f"alphaextract,scale={mw}:{mh}:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    n = len(raw) // (mw * mh)
    if not n:
        raise RuntimeError(f"could not read the alpha channel of {webm.name}")
    return np.frombuffer(raw[: n * mw * mh], np.uint8).reshape(n, mh, mw).astype(np.float32) / 255


def frame_rgb(video: Path, t: float, mw: int, mh: int) -> np.ndarray:
    raw = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(video),
                          "-frames:v", "1", "-vf", f"scale={mw}:{mh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw[: mw * mh * 3], np.uint8).reshape(mh, mw, 3).astype(np.float32)


# ---------- the word ----------

def theme_font(theme: dict) -> tuple[str, int, Path, float, bool]:
    v = theme["vars"]
    family = v["font-display"].strip("'\" ")
    weight = int(v.get("weight") or (800 if family == "Montserrat XB" else 400))
    file = INTER.get(weight, INTER[700]) if family == "Inter" else FONT_FILES.get(family, "Montserrat-ExtraBold.ttf")
    track = float(str(v.get("tracking", "0")).replace("em", "") or 0)
    return family, weight, FONT_DIR / file, track, v.get("case") == "uppercase"


def ink(text: str, font_path: Path, fs: int, track: float, w: int, cx: float, scale: tuple[int, int] | None = None):
    """The word drawn the way the SVG <text text-anchor=middle> draws it. Returns (letters, ink top
    relative to the baseline, ink height, advance width); letters is (letters, rows, w) floats 0-1, one
    layer per visible letter, resized to scale=(width, height factor) when given."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(str(font_path), fs)
    asc, desc = font.getmetrics()
    adv = font.getlength(text) + track * fs * (len(text) - 1)
    x0 = cx - adv / 2
    layers = []
    for i, ch in enumerate(text):
        img = Image.new("L", (w, asc + desc + fs), 0)
        ImageDraw.Draw(img).text((x0 + font.getlength(text[:i]) + track * fs * i, asc), ch, font=font,
                                 fill=255, anchor="ls")
        if img.getbbox():
            layers.append(img)
    if not layers:
        raise Abort(f"nothing to draw for {text!r}")
    top = min(im.getbbox()[1] for im in layers)
    bottom = max(im.getbbox()[3] for im in layers)
    out = []
    for im in layers:
        im = im.crop((0, top, w, bottom))
        if scale:
            im = im.resize((scale[0], max(1, round(im.height * scale[1]))), 4)   # 4 = BOX: keeps the ink share
        out.append(np.asarray(im, np.float32) / 255)
    return np.stack(out), top - asc, bottom - top, adv


def place(sprites: list[np.ndarray], mattes: np.ndarray, anchor: float, top: int, lowest: int,
          shifts: tuple[float, ...] = (0, -0.05, 0.05, -0.1, 0.1)) -> dict:
    """Pick a size, height and sideways shift for the word. sprites[i]: letters (n, rows, mw) at matte scale,
    biggest size first; mattes: (frames, mh, mw), person = 1; rows and columns are matte pixels.
    Goal: 30-55% of the word hidden, no letter more than half hidden, its middle near anchor."""
    best = None
    mh, mw = mattes.shape[1:]
    for si, letters in enumerate(sprites):
        cols = np.nonzero(letters.max(axis=(0, 1)) > 0)[0]
        for f in shifts:
            dx = round(f * mw)
            if cols[0] + dx < 0.03 * mw or cols[-1] + dx > 0.97 * mw:
                continue                              # keep the word inside the frame
            lt = np.roll(letters, dx, axis=2)
            word = np.clip(lt.sum(axis=0), 0, 1)
            rows = lt.shape[1]
            for y in range(top, max(top, min(lowest, mh - rows)) + 1):
                m = mattes[:, y:y + rows, :]
                cov = (m * word).sum(axis=(1, 2)) / word.sum()
                worst = float(np.max(np.einsum("frc,lrc->l", m, lt) / len(m) / lt.sum(axis=(1, 2))))
                mean, lo, hi = float(cov.mean()), float(cov.min()), float(cov.max())
                ok = COVER[0] <= mean <= COVER[1] and hi <= 0.65 and lo >= 0.15 and worst <= LETTER_MAX
                # readable beats the 30-55% goal: next best is every letter readable and at least ~15% hidden
                tier = 0 if ok else 1 if worst <= LETTER_MAX and mean >= 0.15 and hi <= 0.65 else 2
                score = (tier + 2 * abs(mean - COVER_GOAL) + max(0.0, worst - 0.5)
                         + abs(y + rows / 2 - anchor) / mh + 0.12 * si + 0.2 * abs(f))
                if best is None or score < best["score"]:
                    best = {"score": score, "size": si, "y": y, "dx": dx, "mean": mean, "min": lo, "max": hi,
                            "worst": worst, "ok": ok, "tier": tier}
    return best


def luminance(rgb) -> np.ndarray:
    """WCAG relative luminance of RGB values 0-255 (last axis = channels)."""
    c = np.asarray(rgb, np.float32) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def hex_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    c = "".join(ch * 2 for ch in c) if len(c) == 3 else c[:6]
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def pick_color(theme: dict, override: str | None, bg: np.ndarray, weight: np.ndarray) -> str:
    """The theme's text colour, unless too much of the visible word would sit on pixels it can't be seen
    against (white on a white shirt): then the accent, then the theme background colour."""
    v = theme["vars"]
    if override:
        return v.get(override) if str(v.get(override, "")).startswith("#") else hfbuild.color(override)
    lb, wsum = luminance(bg), max(1e-6, float(weight.sum()))

    def poor(c):                                 # share of the visible ink with contrast under 2:1
        lc = float(luminance(hex_rgb(c)))
        ratio = (np.maximum(lc, lb) + 0.05) / (np.minimum(lc, lb) + 0.05)
        return float((weight * (ratio < 2.0)).sum()) / wsum
    options = [v[k] for k in ("text", "accent", "bg") if str(v.get(k, "")).startswith("#")]
    return next((c for c in options if poor(c) < 0.15), min(options, key=poor))


def word_page(text, w, h, dur, family, weight, fs, track, color, cx, baseline, ink_h) -> str:
    rise = ink_h * 0.45
    oy = baseline - ink_h / 2
    js = (f'tl.fromTo("#word",{{y:{rise:.0f},opacity:0,scale:1.06}},{{y:0,opacity:1,scale:1,duration:{IN},ease:"expo.out"}},0);'
          f'tl.to("#word",{{scale:1.03,duration:{dur - IN - OUT:.3f},ease:"none"}},{IN});'
          f'tl.to("#word",{{opacity:0,y:{-rise * 0.4:.0f},duration:{OUT},ease:"power2.in"}},{dur - OUT:.3f});')
    return f"""<!doctype html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width={w}, height={h}">
{hfbuild.scripts_html()}
<style>{hfbuild.FONT_CSS}
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent}}
#root{{position:relative;width:{w}px;height:{h}px}}
#stage{{position:absolute;inset:0}}
#word{{position:absolute;inset:0;transform-origin:{cx:.0f}px {oy:.0f}px}}
#word svg{{position:absolute;left:0;top:0;overflow:visible;filter:drop-shadow(0 {fs * 0.02:.1f}px {fs * 0.05:.1f}px rgba(0,0,0,.28))}}
#word text{{font-family:'{family}';font-weight:{weight};font-size:{fs}px;letter-spacing:{track}em;fill:{color}}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{w}" data-height="{h}">
  <div id="stage" class="clip" data-start="0" data-duration="{dur}" data-track-index="0">
    <div id="word"><svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><text x="{cx:.1f}" y="{baseline:.1f}" text-anchor="middle">{html.escape(text)}</text></svg></div>
  </div>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{js}
tl.to({{}}, {{ duration: {dur} }}, 0);
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
"""


# ---------- one moment ----------

def build_moment(i: int, m: dict, video: Path, info, theme: dict, color: str | None, w: int, h: int,
                 fps: float) -> dict:
    root = project_root()
    text = str(m["text"]).strip()
    win = window(float(m["start"]), m.get("end") and float(m["end"]), m.get("duration") and float(m["duration"]),
                 info.duration, fps)
    if win["frames"] / fps > MAX_WINDOW:
        print(f"  note: a {win['frames'] / fps:.1f}s window; background removal takes about "
              f"{win['frames'] / 2:.0f}s on CPU")
    d = root / "work" / "behind" / f"{hfbuild.slug(video.stem)}-{int(video.stat().st_mtime)}-{win['ka']}-{win['frames']}"
    d.mkdir(parents=True, exist_ok=True)
    cutout, win_mp4 = d / "person.webm", d / "window.mp4"
    t0 = time.time()
    if not win_mp4.is_file():
        cut_window(video, win, fps, win_mp4)
    face = find_face(probe(win_mp4))            # checked before the slow step: the matte model "finds" people anywhere
    if not face:
        try:
            import cv2  # noqa: F401
        except ImportError:
            print(f"  [{i}] note: OpenCV is missing, so there is no face check; placing from the matte")
        else:
            raise Abort(f"no face found between {fmt_time(win['cut_start'])} and "
                        f"{fmt_time(win['cut_start'] + win['frames'] / fps)}; text-behind needs the speaker's head "
                        "and shoulders in frame, facing the camera")
    if not cutout.is_file():                    # cached per window: re-runs that only change the word are fast
        print(f"  [{i}] cutting out the person, {win['frames']} frames...", flush=True)
        remove_background(win_mp4, cutout)
        print(f"  [{i}] cutout done in {time.time() - t0:.0f}s", flush=True)
    else:
        print(f"  [{i}] reusing the cutout in {d.name}")

    mw, mh = w // 4, h // 4
    mattes = np.clip((read_alpha(cutout, mw, mh) - MATTE[0]) / (MATTE[1] - MATTE[0]), 0, 1)
    area = (mattes > 0.5).mean(axis=(1, 2))
    if area.mean() < 0.02 or area.min() < 0.002:
        raise Abort(f"no person found (or they leave the frame) between {fmt_time(win['cut_start'])} and "
                    f"{fmt_time(win['cut_start'] + win['frames'] / fps)}: the matte is empty; pick a moment "
                    "with the speaker in frame")
    if area.std() > 0.15 * area.mean():
        print(f"  [{i}] warning: the person's outline changes a lot in this window (fast motion, hands or a held "
              "object); the cutout may flicker")
    off = win["k0"] - win["ka"]
    hold = mattes[off + round(IN * fps): off + round((win["clip_dur"] - OUT) * fps)]
    hold = hold[np.linspace(0, len(hold) - 1, min(12, len(hold))).astype(int)]

    family, weight, font_path, track, upper = theme_font(theme)
    text = text.upper() if upper else text
    if face:
        cx = (face[0] + face[2]) / 2 * w
        anchor = face[1] * mh                   # the word's middle at the top of the face box: behind the head
    else:                                       # top of the silhouette, a little down
        rows = np.nonzero((hold.mean(axis=0) > 0.5).any(axis=1))[0]
        cols = np.nonzero((hold.mean(axis=0)[rows[0]: rows[0] + mh // 10] > 0.5).any(axis=0))[0]
        cx, anchor = (cols.mean() * 4 if len(cols) else w / 2), rows[0] + 0.06 * mh
    adv200 = ink(text, font_path, 200, track, w, w / 2)[3]
    fs0 = 200 * (0.86 if h > w else 0.62) * w / adv200
    fs0 = min(fs0, fs0 * (0.16 if h > w else 0.26) * h / ink(text, font_path, int(fs0), track, w, w / 2)[2])
    sprites, metas = [], []
    for fs in (max(24, int(fs0 * s)) for s in SIZES):
        adv = ink(text, font_path, fs, track, w, w / 2)[3]
        c = min(max(cx, adv / 2 + 0.04 * w), w - adv / 2 - 0.04 * w) if adv < 0.92 * w else w / 2
        letters, ink_top, ink_h, _ = ink(text, font_path, fs, track, w, c, (mw, mh / h))
        sprites.append(letters)
        metas.append((fs, c, ink_top, ink_h))
    lowest = int(anchor) if face else int(anchor + 0.1 * mh)
    best = place(sprites, hold, anchor, int(0.035 * mh), lowest)
    if best["tier"] == 2:
        print(f"  [{i}] warning: no size or position keeps every letter at least half visible; "
              "try a shorter word or a moment with more background around the head")
    fs, cx, ink_top, ink_h = metas[best["size"]]
    cx += best["dx"] * w / mw
    top_px = best["y"] * h / mh
    baseline = top_px - ink_top

    sp = np.roll(np.clip(sprites[best["size"]].sum(axis=0), 0, 1), best["dx"], axis=1)
    seen = sp * (1 - hold.mean(axis=0)[best["y"]: best["y"] + sp.shape[0]])
    frame = frame_rgb(video, win["clip_start"] + win["clip_dur"] / 2, mw, mh)[best["y"]: best["y"] + sp.shape[0]]
    col = pick_color(theme, m.get("color") or color, frame, seen)

    page = word_page(text, w, h, win["clip_dur"], family, weight, fs, track, col, cx, baseline, ink_h)
    t1 = time.time()
    comp = hfbuild.new_composition(f"tb-{hfbuild.slug(video.stem)}-{i:02d}-{hfbuild.slug(text)}", page)
    word = hfbuild.render(comp, d / f"word-{hfbuild.slug(text)}.webm", fps=hfbuild.video_fps(info), transparent=True)

    # Measure the rendered word against the matte (font metrics guess wrong both ways)
    wa = read_alpha(word, mw, mh)
    ks = range(round(IN * fps), min(len(wa), round((win["clip_dur"] - OUT) * fps)))
    cov = [float((wa[k] * mattes[min(len(mattes) - 1, off + k)]).sum() / max(1e-6, wa[k].sum())) for k in ks]
    mean = sum(cov) / max(1, len(cov))
    flag = ("" if COVER[0] - 0.05 <= mean <= COVER[1] + 0.05 else "  <- mostly hidden, check the frames"
            if mean > COVER[1] else "  (shallow: every letter kept readable)")
    print(f"  [{i}] {fmt_time(win['clip_start']):>7} \"{text}\" {fs}px {col} at y {top_px / h:.2f}; "
          f"covered {min(cov):.0%}-{max(cov):.0%} (avg {mean:.0%}); word rendered in {time.time() - t1:.0f}s{flag}",
          flush=True)
    return {"word": word, "cutout": cutout, "text": text, **win}


# ---------- one encode ----------

def composite(video: Path, info, items: list[dict], out: Path, crf: int = 18, speed: str = "fast") -> Path:
    """Video, then each word (only in its window), then the person on top: the original pixels with the
    matte as alpha, so the person matches the base exactly. Audio copied."""
    from cut_dead_air import run_ffmpeg, video_codec_args

    w, h = info.width, info.height
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(video)]
    parts, prev, n = [], f"[0:v:{info.video_index}]", 1
    for i, it in enumerate(items, 1):
        cmd += ["-c:v", "libvpx-vp9", "-i", str(it["word"]),
                "-ss", f"{it['seek']:.4f}", "-t", f"{(it['frames'] + 0.5) / info.fps:.4f}", "-i", str(video),
                "-c:v", "libvpx-vp9", "-i", str(it["cutout"])]
        a, b, c = n, n + 1, n + 2
        n += 3
        parts += [f"[{a}:v]scale={w}:{h},setpts=PTS+{it['clip_start']:.4f}/TB[t{i}]",
                  f"[{b}:v:{info.video_index}]setpts=PTS-STARTPTS[s{i}]",
                  f"[{c}:v]alphaextract,lut=c0='clip((val-{MATTE[0] * 255:.1f})*{1 / (MATTE[1] - MATTE[0]):.4f},0,255)',"
                  f"scale={w}:{h},setpts=PTS-STARTPTS[m{i}]",
                  f"[s{i}][m{i}]alphamerge,setpts=PTS+{it['cut_start']:.4f}/TB[f{i}]",
                  f"{prev}[t{i}]overlay=0:0:eof_action=pass[u{i}]",
                  f"[u{i}][f{i}]overlay=0:0:eof_action=pass[v{i}]"]
        prev = f"[v{i}]"
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2" if (w % 2 or h % 2) else "null"
    parts.append(f"{prev}{even}[vout]")
    root = project_root()
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
    if abs(probe(out).duration - info.duration) > 0.5:
        raise RuntimeError(f"result is {fmt_time(probe(out).duration)} long, source is {fmt_time(info.duration)}")
    return out


# ---------- self-test ----------

def self_test() -> int:
    w = window(28.28, 28.9, None, 33.1, 30)
    assert w["k0"] == 844 and abs(w["clip_start"] - 844 / 30) < 1e-9, w
    assert w["ka"] == 841 and w["frames"] == round(w["clip_dur"] * 30) + 6, w
    assert abs(w["seek"] - 840.5 / 30) < 1e-9
    w = window(0.05, None, 2.0, 33.1, 30)                      # near the start: no negative times
    assert w["k0"] == 0 and w["ka"] == 0 and w["seek"] == 0.0, w
    w = window(31.9, None, 3.0, 33.1, 30)                      # runs past the end: shortened
    assert w["ka"] + w["frames"] - 1 <= 992 and w["clip_dur"] < 3.0, w
    for bad in (40.0, 32.95, -1.0):
        try:
            window(bad, None, 2.0, 33.1, 30)
        except Abort:
            continue
        raise AssertionError(f"window({bad}) should fail")
    # A head (disk) over shoulders; two letters with a gap. The pick must hide 30-55%, no letter over half.
    mh, mw = 120, 80
    yy, xx = np.mgrid[0:mh, 0:mw]
    person = (((yy - 40) ** 2 + (xx - 40) ** 2) < 14 ** 2) | ((yy > 52) & (abs(xx - 40) < 30))
    mattes = np.repeat(person[None].astype(np.float32), 4, axis=0)
    sprites = []
    for wd in (68, 60, 52):                                    # two letters per size, gap in the middle
        s = np.zeros((2, 10, mw), np.float32)
        x0, lw = (mw - wd) // 2, wd * 3 // 8
        s[0, :, x0:x0 + lw] = s[1, :, x0 + wd - lw:x0 + wd] = 1
        sprites.append(s)
    best = place(sprites, mattes, anchor=40, top=4, lowest=55)
    assert best["ok"] and COVER[0] <= best["mean"] <= COVER[1] and best["worst"] <= LETTER_MAX, best
    assert 25 <= best["y"] + 5 <= 60, best
    empty = place(sprites, np.zeros_like(mattes), anchor=40, top=4, lowest=55)
    assert not empty["ok"]
    left = np.repeat(((xx < 30) & (yy > 0))[None].astype(np.float32), 4, axis=0)
    hidden = place(sprites, left, anchor=40, top=4, lowest=55)   # a wall over the left letter:
    assert hidden["dx"] > 0 and hidden["worst"] <= LETTER_MAX, hidden   # slide right, keep it readable
    th = {"vars": {"text": "#ffffff", "accent": "#2997ff", "bg": "#000000"}}
    wall = np.full((4, 10, 3), 40, np.float32)
    assert pick_color(th, None, wall, np.ones((4, 10))) == "#ffffff"          # white on a dark wall
    wall[:, 7:] = 245                                                       # 30% of it on a white shirt
    assert pick_color(th, None, wall, np.ones((4, 10))) == "#2997ff"       # the blue reads on both
    assert pick_color(th, None, np.full((4, 10, 3), 200, np.float32), np.ones((4, 10))) == "#000000"
    assert pick_color(th, "red", wall, np.ones((4, 10))) == hfbuild.COLORS["red"]
    print("self-test OK")
    return 0


# ---------- main ----------

def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Put one big word behind the speaker, the speaker cut out in front.")
    p.add_argument("video", type=Path, nargs="?")
    p.add_argument("--at", type=float, help="when the word is said (seconds); the word rises 0.15s before")
    p.add_argument("--end", type=float, help="when the spoken word or phrase ends (sets how long it holds)")
    p.add_argument("--text", help='the word or short number, e.g. "90 DAYS"')
    p.add_argument("--duration", type=float, help="seconds on screen (default: from the spoken length, ~2s)")
    p.add_argument("--plan", type=Path, help='JSON: {"moments": [{"start", "end", "text", "duration"?, "color"?}]}')
    p.add_argument("--only", help="comma-separated moment numbers from the plan (1-based)")
    p.add_argument("--theme", default="apple", help="blueprint, midnight, paper or apple (font and colour)")
    p.add_argument("--color", help="text colour: a theme name (text, accent, good, bad), a colour name or #hex")
    p.add_argument("--out", type=Path, help="output video (default: output/<name>.mp4)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--self-test", action="store_true", help="check the timing and placement maths, then exit")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.video:
        p.error("give a video (or --self-test)")

    root = project_root()
    video = args.video if args.video.exists() else root / "input" / args.video
    try:
        info = probe(video)
        theme = load_theme(args.theme)
    except (SetupError, ValueError) as e:
        print(e)
        return 2
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        moments = plan.get("moments", []) if isinstance(plan, dict) else plan
        if args.only:
            picks = {int(x) for x in args.only.split(",") if x.strip()}
            moments = [m for k, m in enumerate(moments, 1) if k in picks]
    elif args.at is not None and args.text:
        moments = [{"start": args.at, "end": args.end, "text": args.text, "duration": args.duration}]
    else:
        p.error("give --at and --text, or --plan")
    if not moments:
        print("The plan has no moments.")
        return 1
    out = args.out or root / "output" / f"{video.stem}.mp4"
    if out.resolve() == video.resolve():
        print("The output would overwrite the source. Use --out with a different name.")
        return 2
    if out.exists() and not args.overwrite:
        print(f"{out} already exists (use --overwrite or --out).")
        return 1

    moments = sorted(moments, key=lambda m: float(m["start"]))
    big = max(info.width, info.height)
    s = min(1.0, 1920 / big)                      # render the word at most 1920 px, scaled up in the encode
    w, h = int(info.width * s) // 2 * 2, int(info.height * s) // 2 * 2
    fps = info.fps or 30
    started = time.time()
    items = []
    try:
        for i, m in enumerate(moments, 1):
            it = build_moment(i, m, video, info, theme, args.color, w, h, fps)
            if items and it["clip_start"] < items[-1]["clip_start"] + items[-1]["clip_dur"] + 0.5:
                raise Abort(f"\"{it['text']}\" starts while \"{items[-1]['text']}\" is still on screen; "
                            "keep these moments at least a beat apart")
            items.append(it)
        print("Compositing (video, word, person) in one encode...", flush=True)
        composite(video, info, items, out)
    except Abort as e:
        print(f"Stopped: {e}")
        return 1
    except SetupError as e:
        print(e)
        return 2
    times = [t for it in items for t in (it["clip_start"] + IN + 0.05, it["clip_start"] + it["clip_dur"] / 2,
                                         it["clip_start"] + it["clip_dur"] - OUT - 0.05)]
    sheet = hfbuild.contact_sheet(out, times, root / "work" / f"{out.stem}.behind-check.png")
    print(f"OK  {out}  ({len(items)} text-behind moment{'s' if len(items) > 1 else ''}, audio untouched, "
          f"{time.time() - started:.0f}s)")
    print(f"Check frames: {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
