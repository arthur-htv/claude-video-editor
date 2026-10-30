#!/usr/bin/env python3
"""Burn readable, on-brand captions into a video.

Default "reel" look (from the editing playbook): 1-3 words at a time, ALL CAPS
Montserrat ExtraBold in one dark box with a thin light edge, hard swaps (no pop),
shown 2 frames before the word. A quarter to under half of the chunks are colored
by meaning (red = wrong/loss, teal = keyword/number, green = action/payoff), a few
soft words get a serif accent, and captions sit below the face, never over the mouth.

Examples (from the project folder, with the .venv python)
  python make_captions.py work/talk.mp4                        -> output/talk.mp4 (transcribes first)
  python make_captions.py work/talk.mp4 --plan-only            -> work/talk.captions.json to review / fix words
  python make_captions.py work/talk.mp4 --from-plan work/talk.captions.json
  python make_captions.py work/talk.mp4 --style clean --srt    -> subtitle-style lines + output/talk.srt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent / "video-editor" / "scripts"
sys.path.insert(0, str(SHARED))
from vtools import SetupError, find_tool, fmt_time, probe, project_root  # noqa: E402

FONT_DIR = SHARED.parent / "assets" / "fonts"
SANS, SERIF = "Montserrat ExtraBold", "Abril Fatface"
SANS_FILE, SERIF_FILE = "Montserrat-ExtraBold.ttf", "AbrilFatface-Regular.ttf"

STYLES = {
    # max words per chunk, max characters (portrait, landscape), size (fraction of the short side), caps, colors
    "reel": dict(words=3, chars=(16, 22), size=0.059, caps=True, colors=True, serif=True),
    "minimal": dict(words=1, chars=(14, 18), size=0.046, caps=True, colors=False, serif=False),
    "clean": dict(words=7, chars=(30, 42), size=0.05, caps=False, colors=False, serif=False),
}
HEX = {"white": "#FFFFFF", "teal": "#2EE6D6", "red": "#FF5A5F", "green": "#4ADE80", "yellow": "#FFD84A"}
BOX, EDGE = "#121212", "#E6E6E6"

NEG = set("""never not no don't dont can't cant won't wont wrong mistake mistakes lose losing lost fail failed failing
problem problems broke broken waste wasted stop worst bad hard harder expensive risk risky slow slower nobody
nothing without miss missed quit hate pain scam""".split())
POS = set("""do try start build get use save saves saved grow growth win wins works work fast faster easy easier
free better best more money results result done fix fixed make made double triple boost profit love yes
simple simpler instantly automatically""".split())
SOFT = set("""a an the and or but so of to in on at for with by from is it it's its that this
these those your you my we our just then than as if be are was were""".split())
MARKERS = set("first second third fourth fifth finally step secret rule".split())
COMMON = SOFT | set("""i me he she they them what when where who how why want show tell know think going
gonna get got have has had do does did can could will would should here there today now about into out
up down over all any some more very really thing things way time back welcome hey everyone""".split())
NUMBER = re.compile(r"^[$€£]?\d[\d,.]*(%|x|k|m|b)?$|^\d+(st|nd|rd|th)$", re.I)


# ---------------------------------------------------------------------------- planning

def clean_word(word: str, caps: bool) -> str:
    w = word.strip()
    if caps:
        w = re.sub(r"[.,;:…\"“”]+", "", w).upper()   # keep ? ! ' % $ in caps style
    return w


# Words that lean on the next word: a chunk should not end with them ("WELCOME BACK | TO THE CHANNEL").
DANGLE = set("""a an the and or but so of to in on at for with by from your my our their his her its
as than if into about over is are was were be""".split())


def _norm(word: str) -> str:
    return word.lower().strip(",.!?;:\"'")


def split_phrase(phrase: list[dict], max_words: int, max_chars: int) -> list[list[dict]]:
    """Best way to cut one phrase into chunks: few chunks, no chunk ending on a word that leans on
    the next one, no split between two content words ("THE DEAD AIR", not "THE DEAD | AIR")."""
    n = len(phrase)
    best = [0.0] + [float("inf")] * n
    back = [0] * (n + 1)
    for i in range(1, n + 1):
        for j in range(max(0, i - max_words), i):
            part = phrase[j:i]
            if len(" ".join(w["word"] for w in part)) > max_chars and len(part) > 1:
                continue
            cost = 1.0
            last = _norm(part[-1]["word"])
            if i < n:
                nxt = _norm(phrase[i]["word"])
                if last in DANGLE:
                    cost += 2.0
                elif last not in COMMON and nxt not in COMMON and nxt not in DANGLE:
                    cost += 1.2                    # splitting two content words ("raw | footage")
            if len(part) == 1 and n > 1 and max_words > 1:
                cost += 1.2 if last in DANGLE else 0.5
            if max_words >= 5 and len(part) <= 2 and n >= 5:
                cost += 0.8                        # subtitle lines: no stubby "today I" lines
            if best[j] + cost < best[i]:
                best[i], back[i] = best[j] + cost, j
    chunks, i = [], n
    while i > 0:
        chunks.append(phrase[back[i]:i])
        i = back[i]
    return chunks[::-1]


def chunk_words(words: list[dict], max_words: int, max_chars: int) -> list[list[dict]]:
    """Split the words into phrases (punctuation or a pause ends one), then each phrase into chunks.
    A chunk never crosses a phrase boundary, so captions follow the speaker's breathing."""
    phrases, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["word"].rstrip().endswith((",", ".", "?", "!", ";", ":")) or nxt is None or nxt["start"] - w["end"] > 0.25:
            phrases.append(cur)
            cur = []
    chunks = []
    for ph in phrases:
        chunks += split_phrase(ph, max_words, max_chars)
    return chunks


