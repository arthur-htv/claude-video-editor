#!/usr/bin/env python3
"""Find the few moments in a talk that deserve kinetic text.

Combines HOW something is said (louder than the speaker's own running level,
stretched-out delivery, a beat of silence before it) with WHAT is said (numbers
and money, absolutes like "never" / "always", names, contrasts, and keywords you
pass in), then keeps only the strongest moments, spaced apart so the video never
gets cluttered.

Examples (from the project folder, with the .venv python)
  python find_emphasis.py work/talk.mp4                         -> work/talk.emphasis.json
  python find_emphasis.py work/talk.mp4 --keywords "10x, Claude" --max 6
  python find_emphasis.py work/talk.mp4 --words work/talk.words.json --min-gap 8
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent / "video-editor" / "scripts"
sys.path.insert(0, str(SHARED))
from vtools import find_tool, fmt_time, probe, project_root  # noqa: E402

import numpy as np  # noqa: E402

NUMBER = re.compile(r"\d|%|\$|€|£|\bhalf\b|\bdouble\b|\btriple\b|\bten\b|\bhundred\b|\bthousand\b|\bmillion\b|\bbillion\b", re.I)
ABSOLUTE = set("""never always every everything nothing nobody only best worst biggest fastest easiest secret
must stop instantly guaranteed zero free forever impossible""".split())
CONTRAST = set("but actually instead however except unless".split())
NEGATIVE = set("never not no don't can't won't wrong mistake lose lost fail problem broke waste worst bad stop".split())
POSITIVE = set("best win save grow faster easy free better results works profit double".split())
STOP = set("""a an the and or but so of to in on at for with by from is it it's its that this these those your you my
we our just then than as if be are was were i me he she they them what when where who how why want show tell know
think going gonna get got have has had do does did can could will would should here there today now about into out up
down over all any some more very really thing things way time back""".split())


def norm(w: str) -> str:
    return re.sub(r"[^\w$%'€£]", "", w.lower())


def word_loudness(video: Path, words: list[dict]) -> np.ndarray:
    """RMS loudness (dBFS) of every word."""
    raw = subprocess.run([find_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(video), "-map", "0:a:0",
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    out = []
    for w in words:
        seg = a[int(w["start"] * 16000): max(int(w["start"] * 16000) + 160, int(w["end"] * 16000))]
        rms = float(np.sqrt(np.mean(seg * seg))) if seg.size else 0.0
        out.append(20 * np.log10(max(rms, 1e-5)))
    return np.array(out)


def keyword_runs(words: list[dict], keywords: list[str]) -> dict[int, tuple[int, int]]:
    """Where a multi-word keyword ("phone is enough") is said: every word index in it -> (first, last) index."""
    toks = [norm(w["word"]) for w in words]
    runs = {}
    for k in keywords:
        t = [norm(x) for x in k.split()]
        if len(t) > 1:
            for j in range(len(toks) - len(t) + 1):
                if toks[j:j + len(t)] == t:
                    runs.update({m: (j, j + len(t) - 1) for m in range(j, j + len(t))})
    return runs


def score_words(words: list[dict], loud: np.ndarray, keywords: list[str]) -> list[dict]:
    starts = np.array([w["start"] for w in words])
    per_char = np.array([(w["end"] - w["start"]) / max(1, len(norm(w["word"]))) for w in words])
    med_rate = float(np.median(per_char)) if len(per_char) else 0.07
    kw = [k.strip().lower() for k in keywords if k.strip()]
    in_phrase = keyword_runs(words, kw)
    scored = []
    for i, w in enumerate(words):
        n = norm(w["word"])
        reasons, s = [], 0.0
        window = (starts > w["start"] - 8) & (starts < w["start"] + 8)
        vocal = float(loud[i] - np.median(loud[window]))
        if vocal > 2.0 and n not in STOP:
            s += 1.2 * min(vocal, 8.0)
            reasons.append(f"said {vocal:.0f} dB louder")
        if per_char[i] > 1.6 * med_rate and len(n) > 2 and n not in STOP:
            s += 2.0
            reasons.append("stretched out")
        if i and w["start"] - words[i - 1]["end"] > 0.35 and n not in STOP:
            s += 1.5
            reasons.append("pause before it")
        if NUMBER.search(w["word"]):
            s += 4.0
            reasons.append("number")
        if n in ABSOLUTE:
            s += 2.5
            reasons.append("absolute word")
        if n in CONTRAST:
            s += 1.0
            reasons.append("contrast")
        prev = words[i - 1]["word"] if i else "."
        if w["word"][:1].isupper() and n != "i" and not prev.endswith((".", "?", "!")):
            s += 2.0
            reasons.append("name")
        if i in in_phrase or any(n == k or (len(k) > 3 and k in w["word"].lower()) for k in kw):
            s += 6.0
            reasons.append("your keyword")
        scored.append({"i": i, "score": s, "reasons": reasons})
    return scored


def build_phrase(words: list[dict], i: int, max_words: int = 4) -> tuple[int, int]:
    """Grow the moment around word i to a short phrase that stays inside one spoken phrase."""
    lo = hi = i

    def joined(a: int, b: int) -> bool:
        return words[b]["start"] - words[a]["end"] < 0.25 and \
            not words[a]["word"].endswith((",", ".", "?", "!", ";", ":"))
    # forward: take small words up to the next content word ("10x faster", "$500 a month")
    while hi + 1 < len(words) and hi - lo + 1 < max_words and joined(hi, hi + 1) and \
            (NUMBER.search(words[hi]["word"]) or norm(words[hi + 1]["word"]) not in STOP) and \
            norm(words[hi + 1]["word"]) not in CONTRAST:
        hi += 1
        if norm(words[hi]["word"]) not in STOP:
            break
    # backward: take content words right before it ("raw footage")
    while lo - 1 >= 0 and hi - lo + 1 < max_words and joined(lo - 1, lo) and \
            norm(words[lo - 1]["word"]) not in STOP and norm(words[lo - 1]["word"]) not in CONTRAST:
        lo -= 1
    return lo, hi


def suggest_style(text: str, reasons: list[str]) -> tuple[str, str]:
    ws = [norm(w) for w in text.split()]
    if NUMBER.search(text):
        return "slam", "teal"
    color = "red" if any(w in NEGATIVE for w in ws) else "green" if any(w in POSITIVE for w in ws) else "teal"
    if "name" in reasons or "your keyword" in reasons:
        return ("typewriter" if len(text) <= 28 else "highlight"), color
    if len(ws) == 1:
        return "pop", color
    return "highlight", color


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Find the moments that deserve kinetic text.")
    p.add_argument("video", type=Path)
    p.add_argument("--words", type=Path, help="word timings (default: transcribe now)")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.add_argument("--keywords", default="", help="comma-separated words or phrases you want emphasized")
    p.add_argument("--max", type=int, help="most moments to pick (default: about one per 12 s, at least 3)")
    p.add_argument("--min-gap", type=float, default=5.0, help="seconds between picked moments (default 5)")
    p.add_argument("--skip", default="", help="'start-end' windows where no moment may go, e.g. graphics: '3.2-27.6,30.6-33.1'")
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    root = project_root()
    video = args.video if args.video.exists() else root / "input" / args.video
    info = probe(video)
    from transcribe import load_words, transcribe_words
    if args.words:
        words = load_words(args.words)
    else:
        print(f"Transcribing {video.name} ('{args.model}' model)...", flush=True)
        words, _ = transcribe_words(video, args.model, args.language)
        wpath = root / "work" / f"{video.stem}.words.json"
        wpath.parent.mkdir(parents=True, exist_ok=True)
        wpath.write_text(json.dumps(words, indent=1), encoding="utf-8")
    if not words:
        print("No speech found.")
        return 1

    loud = word_loudness(video, words)
    keywords = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
    scored = sorted(score_words(words, loud, keywords), key=lambda x: -x["score"])
    runs = keyword_runs(words, keywords)
    limit = args.max or max(3, round(info.duration / 12))
    skip = [tuple(float(x) for x in w.split("-")) for w in args.skip.split(",") if w.strip()]
    candidates, used = [], set()
    for s in scored:
        if s["score"] < 2.5 or s["i"] in used:
            continue
        lo, hi = runs.get(s["i"]) or build_phrase(words, s["i"])   # a keyword phrase stays whole
        if any(words[lo]["start"] < b and words[hi]["end"] > a for a, b in skip):
            continue
        if any(k in used for k in range(lo, hi + 1)):
            continue
        used.update(range(lo, hi + 1))
        text = " ".join(w["word"].strip(",.;:") for w in words[lo:hi + 1])
        style, color = suggest_style(text, s["reasons"])
        candidates.append({"start": round(words[lo]["start"], 3), "end": round(words[hi]["end"], 3), "text": text,
                           "score": round(s["score"], 1), "reasons": s["reasons"], "style": style, "color": color})
        if len(candidates) >= limit * 3:
            break
    # keep the strongest, spaced apart (no clutter), then sort by time
    selected = []
    for c in sorted(candidates, key=lambda c: -c["score"]):
        if len(selected) >= limit:
            break
        if all(abs(c["start"] - s["start"]) >= args.min_gap for s in selected):
            selected.append(c)
    selected.sort(key=lambda c: c["start"])
    candidates.sort(key=lambda c: c["start"])
    out = args.out or root / "work" / f"{video.stem}.emphasis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"video": str(video), "duration": info.duration, "moments": selected,
                               "other_candidates": [c for c in candidates if c not in selected]}, indent=1),
                   encoding="utf-8")
    print(f"{len(selected)} moments picked (of {len(candidates)} candidates; max {limit}, at least "
          f"{args.min_gap:g}s apart):")
    for c in selected:
        print(f"  {fmt_time(c['start']):>7}  {c['style']:<10} {c['color']:<6} \"{c['text']}\"  ({', '.join(c['reasons'])})")
    print(f"Plan: {out}  (edit text/style/color or remove moments, then run build_kinetic.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
