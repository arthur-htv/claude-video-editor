#!/usr/bin/env python3
"""Check a video's graphics by machine before the hand-over (step 8 of /video-editor:auto).

Reads one video's plans and the clips rendered from them, and names the graphic and the video time of every problem:
  - a font that isn't bundled (the renderer would quietly draw another one)
  - a graphic over the face, or over a caption while the caption is on screen
  - an overlay or caption where the app draws its own buttons and text (--platform, 9:16 video; full-screen graphics
    aren't checked for this)
  - two graphics on screen together, or less than 0.5 s apart
  - a full-screen graphic that starts or ends on a black frame, or an overlay that shows nothing at its first check
  - a graphic cut off at the frame's edge, or a rendered clip that can't be read
It writes work/<name>.qa.json. Exit 0: all clear (read the notes: what it couldn't check); 1: problems found;
2: it couldn't check at all (a missing video, a damaged plan or run file).

Plans (each optional): work/<name>.templates.json (templates and designed cards), work/<name>[.*].emphasis.json
(kinetic text), work/<name>.behind.json (text behind the speaker), work/<name>[.*].captions.json, and the morph
windows: --morph, else the ones saved in the run file work/<name>.run.json (run_state.py).
Clips: work/templates, work/kinetic, work/behind, work/morph.

  python qa_graphics.py talk                                  checks work/talk's graphics
  python qa_graphics.py talk --platform reels --morph "2.9-5.9,8.2-10.8"
  python qa_graphics.py talk --face 0.35,0.14,0.62,0.30       this face box (fractions) instead of measuring it
  python qa_graphics.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for _skill in ("captions", "text-behind", "kinetic-text", "motion-templates", "video-editor"):
    sys.path.insert(0, str(HERE.parent.parent / _skill / "scripts"))
import build_behind as tb  # noqa: E402
import build_kinetic as kt  # noqa: E402
import hfbuild  # noqa: E402
from build_template import scene_for  # noqa: E402
from layout import analyze  # noqa: E402
from make_captions import FONT_DIR, SANS_FILE, STYLES as CAPTION_STYLES, font_ratio, windows  # noqa: E402
from tpl import THEMES  # noqa: E402
from vtools import VIDEO_EXTS, SetupError, find_tool, fmt_time, probe, project_root  # noqa: E402

# Where each app draws its own buttons and text over a 9:16 video: (x0, y0, x1, y1) as fractions of the frame.
# These are the ad guides' safe zones, the strictest case: an organic post's own text takes a little less room.
ZONES = {
    # Meta Ads Guide, Instagram Reels: "leave at least 14% of the top, 35% of the bottom, and 6% on each side of your
    # asset free from text, logos, or other important creative elements" (read 2026-11-02)
    # https://www.facebook.com/business/ads-guide/update/video/instagram-reels
    "reels": {"top": (0, 0, 1, 0.14), "bottom": (0, 0.65, 1, 1), "left side": (0, 0, 0.06, 1),
              "right side": (0.94, 0, 1, 1)},
    # Approximate: TikTok publishes its in-feed safe zone only as a template file
    # (https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads). These are that file's margins as measured by
    # https://www.upload-post.com/tools/safe-zone-checker/ : 240, 660, 120 and 120 px of 1080x1920, buttons from 840 px down
    "tiktok": {"top": (0, 0, 1, 0.125), "bottom": (0, 0.656, 1, 1), "left side": (0, 0, 0.111, 1),
               "right side": (0.889, 0, 1, 1), "buttons": (0.722, 0.4375, 1, 1)},
    # Approximate: Google's vertical video ad guidance as summarised on the same page: 288, 672, 48 and 192 px
    "shorts": {"top": (0, 0, 1, 0.15), "bottom": (0, 0.65, 1, 1), "left side": (0, 0, 0.044, 1),
               "right side": (0.822, 0, 1, 1)},
}
APP = {"reels": "Instagram Reels", "tiktok": "TikTok", "shorts": "YouTube Shorts"}

GAP = 0.5        # seconds from one graphic's end to the next one's start (talking-head-recut)
OPAQUE = 0.5     # alpha that counts as covering: drop shadows and glows stay under it
GRAZE = 0.0005   # share of the frame a graphic may touch before it counts (anti-aliasing, the detector's rough box)
FONTS = list(dict.fromkeys(re.findall(r"font-family:\s*'([^']+)'", hfbuild.FONT_CSS)))
GENERIC = set("serif sans-serif monospace cursive fantasy system-ui ui-serif ui-sans-serif ui-monospace ui-rounded "
              "math emoji fangsong inherit initial unset revert revert-layer".split())

CSS = re.compile(r"<style[^>]*>(.*?)</style>|\sstyle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.S | re.I)
SVG_FONT = re.compile(r"\sfont-family\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)
FAMILY = re.compile(r"(?<![\w-])font-family\s*:\s*([^;}]+)", re.I)
SHORTHAND = re.compile(r"(?<![\w-])font\s*:\s*([^;}]+)", re.I)
# In "font: 600 48px/1.1 'Inter', sans-serif" the font names are what follows the size.
_NAME = r"(?:'[^']*'|\"[^\"]*\"|var\([^)]*\)|[a-z][\w -]*)"
AFTER_SIZE = re.compile(rf"[\d)][a-z%]*(?:/\S+)?\s+({_NAME}(?:\s*,\s*{_NAME})*)\s*$", re.I)
VAR_DEF = re.compile(r"(?<![\w-])--([\w-]+)\s*:\s*([^;}]+)")
VAR_USE = re.compile(r"var\(\s*--([\w-]+)")
COMMA = re.compile(r",(?![^(]*\))")          # between two fonts, not inside var(...)
COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I)
SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
JS_FAMILY = re.compile(r"fontFamily\s*[:=]\s*(['\"`])(.*?)\1")
SYSTEM_FONTS = {"caption", "icon", "menu", "message-box", "small-caption", "status-bar"}   # font: caption = the OS's font
BUNDLED_FILES = {f.name.lower() for f in hfbuild.FONT_DIR.glob("*")}       # hfbuild copies them to assets/fonts


def problem(graphic: str, t: float | None, kind: str, text: str) -> dict:
    return {"graphic": graphic, "time": None if t is None else round(float(t), 3), "kind": kind, "problem": text}


def read_json(path: Path):
    """A plan or the run file. A damaged one stops the check with a plain message (exit 2)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path.name} isn't valid JSON (line {e.lineno}, column {e.colno}). Fix it by hand, or "
                           "write it again with the step that made it.") from None
    except (OSError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Can't read {path.name}: {e}") from None


def readable(fn, *args):
    """fn(*args) on a rendered clip, or None when the clip can't be read (empty, or cut short by a failed render).
    A missing ffmpeg still stops the check."""
    try:
        return fn(*args)
    except SetupError:
        raise
    except RuntimeError:
        return None


def unreadable(what: str, t: float | None, clip: Path) -> dict:
    return problem(what, t, "clip", f"its rendered clip {clip.name} can't be read (empty, or cut short by a failed "
                   "render); render that pass again")


# ---------- fonts ----------

@lru_cache(maxsize=1)
def theme_font_vars() -> frozenset:
    """The themes' font variables (font-display, font-body): the templates' own CSS draws text with them."""
    return frozenset(k for f in THEMES.glob("*.json") for k in read_json(f).get("vars", {}) if k.startswith("font"))


def font_lists(text: str) -> list[str]:
    """The font lists an HTML fragment asks for (its <style> blocks, style="", SVG font-family="" and fontFamily in
    its scripts), or plain CSS. A font variable it sets counts too: one its own lists or font: shorthands use, or a
    theme font variable."""
    text, lists = COMMENT.sub(" ", text), []
    if "<" in text:
        lists = [html.unescape("".join(m)) for m in SVG_FONT.findall(text)]
        lists += [m[1] for s in SCRIPT.findall(text) for m in JS_FAMILY.findall(s)]
        text = "\n".join(html.unescape("".join(m)) for m in CSS.findall(text))
    text = FONT_FACE.sub(" ", text)          # a font's declaration, not a use: aliases() reads those
    lists += FAMILY.findall(text)
    whole = set()                            # variables holding a whole shorthand: font: var(--hero)
    for v in (v.strip() for v in SHORTHAND.findall(text)):
        if m := AFTER_SIZE.search(v):
            lists.append(m.group(1))
        elif v.lower() in SYSTEM_FONTS:
            lists.append(v)
        else:
            whole |= set(VAR_USE.findall(v))
    used = {k for lst in lists for k in VAR_USE.findall(lst)} | theme_font_vars()
    for k, v in VAR_DEF.findall(text):
        if k in whole and (m := AFTER_SIZE.search(v.strip())):
            lists.append(m.group(1))
        elif k in used:
            lists.append(v)
    return lists


def aliases(text: str) -> set[str]:
    """Names a card gives a bundled font file with its own @font-face (src: url('assets/fonts/Inter-Bold.ttf'))."""
    out = set()
    for block in FONT_FACE.findall(COMMENT.sub(" ", text)):
        fam, files = FAMILY.search(block), re.findall(r"url\(\s*['\"]?([^'\")]+)", block)
        if fam and files and all(Path(f.strip()).name.lower() in BUNDLED_FILES for f in files):
            out.add(fam.group(1).strip().strip("'\"").strip().lower())
    return out


def swapped(lists, extra=()) -> list[str]:
    """The fonts the render can't draw as asked: in each list, the names before its first bundled font (or an extra
    name, such as a card's own alias), generic family or variable. A name after those is never reached, and a
    variable is checked where it is set."""
    ok, out = {f.lower() for f in FONTS} | GENERIC | set(extra), []
    for lst in lists:
        for n in COMMA.split(lst):
            n = n.replace("!important", "").strip().strip("'\"").strip()
            if n.lower() in ok or n.lower().startswith("var("):
                break
            out += [n] if n else []
    return list(dict.fromkeys(out))


def font_text(names: list[str]) -> str:
    quoted, one = ", ".join(f'"{n}"' for n in names), len(names) == 1
    return (f"uses the font{'' if one else 's'} {quoted}, which {'is' if one else 'are'}n't bundled, so the render "
            f"quietly draws another font. Use {', '.join(FONTS[:-1])} or {FONTS[-1]}.")


def theme_problems(themes: Path = THEMES) -> list[dict]:
    out = []
    for f in sorted(themes.glob("*.json")):
        bad = swapped(v for k, v in read_json(f).get("vars", {}).items() if k.startswith("font"))
        out += [problem(f"theme {f.stem}", None, "font", font_text(bad))] if bad else []
    return out


# ---------- the plans ----------

def newest(paths) -> Path | None:
    paths = [p for p in paths if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def plan_file(work: Path, name: str, kind: str) -> Path | None:
    """work/<name>.<kind>.json, else the newest work/<name>.<cut>.<kind>.json (plans named after a later cut)."""
    n = glob.escape(name)
    return newest([*work.glob(f"{n}.{kind}.json"), *work.glob(f"{n}.*.{kind}.json")])


def moments(path: Path) -> list[dict]:
    data = read_json(path)
    ms = data.get("moments", []) if isinstance(data, dict) else data
    if not isinstance(ms, list) or not all(isinstance(m, dict) and isinstance(m.get("start"), (int, float))
                                           and "text" in m for m in ms):
        raise RuntimeError(f'{path.name}: every moment needs a "start" (seconds) and a "text".')
    return ms


def spec_label(sp: dict) -> str:
    """The label build_template.py names a template's clip after (same rule)."""
    return str(sp.get("name") or sp.get("title") or sp.get("text") or sp.get("handle") or sp.get("label") or "")


def template_clip(work: Path, sp: dict, start: float, overlay: bool) -> Path:
    """The clip build_template.py renders for a spec (same name rule)."""
    stem = f"tpl-{sp['template']}-{hfbuild.slug(spec_label(sp))}-{int(start * 10)}"
    return work / "templates" / f"{stem}.{'webm' if overlay else 'mp4'}"


def run_windows(work: Path, name: str) -> list[dict]:
    """The graphic windows saved in the run file work/<name>.run.json, or none without one."""
    run = work / f"{name}.run.json"
    if not run.is_file():
        return []
    import run_state          # plan step 6's module, needed only when there is a run file
    try:
        return [{**w, "start": float(w["start"]), "end": float(w["end"])} for w in run_state.windows(read_json(run))]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError(f"{run.name} has damaged windows. Fix it by hand, or add them again with run_state.py.") from None


def morph_windows(saved: list[dict], morph: str) -> list[tuple[float, float, str | None, str | None]]:
    """The morph windows (--morph, else the run file's), each with its mode (cutaway or overlay) and label when the
    run file has them."""
    known = [(w["start"], w["end"], w["mode"], w.get("label")) for w in saved if w.get("kind") == "morph"]
    if not morph.strip():
        return known
    by_time = {(round(a, 2), round(b, 2)): (m, lab) for a, b, m, lab in known}
    return [(a, b, *by_time.get((round(a, 2), round(b, 2)), (None, None))) for a, b in windows(morph)]


def label_words(label) -> set[str]:
    """The words of a run-file label that can name a morph clip: "ring 87%" -> {"ring"}."""
    words = re.findall(r"[a-z]{3,}", str(label or "").lower())       # not slug(): it turns "" into "clip"
    return set(words) - {"clip", "morph"}


def collect(root: Path, name: str, info, morph: str) -> tuple[list[dict], list[dict], list[str]]:
    """Every planned graphic: its window on the video, its rendered clip and its check times (clip seconds)."""
    work = root / "work"
    s = min(1.0, 1920 / max(info.width, info.height))
    w, h = int(info.width * s) // 2 * 2, int(info.height * s) // 2 * 2       # the canvas the renderers use
    fps = info.fps or 30
    gs, problems, notes = [], [], []

    def add(label, start, end, clip, checks, full=False, behind=False):
        gs.append({"graphic": label, "start": float(start), "end": float(end), "clip": clip, "checks": checks,
                   "full": full, "behind": behind})

    tfile = work / f"{name}.templates.json"
    specs = read_json(tfile) if tfile.is_file() else []
    for sp in specs if isinstance(specs, list) else [specs]:
        if not isinstance(sp, dict):
            raise RuntimeError(f'{tfile.name}: each entry needs to be a template spec, such as {{"template": "card", ...}}.')
        lab = spec_label(sp)
        what = (f'{sp.get("template")} "{lab[:40]}"' if lab else
                f'card {Path(str(sp["file"])).stem}' if sp.get("file") else str(sp.get("template")))
        at = sp["start"] if isinstance(sp.get("start"), (int, float)) else None
        card = None
        if sp.get("template") == "card" and sp.get("file"):
            card = Path(sp["file"]) if Path(sp["file"]).is_absolute() else root / sp["file"]
            if not card.is_file():
                problems.append(problem(what, at, "plan", f"its card file {sp['file']} is missing"))
                continue
        try:
            ctx, scene = scene_for(sp, w, h, sp.get("theme") or "blueprint")
        except (ValueError, KeyError, TypeError, OSError) as e:
            problems.append(problem(what, at, "plan", f"can't be built from the plan: {e}"))
            continue
        if sp.get("template") == "card":
            text = card.read_text(encoding="utf-8") if card else str(sp.get("html") or "")
            bad = swapped(font_lists(text), aliases(text))
            problems += [problem(what, ctx.start, "font", font_text(bad))] if bad else []
        clip = template_clip(work, sp, ctx.start, scene.overlay)
        if not clip.is_file():
            problems.append(problem(what, ctx.start, "clip", f"has no rendered clip ({clip.name}); render the templates again"))
        add(what, ctx.start, ctx.end, clip if clip.is_file() else None,
            scene.checks or [ctx.dur * f for f in (0.2, 0.5, 0.85)], full=not scene.overlay)

    kfile = plan_file(work, name, "emphasis")
    ms = sorted(moments(kfile), key=lambda m: float(m["start"])) if kfile else []
    kept = 0
    for j, m in enumerate(ms):
        what, start = f'kinetic text "{m["text"]}"', max(0.0, float(m["start"]) - kt.LEAD)
        if j + 1 < len(ms) and float(ms[j + 1]["start"]) - float(m["start"]) - 0.05 < 0.9:     # build_kinetic's rule
            notes.append(f"{what} at {fmt_time(start)} isn't in the video: build_kinetic leaves out a moment that starts "
                         "under 0.9 s before the next one")
            continue
        kept += 1          # build_kinetic numbers the moments it keeps: kt-<video>-NN-<word>.webm
        stem, tail = hfbuild.slug(name), f"{kept:02d}-{hfbuild.slug(str(m['text']))}.webm"
        clip = newest([*work.glob(f"kinetic/kt-{stem}-{tail}"), *work.glob(f"kinetic/kt-{stem}-*-{tail}")])
        if clip is None:
            notes.append(f"{what} at {fmt_time(start)} has no rendered clip (kt-{stem}-{tail}), so it wasn't checked; "
                         "run build_kinetic.py again if it belongs in the video")
            continue
        ci = readable(probe, clip)
        if ci is None:
            problems.append(unreadable(what, start, clip))
        add(what, start, start + (ci.duration if ci else 0.0), clip if ci else None, [kt.IN + 0.25])   # the word's peak

    bfile = work / f"{name}.behind.json"
    bms = moments(bfile) if bfile.is_file() else []
    # build_behind names its folder <cut>-<the cut's mtime>-<ka>-<frames> after the cut it read. With that cut still
    # in work/, the first frame (ka) is worked out with its own frame rate: a variable-rate source's average drifts
    # between cuts. Without it, a ka within 2% (that drift) counts, the nearest first.
    srcs = {(hfbuild.slug(p.stem), str(int(p.stat().st_mtime))): p for p in work.glob(f"{glob.escape(name)}*.mp4")} if bms else {}
    for m in bms:
        what = f'text behind "{m["text"]}"'
        at = (float(m["start"]), m.get("end") and float(m["end"]), m.get("duration") and float(m["duration"]))
        try:
            win = tb.window(*at, info.duration, fps)
        except tb.Abort as e:
            problems.append(problem(what, float(m["start"]), "plan", str(e)))
            continue
        word, found = f"word-{hfbuild.slug(str(m['text']))}.webm", []
        for p in work.glob(f"behind/*/{word}"):
            parts = p.parent.name.rsplit("-", 3)
            if len(parts) < 4 or not parts[2].isdigit() or not p.parent.name.startswith(hfbuild.slug(name) + "-"):
                continue
            src = srcs.get((parts[0], parts[1]))
            si = src and readable(probe, src)
            try:
                w2 = tb.window(*at, si.duration, si.fps or fps) if si else win
            except tb.Abort:
                continue
            off = abs(int(parts[2]) - w2["ka"])
            if off <= (0 if si else max(2, round(0.02 * w2["ka"]))):
                found.append((off, -p.stat().st_mtime, p, w2))
        clip, win = min(found, key=lambda c: c[:2])[2:] if found else (None, win)
        if clip is None:
            problems.append(problem(what, win["clip_start"], "clip", "has no rendered clip; run build_behind.py again"))
        ci = clip and readable(probe, clip)
        if clip and not ci:
            problems.append(unreadable(what, win["clip_start"], clip))
        dur = ci.duration if ci else win["clip_dur"]
        add(what, win["clip_start"], win["clip_start"] + dur, clip if ci else None,
            [tb.IN + 0.05, dur / 2, dur - tb.OUT - 0.05], behind=True)

    saved = run_windows(work, name)
    wins = morph_windows(saved, morph)
    # Auto mode edits one video at a time, so a clip older than this video's dead-air cut is another video's or an
    # earlier run's.
    cut = work / f"{name}.mp4"
    since = cut.stat().st_mtime if cut.is_file() else 0.0
    pool = [p for p in (*work.glob("morph/*.webm"), *work.glob("morph/*.mp4")) if p.stat().st_mtime >= since]
    if pool and not wins:
        notes.append(f"work/morph has {len(pool)} clip(s) rendered after this video's cut, but no morph windows are "
                     "known (no run file, no --morph), so they weren't checked; add --morph with their windows")
    seen = {}
    for p in pool if wins else []:
        ci = readable(probe, p)
        if ci is None:
            problems.append(unreadable(f"morph {p.stem.removeprefix('morph-')}", None, p))
        else:
            seen[p] = (p.stat().st_mtime, ci.duration)
    # shortcut: build_morph names a clip by template and title, not time. So a window takes a clip of its length (and
    # mode, from the run file); a run-file label that names one of them ("ring 87%": morph-ring-to-number-...) picks
    # it, and the other windows alike take the newest such clips in render order, which step 6 keeps in timeline
    # order. Exact once build_morph puts the start time in the clip name.
    alike = {}
    for a, b, mode, lab in sorted(wins, key=lambda x: (x[0], x[1])):
        fits = sorted((p for p in seen if abs(seen[p][1] - (b - a)) <= 1.5 / fps
                       and (mode is None or (p.suffix == ".mp4") == (mode == "cutaway"))), key=lambda p: seen[p][0])
        alike.setdefault(tuple(fits), []).append((a, b, lab))
    picked, used, unsure = {}, set(), set()
    for fits, ws in alike.items():
        free = [p for p in fits if p not in used]
        for a, b, lab in ws:
            hits = [p for p in free if label_words(lab) & set(p.stem.split("-"))]
            if len(hits) == 1:
                picked[a, b] = hits[0]
                free.remove(hits[0])
                used.add(hits[0])
        rest = [(a, b) for a, b, _ in ws if (a, b) not in picked]
        free = free[-len(rest):] if rest else []
        if 0 < len(free) < len(rest):     # fewer clips than windows: which one lost its clip can't be told, so no guess
            unsure.update(rest)
            notes.append(f"morph graphics at {', '.join(fmt_time(a) for a, _ in rest)}: {len(free)} clip(s) that long "
                         f"for {len(rest)} windows, and no run-file label names one, so which is which can't be told "
                         "and only their timing was checked; render the missing morph graphic again")
            free = []
        picked.update(zip(rest, free + [None] * len(rest)))
        used.update(free)
    for a, b, mode, _ in wins:
        clip = picked[a, b]
        if clip is None and (a, b) not in unsure:
            notes.append(f"morph graphic at {fmt_time(a)}: no {mode or 'morph'} clip {b - a:.1f} s long from this edit "
                         "in work/morph, so only its timing was checked")
        add(f"morph {clip.stem.removeprefix('morph-')}" if clip else "morph graphic", a, b, clip,
            [(b - a) * f for f in (0.15, 0.45, 0.8)],
            full=mode == "cutaway" if mode else bool(clip) and clip.suffix == ".mp4")

    for w in saved:      # a window the director planned that no plan in work/ draws
        if w.get("kind") != "morph" and not any(g["start"] < w["end"] and w["start"] < g["end"] for g in gs):
            notes.append(f"the run file has a {w.get('kind')} window at {fmt_time(w['start'])}-{fmt_time(w['end'])}"
                         f"{' (' + str(w['label']) + ')' if w.get('label') else ''}, but no plan in work/ covers it, "
                         "so nothing there was checked")
    return gs, problems, notes


# ---------- measuring ----------

def face_box(root: Path, name: str, video: Path, given: str | None):
    """The face box (fractions) graphics must stay off, and where it came from: --face, the punch-in plan (the
    tighter framing), or measured on the video."""
    if given:
        box, src = tuple(float(v) for v in given.split(",")), "--face"
    else:
        punch = root / "work" / f"{name}.punch.json"
        data = read_json(punch) if punch.is_file() else {}
        box = next((tuple(data[k]) for k in ("face_at_punch_in", "face")
                    if isinstance(data, dict) and isinstance(data.get(k), list) and len(data[k]) == 4), None)
        src = f"{punch.name}, the tighter framing" if box else "measured"
        box = box or analyze(video).face
    if not box:
        return None, "no face found"
    x0, y0, x1, y1 = box
    return (x0, y0, x1, min(1.0, y1 + 0.1 * (y1 - y0))), src     # the detector's box ends at the mouth: add the chin


def luma(clip: Path, mw: int, mh: int) -> np.ndarray:
    """Every frame's brightness (0-255), shrunk to mw x mh."""
    raw = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(clip), "-vf", f"scale={mw}:{mh}:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (mw * mh)
    if not n:
        raise RuntimeError(f"could not read {clip.name}")
    return np.frombuffer(raw[: n * mw * mh], np.uint8).reshape(n, mh, mw)


def black_ends(frames: np.ndarray) -> list[str]:
    """'starts' / 'ends' when the first / last frame is black but the clip's own background isn't: a black flash.
    A black background (the apple theme's) is the design, not a flash."""
    bg = float(np.median(np.median(frames.reshape(len(frames), -1), axis=1)))
    return [word for word, f in (("starts", frames[0]), ("ends", frames[-1]))
            if np.percentile(f, 99) <= 40 and bg - float(np.median(f)) >= 6]


def cells(mask: np.ndarray, box) -> int:
    """Opaque cells of a mask inside a box given as fractions (x0, y0, x1, y1)."""
    mh, mw = mask.shape
    x0, y0, x1, y1 = box
    return int(mask[max(0, int(y0 * mh)):int(np.ceil(y1 * mh)), max(0, int(x0 * mw)):int(np.ceil(x1 * mw))].sum())


def bbox(mask: np.ndarray) -> list[float] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    mh, mw = mask.shape
    return [round(xs.min() / mw, 3), round(ys.min() / mh, 3), round((xs.max() + 1) / mw, 3), round((ys.max() + 1) / mh, 3)]


@lru_cache(maxsize=8)
def _font(file: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT_DIR / file), size)


def caption_box(plan: dict, chunk: dict) -> tuple[float, float, float, float]:
    """Where make_captions draws a caption, as fractions: its size and position, the text measured in its font."""
    st = CAPTION_STYLES[plan["style"]]
    w, h = plan["width"], plan["height"]
    em = st["size"] * min(w, h) * plan.get("scale", 1.0)
    file = st.get("font", (None, SANS_FILE))[1]
    pad = em * (0.35 if st.get("boxed", True) else 0.13)          # the box, or the outline and shadow, round the letters
    half_w = _font(file, max(1, round(em))).getlength(str(chunk["text"])) / 2 + pad
    half_h = em * font_ratio(file) / 2 + pad
    y = float(plan["position"]) * h
    return max(0.0, 0.5 - half_w / w), (y - half_h) / h, min(1.0, 0.5 + half_w / w), (y + half_h) / h


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ---------- the check ----------

def check(root: Path, name: str, video: Path, face: str | None = None, platform: str = "none", morph: str = "") -> dict:
    work = root / "work"
    info = probe(video)
    gs, problems, notes = collect(root, name, info, morph)
    problems += theme_problems()
    fbox, face_from = face_box(root, name, video, face)
    if not fbox:
        notes.append("No face found, so nothing was checked against the face (give --face x0,y0,x1,y1).")
    cfile = plan_file(work, name, "captions")
    caps = read_json(cfile) if cfile else None
    try:      # (start, end, text, where it is drawn) of each caption
        cap = [(float(c["start"]), float(c["end"]), str(c["text"]), caption_box(caps, c)) for c in caps["chunks"]] if caps else []
    except (KeyError, TypeError, ValueError):
        raise RuntimeError(f"{cfile.name} isn't a captions plan from make_captions.py; make it again with --plan-only.") from None
    vertical = info.height >= 1.7 * info.width
    zones = ZONES.get(platform, {}) if vertical else {}
    if platform in ZONES and not vertical:
        notes.append(f"The {APP[platform]} zones are for 9:16 video, so they were skipped for this "
                     f"{info.width}x{info.height} one.")
    mw, mh = 192 * info.width // max(info.width, info.height), 192 * info.height // max(info.width, info.height)
    graze = max(2, int(GRAZE * mw * mh))

    ordered = sorted(gs, key=lambda g: (g["start"], g["end"]))
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            gap = b["start"] - a["end"]
            if gap >= GAP:
                break
            problems.append(problem(b["graphic"], b["start"], "timing",
                                    f"is on screen together with {a['graphic']} (until {fmt_time(a['end'])})" if gap < 0 else
                                    f"starts {gap:.2f} s after {a['graphic']} ends; leave at least {GAP} s"))

    for g in gs:
        g["boxes"] = []
        if g["clip"] is None:
            continue
        if g["full"]:
            frames = readable(luma, g["clip"], mw, mh)
            problems += [unreadable(g["graphic"], g["start"], g["clip"])] if frames is None else [
                problem(g["graphic"], g["start"] if end == "starts" else g["end"], "black",
                        f"{end} on a black frame: a black flash between the speaker and the graphic")
                for end in black_ends(frames)]
            continue
        ci, alpha = readable(probe, g["clip"]), readable(tb.read_alpha, g["clip"], mw, mh)
        fps = (ci and ci.fps) or info.fps or 30
        # a render killed half way still states its full length, but has fewer frames
        if ci is None or alpha is None or len(alpha) < round(ci.duration * fps) - 2:
            problems.append(unreadable(g["graphic"], g["start"], g["clip"]))
            continue
        masks = alpha >= OPAQUE
        dim = masks.mean(axis=(1, 2)) >= 0.9          # a dim over the whole frame (a title-card overlay): full screen
        found = {}                                    # the first time of each kind of problem
        for i, t in enumerate(sorted(g["checks"])):
            k = min(len(masks) - 1, max(0, round(t * fps)))
            m, at = masks[k], g["start"] + t
            g["boxes"].append({"time": round(at, 3), "box": bbox(m)})
            if i == 0 and not m.any():
                found.setdefault("blank", problem(g["graphic"], at, "blank",
                                                  "shows nothing at its first check time: it comes in late, or rendered empty"))
            if dim[k]:
                continue
            if fbox and not g["behind"] and cells(m, fbox) > graze:  # text behind the speaker is meant to touch the head
                found.setdefault("face", problem(g["graphic"], at, "face", "covers the face"))
            for zone, z in zones.items():
                if cells(m, z) > graze:
                    found.setdefault("zone", problem(g["graphic"], at, "zone", f"sits in the {APP[platform]} {zone} zone, "
                                                     "where the app draws its own buttons and text"))
            edges = [side for side, line in (("left", m[:, 0]), ("right", m[:, -1]), ("top", m[0]), ("bottom", m[-1]))
                     if line.any()]
            if edges:
                found.setdefault("edge", problem(g["graphic"], at, "edge", f"is cut off at the {' and '.join(edges)} edge"))
        # a caption can come and go between two check times, so every frame meets the caption then on screen
        for k, m in enumerate(masks):
            at = g["start"] + k / fps
            c = next((c for c in cap if c[0] <= at < c[1]), None)
            if c and not dim[k] and cells(m, c[3]) > graze:
                found["captions"] = problem(g["graphic"], at, "captions", f'covers the caption "{c[2]}"')
                break
        problems += found.values()

    for zone, z in zones.items():
        hits = [c for c in cap if overlaps(c[3], z)]
        if hits:
            problems.append(problem("captions", hits[0][0], "zone",
                                    f"{len(hits)} of {len(cap)} sit in the {APP[platform]} {zone} zone (from "
                                    f"\"{hits[0][2]}\"); move them with make_captions --position"))
    problems.sort(key=lambda p: (p["time"] is None, p["time"] or 0.0))

    report = {"name": name, "video": str(video), "face": fbox and [round(v, 3) for v in fbox], "face_from": face_from,
              "platform": platform, "captions": str(cfile) if cfile else None, "ok": not problems, "problems": problems,
              "notes": notes, "graphics": [{"graphic": g["graphic"], "start": round(g["start"], 3), "end": round(g["end"], 3),
                                            "clip": str(g["clip"]) if g["clip"] else None, "full_screen": g["full"],
                                            "boxes": g["boxes"]} for g in gs]}
    (work / f"{name}.qa.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def show(report: dict, root: Path) -> None:
    f = report["face"]
    where = f"face x {f[0]:.2f}-{f[2]:.2f}, y {f[1]:.2f}-{f[3]:.2f} ({report['face_from']})" if f else "no face found"
    zones = f"{APP[report['platform']]} zones" if report["platform"] in APP else "no platform zones (--platform)"
    print(f"Checked {len(report['graphics'])} graphic(s) on {report['name']}: {where}; {zones}.")
    for n in report["notes"]:
        print(f"note  {n}")
    for p in report["problems"]:
        print(f"FAIL  {p['graphic']}{'' if p['time'] is None else ' at ' + fmt_time(p['time'])}: {p['problem']}")
    out = (root / "work" / f"{report['name']}.qa.json").relative_to(root).as_posix()
    if report["problems"]:
        print(f"{len(report['problems'])} problem(s). Fix them, render that pass again, then run this check again. Report: {out}")
    else:
        print(f"All clear. Report: {out}")


# ---------- self-test ----------

FACE, FACE_BOX, CLEAN_BOX = "0.35,0.14,0.62,0.30", (0.40, 0.15, 0.60, 0.28), (0.10, 0.40, 0.90, 0.50)


def _clip(path: Path, dur: float, boxes=(), bg: str = "black@0", black_first: bool = False, size=(108, 192),
          mtime: float | None = None, fps: int = 30) -> Path:
    """A test clip: transparent (.webm) or solid (.mp4), with white boxes given as fractions."""
    w, h = size
    alpha = path.suffix == ".webm"
    vf = ["format=yuva420p" if alpha else "format=yuv420p"]
    vf += [f"drawbox=x={x0 * w:.0f}:y={y0 * h:.0f}:w={(x1 - x0) * w:.0f}:h={(y1 - y0) * h:.0f}:color=white:t=fill"
           + (":replace=1" if alpha else "") for x0, y0, x1, y1 in boxes]
    if black_first:
        vf.append("drawbox=w=iw:h=ih:color=black:t=fill:enable='eq(n,0)'")
    codec = (["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "0", "-crf", "40"]
             if alpha else ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    path.parent.mkdir(parents=True, exist_ok=True)
    # one graph, so the colour source is made with alpha (a separate -vf would add an opaque alpha)
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-f", "lavfi",
                    "-i", ",".join([f"color=c={bg}:s={w}x{h}:r={fps}:d={dur}", *vf]), *codec, str(path)], check=True)
    if mtime is not None:
        os.utime(path, (mtime, mtime))          # the render order, without waiting between renders
    return path


def _project(d: Path) -> tuple[Path, Path]:
    for sub in ("input", "output", "work"):
        (d / sub).mkdir(parents=True)
    return d, d / "work"


def self_test() -> int:
    # fonts: only a name the render reaches before a bundled font, a generic family or a variable counts
    lists = font_lists('<i style="font-family:\'SF Pro Display\', Inter, sans-serif">a</i>')
    assert swapped(lists) == ["SF Pro Display"], lists
    assert swapped(font_lists("<style>.a{font:800 40px/1 'Montserrat XB'}.b{font: 600 calc(var(--u)*.04)/1.2 Helvetica, "
                              "serif}.c{font-weight:600;font-size:12px}</style>")) == ["Helvetica"]
    assert swapped(font_lists('<svg><text font-family="Futura">x</text></svg>')) == ["Futura"]
    assert swapped(font_lists("<style>.a{font-family:'Inter', -apple-system, 'Helvetica Neue', sans-serif}</style>")) == []
    assert swapped(font_lists("<style>.c{--font-display:'Helvetica Neue'}.t{font-family:var(--font-display)}</style>")) == [
        "Helvetica Neue"]                                       # a card setting a theme font variable
    assert swapped(font_lists("<style>.c{--brand:'Futura', serif;--u:10px;--font-size:12px}.t{font:700 9px var(--brand)}"
                              "</style>")) == ["Futura"]        # its own variable; sizes aren't fonts
    for text, want in (("<style>/* was: font-family: Gotham */ .x{font-family:Inter}</style>", []),
                       ('<p style="font-family:&quot;Inter&quot;, serif">a</p>', []),
                       ("<style>@font-face{font-family:'Brand';src:url('assets/fonts/Inter-Bold.ttf')}.x{font-family:Brand}"
                        "</style>", []),                                         # its own name for a bundled file
                       ("<style>@font-face{font-family:'Gotham';src:url('fonts/Gotham.otf')}.x{font-family:Gotham}</style>",
                        ["Gotham"]),
                       ('<script>tl.set(".x", {fontFamily: "Gotham, sans-serif"})</script>', ["Gotham"]),
                       ("<style>.c{--hero:700 40px Gotham}.t{font:var(--hero)}</style>", ["Gotham"]),
                       ("<style>.t{font:caption}</style>", ["caption"])):
        assert swapped(font_lists(text), aliases(text)) == want, (text, font_lists(text))
    assert not theme_problems(), theme_problems()             # every shipped theme uses bundled fonts
    for fn, s in ((morph_arg, "abc"), (morph_arg, "3-2"), (face_arg, "x"), (face_arg, "0.5,0.1,0.4,0.3"),
                  (name_arg, "My Talk.mp4"), (name_arg, "work/talk")):
        try:
            fn(s)
        except argparse.ArgumentTypeError:
            continue
        raise AssertionError(f"{fn.__name__} took {s!r}")
    navy = np.full((6, 4, 4), 29, np.uint8)
    flash = navy.copy()
    flash[0] = 16
    assert black_ends(navy) == [] and black_ends(flash) == ["starts"]
    assert black_ends(np.full((6, 4, 4), 16, np.uint8)) == []           # a black background is no flash

    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        video = _clip(base / "v.mp4", 20, bg="gray")
        now = video.stat().st_mtime
        html = "<div>x</div>"

        # 1. One video with every kind of problem, each graphic 0.5 s or more from the next unless planted.
        root, work = _project(base / "a")
        specs = [  # the planted bad card: a font that isn't bundled and a box over the face
            {"template": "card", "name": "bad", "start": 2.8, "end": 4.8, "checks": [3.3],
             "html": "<div class=\"b\">90%</div><style>.b{font-family:'Helvetica Neue',sans-serif}</style>"},
            {"template": "card", "name": "good", "start": 5.4, "end": 6.9, "html": '<div style="font-family:Inter">ok</div>'},
            {"template": "card", "name": "edge", "start": 7.5, "end": 8.5, "html": html},
            {"template": "card", "name": "cut", "start": 9.1, "end": 10.1, "mode": "cutaway", "html": html},
            {"template": "card", "name": "low", "start": 13.0, "end": 17.0, "html": html}]     # checks at 14.0 and 15.4
        _clip(template_clip(work, specs[0], 2.8, True), 2.0, [FACE_BOX])
        _clip(template_clip(work, specs[1], 5.4, True), 1.5, [(0.10, 0.40, 0.90, 0.55)])
        _clip(template_clip(work, specs[2], 7.5, True), 1.0, [(0.0, 0.40, 0.30, 0.50)])
        _clip(template_clip(work, specs[3], 9.1, False), 1.0, bg="0x06101d", black_first=True)
        _clip(template_clip(work, specs[4], 13.0, True), 4.0, [(0.15, 0.72, 0.85, 0.84)])
        _clip(work / "kinetic" / "kt-x-01-wow.webm", 0.8)                                     # rendered empty
        _clip(work / "morph" / "morph-ring-to-number-x.webm", 1.0, [(0.30, 0.74, 0.70, 0.80)])
        win = tb.window(0.6, 0.9, None, 20, 30)       # made from a cut that's gone, its frame rate a frame off
        _clip(work / "behind" / f"x-clean-1-{win['ka'] + 1}-999" / "word-big.webm", win["clip_dur"],
              [(0.30, 0.15, 0.70, 0.25)])
        (work / "x.templates.json").write_text(json.dumps(specs), encoding="utf-8")
        (work / "x.emphasis.json").write_text(json.dumps({"moments": [{"start": 10.2, "end": 10.5, "text": "wow"}]}))
        (work / "x.behind.json").write_text(json.dumps({"moments": [{"start": 0.6, "end": 0.9, "text": "BIG"}]}))
        (work / "x.t.captions.json").write_text(json.dumps(
            {"style": "reel", "width": 108, "height": 192, "fps": 30, "position": 0.78, "scale": 1.0,
             "chunks": [{"start": 5.6, "end": 6.2, "text": "HI"}, {"start": 11.6, "end": 12.0, "text": "HELLO"},
                        {"start": 14.2, "end": 15.2, "text": "MONEY"}]}))       # MONEY falls between low's checks
        rep = check(root, "x", video, FACE, "none", "11.4-12.4")
        got = {(p["graphic"], p["kind"]): p["time"] for p in rep["problems"]}
        want = {('card "bad"', "font"), ('card "bad"', "face"), ('card "edge"', "edge"), ('card "cut"', "black"),
                ('kinetic text "wow"', "timing"), ('kinetic text "wow"', "blank"), ("morph ring-to-number-x", "captions"),
                ('card "low"', "captions")}
        assert set(got) == want, sorted(set(got) ^ want)
        assert got['card "bad"', "face"] == 3.3 and abs(got['card "low"', "captions"] - 14.2) < 0.05, got
        assert not rep["ok"] and (work / "x.qa.json").is_file() and rep["graphics"][-2]["clip"], rep["graphics"][-2]
        rep = check(root, "x", video, FACE, "reels", "11.4-12.4")
        got = {(p["graphic"], p["kind"]) for p in rep["problems"]} - want
        assert got == {('card "edge"', "zone"), ("morph ring-to-number-x", "zone"), ("captions", "zone"),
                       ('card "low"', "zone")}, got
        (work / "x.punch.json").write_text(json.dumps({"face": [0.4, 0.2, 0.6, 0.3], "face_at_punch_in": [0.3, 0.1, 0.7, 0.4]}))
        box, src = face_box(root, "x", video, None)
        assert np.allclose(box, (0.3, 0.1, 0.7, 0.43)) and "punch" in src, (box, src)

        # 2. Three morph windows of the same length: two rendered in timeline order, the third not rendered, and an
        #    earlier run's clip of that length. Then kinetic clips of one word said twice, next to another video's (k2).
        root, work = _project(base / "b")
        _clip(work / "morph" / "morph-old.webm", 3.0, mtime=now - 30)                       # older than the cut
        (work / "m.mp4").write_bytes(b"")                                                     # the dead-air cut
        os.utime(work / "m.mp4", (now - 25, now - 25))
        bars = _clip(work / "morph" / "morph-bars.mp4", 3.0, bg="0x101418", mtime=now - 20)
        _clip(work / "morph" / "morph-ring.webm", 3.0, [FACE_BOX], mtime=now - 10)
        rep = check(root, "m", video, FACE, "none", "1.0-4.0,7.0-10.0")
        pairs = [(g["graphic"], g["start"], g["full_screen"]) for g in rep["graphics"]]
        assert pairs == [("morph bars", 1.0, True), ("morph ring", 7.0, False)], pairs
        assert [(p["graphic"], p["kind"], p["time"]) for p in rep["problems"]] == [("morph ring", "face", 7.45)], rep
        third = check(root, "m", video, FACE, "none", "1.0-4.0,7.0-10.0,13.0-16.0")   # 2 clips for 3: no guess
        assert third["ok"] and all(g["clip"] is None for g in third["graphics"]), third
        assert any("which is which" in n for n in third["notes"]), third["notes"]
        os.utime(bars, (now - 5, now - 5))        # rendered out of order: the run file's modes still pair them
        (work / "m.run.json").write_text(json.dumps({"windows": {
            "cutaway": [{"start": 1.0, "end": 4.0, "kind": "morph", "label": "bars"}],
            "overlay": [{"start": 7.0, "end": 10.0, "kind": "morph", "label": "ring"}]}}))
        again = check(root, "m", video, FACE)     # no --morph: the run file's windows
        assert again["problems"] == rep["problems"] and [g["clip"] for g in again["graphics"]] == [
            g["clip"] for g in rep["graphics"][:2]], again
        # The earlier of two windows alike lost its clip (a failed render): the label names the clip that is there.
        (work / "n.mp4").write_bytes(b"")
        os.utime(work / "n.mp4", (now, now))
        _clip(work / "morph" / "morph-ring-to-number-clip.webm", 2.6, [FACE_BOX], mtime=now + 5)
        run = {"windows": {"cutaway": [], "overlay": [{"start": 1.0, "end": 3.6, "kind": "morph", "label": "check"},
                                                      {"start": 6.0, "end": 8.6, "kind": "morph", "label": "ring 87%"}]}}
        (work / "n.run.json").write_text(json.dumps(run))
        rep = check(root, "n", video, FACE)
        assert [(g["graphic"], g["start"]) for g in rep["graphics"]] == [
            ("morph graphic", 1.0), ("morph ring-to-number-clip", 6.0)], rep["graphics"]
        assert [(p["kind"], p["time"]) for p in rep["problems"]] == [("face", 6.39)], rep["problems"]
        assert any("0:01.0: no overlay clip" in n for n in rep["notes"]), rep["notes"]
        for w, lab in zip(run["windows"]["overlay"], ("first", "second")):
            w["label"] = lab                      # labels that name nothing: no guess, a note instead
        (work / "n.run.json").write_text(json.dumps(run))
        rep = check(root, "n", video, FACE)
        assert rep["ok"] and any("which is which" in n for n in rep["notes"]), rep
        (work / "k.emphasis.json").write_text(json.dumps({"moments": [
            {"start": 2.0, "text": "10X"}, {"start": 5.0, "text": "wow"}, {"start": 5.4, "text": "now"},
            {"start": 8.0, "text": "10X"}]}))     # "wow" is too close to "now", so build_kinetic numbers now 02
        _clip(work / "kinetic" / "kt-k-01-10x.webm", 1.6, [FACE_BOX], mtime=now - 30)
        _clip(work / "kinetic" / "kt-k-02-now.webm", 1.6, [CLEAN_BOX], mtime=now - 20)
        _clip(work / "kinetic" / "kt-k-03-10x.webm", 1.6, [CLEAN_BOX], mtime=now - 10)
        _clip(work / "kinetic" / "kt-k2-01-10x.webm", 1.6, [CLEAN_BOX], mtime=now)
        # Text behind made from a later cut at another frame rate: its first frame is far from this cut's, and is
        # worked out with that cut's own rate.
        clean = _clip(work / "k.clean.mp4", 20, bg="gray", fps=25)
        (work / "k.behind.json").write_text(json.dumps({"moments": [{"start": 15.0, "end": 15.4, "text": "TOP"}]}))
        w25, w30 = tb.window(15.0, 15.4, None, 20, 25), tb.window(15.0, 15.4, None, 20, 30)
        assert abs(w25["ka"] - w30["ka"]) > 0.02 * w30["ka"], (w25, w30)
        _clip(work / "behind" / f"k-clean-{int(clean.stat().st_mtime)}-{w25['ka']}-{w25['frames']}" / "word-top.webm",
              w25["clip_dur"], [CLEAN_BOX])
        rep = check(root, "k", video, FACE)
        assert [(p["graphic"], p["kind"], p["time"]) for p in rep["problems"]] == [('kinetic text "10X"', "face", 2.45)], rep
        assert len(rep["graphics"]) == 4 and any('"wow"' in n for n in rep["notes"]), rep
        assert rep["graphics"][-1]["start"] == round(w25["clip_start"], 3), rep["graphics"][-1]

        # 3. A 16:9 video skips the app zones; a damaged plan stops the check; a missing card file is named plainly.
        root, work = _project(base / "c")
        wide = _clip(base / "w.mp4", 6, bg="gray", size=(192, 108))
        specs = [{"template": "card", "name": "side", "start": 1.0, "end": 3.0, "html": html}]
        (work / "w.templates.json").write_text(json.dumps(specs))
        _clip(template_clip(work, specs[0], 1.0, True), 2.0, [(0.65, 0.30, 0.95, 0.60)], size=(192, 108))
        (work / "w.captions.json").write_text(json.dumps(
            {"style": "reel", "width": 192, "height": 108, "fps": 30, "position": 0.86, "scale": 1.0,
             "chunks": [{"start": 0.5, "end": 5.5, "text": "HELLO THERE"}]}))
        rep = check(root, "w", wide, "0.20,0.15,0.35,0.45", "reels")
        assert rep["ok"] and any("9:16" in n for n in rep["notes"]), rep
        (work / "bj.templates.json").write_text('[{"template":"card",')
        try:
            check(root, "bj", video, FACE)
            raise AssertionError("a damaged plan must stop the check")
        except RuntimeError as e:
            assert "bj.templates.json" in str(e), e
        (work / "mf.templates.json").write_text(json.dumps(
            [{"template": "card", "start": 1.0, "end": 3.0, "file": "work/cards/nope.html"}]))
        rep = check(root, "mf", video, FACE)
        assert [p["problem"] for p in rep["problems"]] == ["its card file work/cards/nope.html is missing"], rep

        # 4. A damaged clip is one FAIL and the rest are still checked; nothing is passed over in silence. An overlay
        #    cut short by a killed render still states its full length, so its frames are counted.
        specs = [{"template": "card", "name": "zero", "start": 1.0, "end": 3.0, "html": html},
                 {"template": "card", "name": "fine", "start": 4.0, "end": 6.0, "html": html},
                 {"template": "card", "name": "half", "start": 7.0, "end": 9.0, "html": html}]
        (work / "z.templates.json").write_text(json.dumps(specs))
        template_clip(work, specs[0], 1.0, True).write_bytes(b"")
        _clip(template_clip(work, specs[1], 4.0, True), 2.0, [FACE_BOX])
        half = _clip(template_clip(work, specs[2], 7.0, True), 2.0, [CLEAN_BOX])
        half.write_bytes(half.read_bytes()[: half.stat().st_size // 2])
        rep = check(root, "z", video, FACE)
        assert [(p["graphic"], p["kind"]) for p in rep["problems"]] == [
            ('card "zero"', "clip"), ('card "fine"', "face"), ('card "half"', "clip")], rep
        (work / "e.run.json").write_text(json.dumps({"windows": {"cutaway": [], "overlay": [
            {"start": 1.0, "end": 3.0, "kind": "card", "label": "stat"}]}}))     # a card window, no templates plan
        _clip(work / "morph" / "morph-bars.mp4", 1.0)                             # a morph clip, no morph windows
        rep = check(root, "e", video, FACE)
        assert rep["ok"] and len(rep["notes"]) == 2 and "(stat), but no plan" in rep["notes"][1], rep["notes"]
        assert "no morph windows" in rep["notes"][0], rep["notes"]
    print("qa_graphics self-test: OK")
    return 0


def face_arg(s: str) -> str:
    try:
        v = [float(x) for x in s.split(",")]
    except ValueError:
        v = []
    if len(v) != 4 or not (0 <= v[0] < v[2] <= 1 and 0 <= v[1] < v[3] <= 1):
        raise argparse.ArgumentTypeError("give four fractions x0,y0,x1,y1, e.g. 0.35,0.14,0.62,0.30")
    return s


def name_arg(s: str) -> str:
    if Path(s).name != s or Path(s).suffix.lower() in VIDEO_EXTS:
        raise argparse.ArgumentTypeError(f"give the video's name without its folder or extension (talk for "
                                         f"input/talk.mov), not {s!r}")
    return s


def morph_arg(s: str) -> str:
    try:
        ok = all(len(w) == 2 and 0 <= w[0] < w[1] for w in windows(s))
    except ValueError:
        ok = False
    if not ok:
        raise argparse.ArgumentTypeError('give the windows in seconds, like "2.9-5.9,8.2-10.8"')
    return s


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Check one video's graphics by machine before the hand-over.")
    p.add_argument("name", nargs="?", type=name_arg,
                   help="the video's name in work/, without its extension (work/<name>.mp4 is its dead-air cut)")
    p.add_argument("--video", type=Path, help="the video the face is measured on (default: work/<name>.mp4)")
    p.add_argument("--face", type=face_arg,
                   help="the face box as x0,y0,x1,y1 fractions (default: work/<name>.punch.json, else measured)")
    p.add_argument("--platform", choices=(*ZONES, "none"), default="none",
                   help="keep graphics and captions out of this app's buttons and text, on 9:16 video (default: none)")
    p.add_argument("--morph", type=morph_arg, default="",
                   help='the morph graphic windows, e.g. "2.9-5.9,8.2-10.8" (default: the run file\'s)')
    p.add_argument("--self-test", action="store_true", help="check the checks on small made-up clips, then exit")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.name:
        p.error("give the video's name, or --self-test")
    root = project_root()
    video = args.video or root / "work" / f"{args.name}.mp4"
    if not video.is_file():
        print(f"{video} not found: give the video with --video.")
        return 2
    try:
        report = check(root, args.name, video, args.face, args.platform, args.morph)
    except (SetupError, RuntimeError) as e:
        print(e)
        return 2
    except (ValueError, TypeError, KeyError) as e:      # a plan value of the wrong type, such as "end": "1.5s"
        print(f"A plan in work/ is damaged: {e}. Fix it by hand, or write it again with the step that made it.")
        return 2
    show(report, root)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