def classify(words_: list[str], sentence_start: bool) -> tuple[str, int]:
    """(color, strength) for a chunk; strength 2 = clear meaning, 1 = weak keyword, 0 = none."""
    lw = [re.sub(r"[^\w$%'€£]", "", w.lower()) for w in words_]
    if any(w in NEG for w in lw):
        return "red", 2
    if any(NUMBER.match(w) for w in lw if w):
        return "teal", 2
    if any(w in POS for w in lw):
        return "green", 2
    proper = [w for i, w in enumerate(words_) if w[:1].isupper() and w.lower() != "i"
              and not (i == 0 and sentence_start)]
    if proper or any(w in MARKERS for w in lw):
        return "teal", 2
    content = [w for w in lw if w and w not in COMMON]
    if content and max(len(w) for w in content) >= 5:
        return "teal", 1                     # a real content word; used to fill up to a quarter
    return "white", 0


def plan_captions(words: list[dict], style: str, fps: float, vertical: bool,
                  use_color: bool = True, use_serif: bool = True) -> list[dict]:
    st = STYLES[style]
    chunks = chunk_words(words, st["words"], st["chars"][0 if vertical else 1])
    lead = 2.0 / (fps or 30)
    out = []
    for i, c in enumerate(chunks):
        prev_word = chunks[i - 1][-1]["word"] if i else "."
        sentence_start = prev_word.endswith((".", "?", "!"))
        raw = [w["word"] for w in c]
        color, strength = classify(raw, sentence_start) if (st["colors"] and use_color) else ("white", 0)
        out.append({"start": max(0.0, c[0]["start"] - lead), "word_end": c[-1]["end"],
                    "text": " ".join(clean_word(w, st["caps"]) for w in raw).strip(),
                    "color": color, "strength": strength, "serif": False,
                    "soft": all(w.lower().strip(",.!?") in SOFT for w in raw)})
    # timing: hard swap to the next chunk, or hold briefly before a pause
    for i, c in enumerate(out):
        nxt = out[i + 1]["start"] if i + 1 < len(out) else None
        if nxt is not None and nxt - c["word_end"] < 0.7:
            c["end"] = nxt
        else:
            c["end"] = c["word_end"] + 0.3 if nxt is None else min(c["word_end"] + 0.3, nxt)
        c["end"] = max(c["end"], c["start"] + 1.0 / (fps or 30))
    # color budget: 25-45% of chunks (aim for a third), strongest meaning first, avoid neighbours
    if st["colors"] and use_color and out:
        n = len(out)
        cap, target = max(1, int(0.45 * n)), max(1, round(0.33 * n))
        strong = [i for i, c in enumerate(out) if c["strength"] == 2]
        keep = set(strong[:: max(1, round(len(strong) / cap))][:cap]) if strong else set()
        for i in (i for i, c in enumerate(out) if c["strength"] == 1):
            if len(keep) >= target:
                break
            if i - 1 not in keep and i + 1 not in keep:
                keep.add(i)
        for i, c in enumerate(out):
            if i not in keep:
                c["color"] = "white"
    # serif accent: soft-word chunks, at most 20%, never two in a row, never on a colored chunk
    if st["serif"] and use_serif:
        budget, last = int(0.2 * len(out)), -2
        for i, c in enumerate(out):
            if budget and c["soft"] and c["color"] == "white" and i - last > 1:
                c["serif"], last, budget = True, i, budget - 1
                c["text"] = c["text"].lower()
    for c in out:
        c.pop("word_end"), c.pop("strength"), c.pop("soft")
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return out


# ---------------------------------------------------------------------------- rendering

def ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_text(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def font_ratio(font_file: str) -> float:
    """libass sizes fonts by line height; convert from the em size we think in."""
    try:
        from PIL import ImageFont
        asc, desc = ImageFont.truetype(str(FONT_DIR / font_file), 100).getmetrics()
        return (asc + desc) / 100.0
    except Exception:
        return 1.22


def build_ass(plan: dict) -> str:
    w, h = plan["width"], plan["height"]
    st = STYLES[plan["style"]]
    em = st["size"] * min(w, h) * plan.get("scale", 1.0)
    fs = round(em * font_ratio(SANS_FILE))
    fs_serif = round(em * 1.08 * font_ratio(SERIF_FILE))
    pad, edge = max(4, round(0.30 * em)), max(2, round(0.05 * em))
    x, y = round(w / 2), round(plan["position"] * h)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Edge,{SANS},{fs},&H00FFFFFF&,&H00FFFFFF&,{ass_color(EDGE)},&H00000000&,0,0,0,0,100,100,1,0,3,{pad + edge},0,5,0,0,0,1
Style: Box,{SANS},{fs},&H00FFFFFF&,&H00FFFFFF&,{ass_color(BOX)},&H00000000&,0,0,0,0,100,100,1,0,3,{pad},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in plan["chunks"]:
        font = f"\\fn{SERIF}\\fs{fs_serif}" if c.get("serif") else ""
        txt = ass_text(c["text"])
        a, b = ass_time(c["start"]), ass_time(c["end"])
        col = ass_color(HEX.get(c.get("color", "white"), c.get("color") if str(c.get("color", "")).startswith("#") else "#FFFFFF"))
        lines.append(f"Dialogue: 0,{a},{b},Edge,,0,0,0,,{{\\pos({x},{y}){font}\\1a&HFF&}}{txt}")
        lines.append(f"Dialogue: 1,{a},{b},Box,,0,0,0,,{{\\pos({x},{y}){font}\\c{col}}}{txt}")
    return header + "\n".join(lines) + "\n"


def write_srt(chunks: list[dict], path: Path) -> None:
    def t(s: float) -> str:
        ms = int(round(s * 1000))
        hh, ms = divmod(ms, 3600000)
        mm, ms = divmod(ms, 60000)
        ss, ms = divmod(ms, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"
    path.write_text("\n".join(f"{i}\n{t(c['start'])} --> {t(c['end'])}\n{c['text']}\n"
                              for i, c in enumerate(chunks, 1)), encoding="utf-8")


def burn(video: Path, plan: dict, out: Path, crf: int, speed: str) -> None:
    from cut_dead_air import run_ffmpeg, video_codec_args

    root = project_root()
    work = root / "work"
    work.mkdir(exist_ok=True)
    ass = work / f"captions_{abs(hash(str(video))) % 10**8}.ass"   # simple name: filter args dislike odd characters
    ass.write_text(build_ass(plan), encoding="utf-8")
    # The subtitle filter only takes relative paths (a drive letter's colon breaks it), so the fonts
    # are copied next to the subtitle file inside the project.
    fonts_dir = work / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for f in (SANS_FILE, SERIF_FILE):
        if not (fonts_dir / f).exists():
            shutil.copy2(FONT_DIR / f, fonts_dir / f)
    fonts = fonts_dir.relative_to(root).as_posix()
    info = probe(video)
    vargs, _ = video_codec_args(info, crf, speed)
    vf = f"ass={ass.relative_to(root).as_posix()}:fontsdir={fonts}"
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(video.resolve()),
           "-map", f"0:v:{info.video_index}", "-map", "0:a?", "-vf", vf, *vargs, "-c:a", "copy",
           "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out.resolve())]
    out.parent.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()
    try:
        os.chdir(root)            # the subtitle filter gets relative paths (Windows drive letters break it)
        run_ffmpeg(cmd, info.duration, video.name)
    finally:
        os.chdir(cwd)


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Burn styled captions into a video.")
    p.add_argument("video", type=Path)
    p.add_argument("--words", type=Path, help="word timings (.words.json or a kit transcript); default: transcribe now")
    p.add_argument("--model", default="small", help="speech model when transcribing (default small)")
    p.add_argument("--language", help="language code, e.g. en (default: detect)")
    p.add_argument("--style", choices=list(STYLES), default="reel", help="reel (default), minimal, clean")
    p.add_argument("--position", default="auto", help="auto (below the face), top, middle, bottom, or 0-1")
    p.add_argument("--scale", type=float, default=1.0, help="text size multiplier (default 1.0)")
    p.add_argument("--no-color", action="store_true", help="all captions white")
    p.add_argument("--no-serif", action="store_true", help="no serif accent words")
    p.add_argument("--plan-only", action="store_true", help="write the caption plan to work/ and stop")
    p.add_argument("--from-plan", type=Path, help="render an edited plan instead of planning again")
    p.add_argument("--out", type=Path, help="output video (default: output/<name>.mp4)")
    p.add_argument("--srt", action="store_true", help="also write the captions as an .srt next to the output")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--speed", default="fast")
    args = p.parse_args()

    root = project_root()
    video = args.video if args.video.exists() else root / "input" / args.video
    if not video.is_file():
        print(f"Not found: {args.video}")
        return 2
    try:
        info = probe(video)
    except SetupError as e:
        print(e)
        return 2
    if not info.has_video:
        print("This file has no picture to put captions on.")
        return 2
    stem = video.stem
    plan_path = root / "work" / f"{stem}.captions.json"

    if args.from_plan:
        plan = json.loads(args.from_plan.read_text(encoding="utf-8"))
    else:
        from transcribe import load_words, transcribe_words
        if args.words:
            words = load_words(args.words)
        else:
            print(f"Transcribing {video.name} ('{args.model}' model)...", flush=True)
            words, _ = transcribe_words(video, args.model, args.language)
        if not words:
            print("No speech found, so there is nothing to caption.")
            return 1
        from layout import analyze
        lay = analyze(video, info)
        named = {"top": 0.16, "middle": 0.5, "bottom": 0.86 if not lay.vertical else 0.78}
        pos = lay.caption_y if args.position == "auto" else named.get(args.position)
        if pos is None:
            pos = float(args.position)
        plan = {"source": str(video), "style": args.style, "width": info.width, "height": info.height,
                "fps": info.fps or 30, "position": round(pos, 3), "scale": args.scale, "layout_note": lay.note,
                "chunks": plan_captions(words, args.style, info.fps or 30, lay.vertical,
                                        not args.no_color, not args.no_serif)}
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        colored = sum(c["color"] != "white" for c in plan["chunks"])
        serif = sum(bool(c.get("serif")) for c in plan["chunks"])
        print(f"Plan: {len(plan['chunks'])} captions ({colored} colored, {serif} serif), "
              f"placed at {plan['position']:.0%} of the height ({lay.note}).")
        print(f"Plan file: {plan_path}  (fix misheard words or colors there, then --from-plan)")
        if args.plan_only:
            return 0

    out = args.out or root / "output" / f"{stem}.mp4"
    if out.resolve() == video.resolve():
        print("The output would overwrite the source. Use --out with a different name.")
        return 2
    if out.exists() and not args.overwrite:
        print(f"{out} already exists (use --overwrite or --out).")
        return 1
    burn(video, plan, out, args.crf, args.speed)
    res = probe(out)
    if abs(res.duration - info.duration) > 0.5:
        print(f"WARNING: result is {fmt_time(res.duration)}, source {fmt_time(info.duration)}")
    if args.srt:
        write_srt(plan["chunks"], out.with_suffix(".srt"))
    from hfbuild import contact_sheet
    chunks = plan["chunks"]
    picks = [chunks[i] for i in sorted({round(k * (len(chunks) - 1) / 5) for k in range(6)})] if chunks else []
    sheet = contact_sheet(out, [(c["start"] + c["end"]) / 2 for c in picks],
                          root / "work" / f"{stem}.captions-check.png")
    print(f"OK  {out}  ({len(chunks)} captions, {fmt_time(res.duration)})")
    print(f"Check frames: {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
