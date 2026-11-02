#!/usr/bin/env python3
"""Re-listen to every join of the finished cut, so a clipped, missing or extra word is caught before the graphics.

After the cuts, the words are re-timed by arithmetic and nobody has heard the result. This takes about 1.5 s of
sound on each side of every join from the cut video (V) and transcribes only those snippets with the large-v3
speech model (local and free; the first run downloads it, about 3 GB, into tools/models/). The same model also
hears the uncut video around both edges of each cut, so what it hears at a join is compared with what the same
speech sounded like before the cut, not with another model's words. It also measures the sound right at each
join, because the model often finishes a cut-off word from context ("busi|" is heard as "business").

A word heard differently counts as a problem only when the cut goes through that word (the uncut video has its
sound on both sides of the edge), when an extra word sits on real sound next to the join, or when a mistake cut
leaves in a word the words file (W) says it takes out. Other differences are the model hearing the new context
differently; they are listed as notes. Problems and notes go to work/<name>.relisten.json. The exit code is 1 when
a problem is found, 2 when the input is wrong or the check could not run.

The joins come from the saved cut lists (see timemap.py), or from --joins. With --joins, or when the uncut video
is gone, the heard words are compared with W instead, and every difference counts.

  python relisten.py work/talk.clean.mp4 --words work/talk.mistakes-transcript.json
  python relisten.py work/talk.mp4 --words work/talk.words.json                  (only dead air was cut)
  python relisten.py work/talk.mp4 --words work/talk.words.json --joins "5.2,12.8"
  python relisten.py --self-test
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cut_dead_air import FADE  # noqa: E402
from timemap import TimeMap, load  # noqa: E402
from transcribe import join_number_parts, load_words  # noqa: E402  (importing it also quiets the model downloader)
from vtools import MediaInfo, find_tool, fmt_time, probe, project_root, run  # noqa: E402

RATE = 16000    # the speech model hears 16 kHz mono
SIDE = 1.5      # seconds of sound taken on each side of a join
NEAR = 0.6      # only differences this close to a join count: the model garbles a snippet's outer words
# A cut through a word stays loud right up to the cut. A cut in a pause or between words sits in a dip, and a lone
# click or bump is a single 10 ms frame. So the HOLD frames just outside the fade must all be within LOUD dB of the
# snippet's speech, FLOOR dB above its floor (room tone, a music bed), and DIP dB of the loudest frame in the
# REACH seconds beside the cut. Measured on two real reels and computer speech: 3-5% of real between-word cuts at
# step 1's quietest points pass all three, against 73% of cuts at a word's loudest point.
LOUD, FLOOR, DIP, HOLD, REACH = 12.0, 15.0, 5.0, 2, 0.15
PAD = 0.5       # seconds of the cut-away part heard with each edge in the uncut video, so a word it crosses is whole
EDGE = 0.3      # how far into a word on each side of an edge its sound is looked for
KEPT = 0.1      # on the kept side, only this close: a word's time often starts inside the last word's tail
TOUCH = 0.15    # how far a word's time may stop short of its sound: it reaches this far into the silence beside it
WORD_HOLD = 3   # 10 ms frames at speech level (LOUD and FLOOR above) on a side of an edge that make a word's sound
ADDED_HOLD = 5  # an extra word is real sound when 50 ms of it is at speech level (LOUD and FLOOR above)
GAP = 1.0       # seconds of silence between snippets that share one listening pass
PASS = 28.0     # the model always hears 30 s at once, so short snippets share a pass instead of padding each
FILLERS = {"uh", "um", "umm", "uhm", "hmm", "mm", "mhm", "ah", "er", "erm", "eh"}
NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                      "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
NUMBERS.update({w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)})
# Spanish, written without accents (split_word drops them). "y" joins a number like "and": "treinta y cinco".
NUMBERS.update({w: i for i, w in enumerate("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
                                           "catorce quince dieciseis diecisiete dieciocho diecinueve veinte veintiuno "
                                           "veintidos veintitres veinticuatro veinticinco veintiseis veintisiete "
                                           "veintiocho veintinueve".split())})
NUMBERS.update({"un": 1, "una": 1, "veintiun": 21, "veintiuna": 21, "cien": 100, "ciento": 100})
NUMBERS.update({w: 10 * i for i, w in
                enumerate("treinta cuarenta cincuenta sesenta setenta ochenta noventa".split(), 3)})
NUMBERS.update({w: 100 * i for i, w in enumerate("doscientos trescientos cuatrocientos quinientos seiscientos "
                                                 "setecientos ochocientos novecientos".split(), 2)})
NUMBERS.update({w[:-2] + "as": v for w, v in list(NUMBERS.items()) if w.endswith("ientos")})
SCALES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9,
          "mil": 1000, "millon": 10 ** 6, "millones": 10 ** 6}
SCALE_OF = {"k": "thousand", "m": "million", "b": "billion", "bn": "billion"}
# The two models spell the same speech differently; both sides are written one way before comparing.
SAME = {"ok": "okay", "alright": "all right", "gonna": "going to", "wanna": "want to", "gotta": "got to",
        "kinda": "kind of", "sorta": "sort of", "lemme": "let me", "gimme": "give me", "cannot": "can not",
        "can't": "can not", "won't": "will not"}
SAME.update(zip("1st 2nd 3rd 4th 5th 6th 7th 8th 9th 10th 11th 12th".split(),   # shortcut: ordinals to 12th
                "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split()))
CONTRACTIONS = (("n't", " not"), ("'re", " are"), ("'ll", " will"), ("'ve", " have"), ("'m", " am"),
                ("'d", " would"), ("'s", " is"))


# ----------------------------------------------------------------------------- comparing words

def split_word(raw: str) -> list[str]:
    """One written word as comparable pieces: lower case, no punctuation, and amounts, contractions and common
    spellings written one way ("OK" / "okay", "it's" / "it is", "$1.5M" / "1.5 million dollars", "sí" / "si")."""
    w = unicodedata.normalize("NFKD", raw.lower().replace("’", "'"))
    w = "".join(c for c in w if not unicodedata.combining(c))
    w = re.sub(r"\bo\.k\b\.?", "ok", w)
    w = re.sub(r"(?<=\d),(?=\d)", "", w)                                              # 10,000 -> 10000
    w = re.sub(r"(\d[\d.]*)(k|m|bn|b)\b", lambda m: f"{m[1]} {SCALE_OF[m[2]]}", w)    # 10k, 1.5M
    w = re.sub(r"\$(\d[\d.]*(?: (?:thousand|million|billion))?)", r"\1 dollars", w)   # $10 -> 10 dollars
    w = w.replace("%", " percent").replace("&", " and ")
    out = []
    for t in re.sub(r"[^\w.']+|(?<!\d)\.|\.(?!\d)", " ", w).split():                 # keeps 2.5, drops the rest
        t = SAME.get(t.strip("'"), t.strip("'"))
        for short, full in CONTRACTIONS:
            if t.endswith(short):
                t = t[:-len(short)] + full
                break
        out += t.replace("'", "").split()
    return out


def number(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def tokens(words: list[dict]) -> list[list]:
    """Comparable tokens: [text, start, end, first word index, last word index, written as cut off ("busi-"),
    the piece as written]. Spoken numbers become digits ("twenty one" -> "21"), so both models' ways of
    writing them compare equal."""
    flat = [[t, w["start"], w["end"], i, i, w["word"].endswith("-"), t]
            for i, w in enumerate(words) for t in split_word(w["word"]) if t not in FILLERS]
    out: list[list] = []
    run_, total, cur = [], 0, 0

    def close():
        nonlocal run_, total, cur
        if run_:
            out.append([number(total + cur), run_[0][1], run_[-1][2], run_[0][3], run_[-1][4], False,
                        " ".join(t[6] for t in run_)])
        run_, total, cur = [], 0, 0

    def fits(n):    # "twenty" then "one" is one number; "twenty twenty" and "two and three" are two
        return cur % 100 == 0 or (cur % 100 >= 20 and cur % 10 == 0 and n < 10)

    for k, tok in enumerate(flat):
        t, nxt = tok[0], flat[k + 1][0] if k + 1 < len(flat) else ""
        if t in NUMBERS:
            if run_ and not fits(NUMBERS[t]):
                close()
            cur += NUMBERS[t]
        elif t in SCALES:
            if SCALES[t] == 100:
                cur = (cur or 1) * 100
            else:
                total, cur = total + (cur or 1) * SCALES[t], 0
        elif re.fullmatch(r"\d+(?:\.\d+)?", t) and not run_ and nxt in SCALES:
            cur = float(t)                               # "5 million", "1.5 thousand"
        elif not (t in ("and", "y") and run_ and nxt in NUMBERS and fits(NUMBERS[nxt])):   # "a hundred and five"
            close()
            out.append(tok)
            continue
        run_.append(tok)
    close()
    return out


def fragment(said: str, heard: str) -> bool:
    """`heard` sounds like a piece of `said`: "star" for "started", "busy" for "business", "ery" for "every"."""
    if len(heard) >= len(said):
        return False
    need = max(2, len(heard) - 1)
    return (len(os.path.commonprefix([said, heard])) >= need
            or len(os.path.commonprefix([said[::-1], heard[::-1]])) >= need)


def split_replace(E: list, H: list) -> list[tuple[list, list]]:
    """Line the shorter side up with the most alike run of the longer one, word for word. The rest of the
    longer side is added or missing: "cool three" for "free" is "cool" added and "three" for "free"."""
    flip = len(E) > len(H)
    a, b = (H, E) if flip else (E, H)
    n = len(a)
    k = max(range(len(b) - n + 1),        # alike as written: "three" is "3" once numbers are digits
            key=lambda k: sum(difflib.SequenceMatcher(None, x[6], y[6]).ratio() for x, y in zip(a, b[k:k + n])))
    parts = ([([], b[:k])] if k else []) + [([x], [y]) for x, y in zip(a, b[k:k + n])] + \
            ([([], b[k + n:])] if b[k + n:] else [])
    return [(q, p) if flip else (p, q) for p, q in parts]


def align(e: list[list], h: list[list]) -> list[tuple[list, list]]:
    """The two token lists lined up: (expected run, heard run) pairs, equal runs included."""
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [t[0] for t in e], [t[0] for t in h],
                                                       autojunk=False).get_opcodes():
        if op == "equal" or "".join(t[0] for t in e[i1:i2]) == "".join(t[0] for t in h[j1:j2]):
            out.append((e[i1:i2], h[j1:j2], True))       # same words written differently: "follow-up" / "follow up"
        else:
            out += [(E, H, False) for E, H in
                    (split_replace(e[i1:i2], h[j1:j2]) if op == "replace" else [(e[i1:i2], h[j1:j2])])]
    return out


def judge(said: list[dict], heard: list[dict], joins: list[float], src: str = "the words") -> list[dict]:
    """Differences between the expected and the heard words of one snippet that sit at one of its joins. Each
    also says whether the cut goes through an expected word ("cut", set on the uncut video's words), and where
    the heard words are ("span"), for review() to weigh."""
    found = []
    for E, H, same in align(tokens(said), tokens(heard)):
        if same:
            continue
        a, b = (E or H)[0][1], (E or H)[-1][2]
        j = min(joins, key=lambda x: max(a - x, x - b, 0.0))
        if max(a - j, j - b, 0.0) > NEAR:
            continue                                     # a garbled snippet edge, or the models hearing it differently
        exp = said[E[0][3]:E[-1][4] + 1] if E else []
        j = next((w["cut_at"] for w in exp if "cut_at" in w), j)    # the join whose edge goes through the word
        got = " ".join(w["word"] for w in heard[H[0][3]:H[-1][4] + 1]) if H else ""
        say = " ".join(w["word"] for w in exp)
        dash = any(t[5] for t in H)
        if not H:
            kind, text = "missing", f'"{say}" is not heard'
        elif dash or any(fragment(x[0], y[0]) for x in E for y in H):
            kind, text = "clipped", f'heard "{got}"' + (f' where {src} {"say" if src == "the words" else "has"} '
                                                         f'"{say}"' if say else ", a cut-off word")
        elif not E:
            kind, text = "added", f'heard "{got}", which {src} {"do" if src == "the words" else "does"} not have'
        else:
            kind, text = "changed", f'heard "{got}" where {src} {"say" if src == "the words" else "has"} "{say}"'
        found.append({"join": j, "time": a, "kind": kind, "said": say, "heard": got, "text": text,
                      "cut": any(w.get("cut") for w in exp), "span": [H[0][1], H[-1][2]] if H else None,
                      "dash": dash, "words": range(E[0][3], E[-1][4] + 1) if E else range(0)})
    return found


def left_in(ref: list[dict], said: list[dict], heard: list[dict], joins: list[float]) -> list[dict]:
    """Words a mistake cut was meant to take out but that are still heard: in the uncut video's kept sound,
    missing from W, between the join and the nearest word W has (so not W mishearing a word further away), and
    heard in the cut, whole ("added") or as another word (the cut goes through it, "clipped")."""
    r = tokens(ref)
    in_w = {id(t) for E, W, same in align(r, tokens(said)) if same or (E and W) for t in E}
    as_h = {}                                            # each uncut-video token -> the heard tokens it lines up with
    for E, H, same in align(r, tokens(heard)):
        if same and len(E) == len(H):
            as_h.update((id(e), [h]) for e, h in zip(E, H))
        elif E and H and len(E) == 1:
            as_h[id(E[0])] = H
    found = []
    for j in joins:
        for side in (sorted((t for t in r if (t[1] + t[2]) / 2 >= j), key=lambda t: t[1]),
                     sorted((t for t in r if (t[1] + t[2]) / 2 < j), key=lambda t: -t[2])):
            for t in side:
                if id(t) in in_w or max(t[1] - j, j - t[2], 0.0) > NEAR:
                    break
                if id(t) not in as_h:
                    continue
                word = " ".join(w["word"] for w in ref[t[3]:t[4] + 1])
                H = as_h[id(t)]
                got = " ".join(w["word"] for w in heard[H[0][3]:H[-1][4] + 1])
                whole = [x[0] for x in tokens([{"word": got, "start": 0, "end": 0}])] == [t[0]]
                found.append({"join": j, "time": t[1], "kind": "added" if whole else "clipped", "said": word,
                              "heard": got, "sure": True, "words": range(t[3], t[4] + 1),
                              "text": f'heard "{got}", which the words leave out: part of what this cut takes out '
                                      "is still there" if whole else
                                      f'heard "{got}" where the uncut video has "{word}", which the words leave '
                                      "out: this cut goes through it"})
    return found


# ----------------------------------------------------------------------------- the sound at the join

def db(x: np.ndarray) -> float:
    return 20.0 * float(np.log10(max(float(np.sqrt(np.mean(x * x))) if x.size else 0.0, 1e-5)))


def side_word(words: list[dict], j: float, side: str) -> tuple[str, float]:
    """The nearest word within NEAR on one side of the cut (by its middle: word times run a little early or late),
    and how far its edge is from the cut."""
    if side == "end":
        near = [w for w in words if (w["start"] + w["end"]) / 2 <= j and j - w["end"] <= NEAR]
        return (near[-1]["word"], j - near[-1]["end"]) if near else ("", 0.0)
    near = [w for w in words if (w["start"] + w["end"]) / 2 > j and w["start"] - j <= NEAR]
    return (near[0]["word"], near[0]["start"] - j) if near else ("", 0.0)


def sound_at_joins(x: np.ndarray, start: float, joins: list[float], said: list[dict],
                   heard: list[dict] = ()) -> list[dict]:
    """Joins where a word's sound is still going at the cut, measured just outside the cutters' 8 ms fade
    (see LOUD, FLOOR, DIP and HOLD). The word is named as heard: W leaves out every word a mistake cut touches."""
    levels = [db(f) for f in x[: x.size // 160 * 160].reshape(-1, 160)] or [-100.0]
    speech, floor = float(np.percentile(levels, 95)), float(np.percentile(levels, 10))
    found = []
    for j in joins:
        for side, first, step in (("end", j - FADE - 0.01, -0.01), ("start", j + FADE, 0.01)):
            near = []                                    # 10 ms frames moving away from the cut
            for k in range(round(REACH / 0.01)):
                i = round((first + k * step - start) * RATE)
                if not 0 <= i <= x.size - 160:
                    break
                near.append(db(x[i:i + 160]))
            if len(near) < HOLD or min(near[:HOLD]) < max(speech - LOUD, floor + FLOOR, max(near) - DIP):
                continue
            (got, gap), (exp, gap_w) = side_word(heard, j, side), side_word(said, j, side)
            word, gap = (got, gap) if got else (exp, gap_w)
            what = (f"a sound right {'before' if side == 'end' else 'after'} it" if not word else
                    f'the {side} of "{word}"' if gap <= 0.1 else       # the word reaches the cut
                    f'a word between "{word}" and the cut' if side == "end" else
                    f'a word between the cut and "{word}"')            # a piece nobody heard as a word
            found.append({"join": j, "time": j, "kind": "clipped", "said": exp, "heard": got,
                          "text": f"the sound is still going at the cut, so {what} may be cut off",
                          "under_speech_db": round(speech - min(near[:HOLD]), 1)})
    return found


def levels(x: np.ndarray) -> np.ndarray:
    """10 ms levels in dB."""
    f = x[: x.size // 160 * 160].reshape(-1, 160)
    return 20.0 * np.log10(np.maximum(np.sqrt((f * f).mean(axis=1)), 1e-5)) if f.size else np.array([-100.0])


def frames_over(x: np.ndarray, start: float, a: float, b: float, line: float) -> int:
    """How many 10 ms frames of x (which starts at `start` seconds) between a and b are at `line` dB or more."""
    i, k = max(0, round((a - start) * RATE)), max(0, round((b - start) * RATE))
    return int((levels(x[i:k]) >= line).sum()) if k - i >= 160 else 0


def reference(words: list[dict], tm: TimeMap, joins: list[float], sound) -> list[dict]:
    """The uncut video's words around these joins, in cut time. A word an edge goes through keeps its kept part,
    and is marked "cut" when its sound is on both sides of the edge (on the kept side, right next to it: the
    model often starts a word inside the last word's tail). A word whose sound near the edge is all on the
    cut-away side is left out. One with no sound near the edge on either side (a soft word, or a pause the
    model's word time runs into) keeps its kept part. The model's word times can stop short of a word's last
    sound ("-ly" of "Honestly"), so a word may reach up to TOUCH seconds into the silence after it at the end of
    a kept piece, and before it at the start of one (never past a neighbour)."""
    edges = []                      # (join, edge, is_end, kept side within KEPT, cut-away side within EDGE seconds)
    for j in joins:
        e1, s2 = tm.to_source(j, end=True), tm.to_source(j)
        a = max((p for p, q in tm.keeps if q <= e1 + 1e-6), default=0.0)       # the kept piece ending at e1
        b = min((q for p, q in tm.keeps if p >= s2 - 1e-6), default=s2)       # the kept piece starting at s2
        edges += [(j, e1, True, (max(a, e1 - KEPT), e1), (e1, min(s2, e1 + EDGE))),
                  (j, s2, False, (s2, min(b, s2 + KEPT)), (max(e1, s2 - EDGE), s2))]
    words = sorted(words, key=lambda w: w["start"])
    out = []
    for k, w in enumerate(words):
        lo = max(w["start"] - TOUCH, words[k - 1]["end"] if k else -1.0)
        hi = min(w["end"] + TOUCH, words[k + 1]["start"] if k + 1 < len(words) else w["end"] + TOUCH)
        crossed = []                                     # (join, is_end, sound on the kept side, on the cut-away side)
        for j, e, is_end, (k0, k1), (c0, c1) in edges:
            a, b = (w["start"], max(hi, w["end"])) if is_end else (min(lo, w["start"]), w["end"])
            if a < e < b:
                crossed.append((j, is_end, sound(max(a, k0), min(b, k1)), sound(max(a, c0), min(b, c1))))
        mid = tm.to_cut((w["start"] + w["end"]) / 2)
        here, gone = any(c[2] for c in crossed), any(c[3] for c in crossed)
        if (gone and not here) or (not crossed and mid is None):
            continue
        s, e = tm.to_cut(w["start"]), tm.to_cut(w["end"])
        s = s if s is not None else next((j for j, is_end, *_ in crossed if not is_end), mid)
        e = e if e is not None else next((j for j, is_end, *_ in crossed if is_end), mid)
        if s is not None and e is not None:
            at = [j for j, _, kept, gone in crossed if kept and gone]
            out.append({**w, "start": s, "end": e, "cut": bool(at), **({"cut_at": at[0]} if at else {})})
    return sorted(out, key=lambda w: w["start"])


def review(start: float, joins: list[float], x: np.ndarray, said: list[dict], heard: list[dict],
           ref: list[dict] | None = None, mistake_joins=()) -> list[dict]:
    """Every problem at the joins of one snippet, each marked "sure" or not. Without `ref` (the uncut video's
    words), every difference from W is sure. With it, a difference is sure when the cut goes through the word, or
    when an extra or cut-off word sits on real sound; a mistake cut that leaves in a word W leaves out is sure too.
    The rest is the model hearing the new context differently."""
    expected = said if ref is None else ref
    if expected and not heard:          # the model heard nothing at all: its failure, not the cut's
        found = [{"join": j, "time": j, "kind": "unheard", "said": "", "heard": "", "sure": True,
                  "text": "the speech model heard nothing around this join, so its words are not checked"}
                 for j in joins]
    else:
        found = judge(expected, heard, joins, "the words" if ref is None else "the uncut video")
    lv = levels(x)
    line = max(float(np.percentile(lv, 95)) - LOUD, float(np.percentile(lv, 10)) + FLOOR)
    for f in found:
        span = f.pop("span", None)
        if "sure" not in f:
            f["sure"] = ref is None or f["cut"] or bool(
                span and (f["kind"] == "added" or f["dash"]) and frames_over(x, start, *span, line) >= ADDED_HOLD)
        f.pop("cut", None), f.pop("dash", None)
    if ref is not None and heard:
        extra = left_in(ref, said, heard, [j for j in joins if j in mistake_joins])
        taken = {i for f in extra for i in f["words"]}
        found = [f for f in found if not taken & set(f["words"])] + extra      # one line per word
    for f in found:
        f.pop("words", None)
    return found + [{**f, "sure": True} for f in sound_at_joins(x, start, joins, expected, heard)]


# ----------------------------------------------------------------------------- listening

def merge(spans) -> list[list]:
    """[start, end, [tags]] from (start, end, tag) spans, the overlapping ones merged."""
    out: list[list] = []
    for a, b, tag in sorted(spans, key=lambda s: s[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2] += [tag] if tag not in out[-1][2] else []
        else:
            out.append([a, b, [tag]])
    return out


def windows(joins: list[float], duration: float) -> list[list]:
    """[start, end, [joins]]: SIDE seconds of sound around each join, overlapping ones merged."""
    return merge((max(0.0, j - SIDE), min(duration, j + SIDE), j) for j in joins)


def edge_windows(tm: TimeMap, joins: list[float], duration: float) -> list[list]:
    """[start, end, [joins]] in the uncut video: SIDE seconds of what each cut keeps and PAD of what it takes out,
    at both edges of each join."""
    spans = []
    for j in joins:
        e1, s2 = tm.to_source(j, end=True), tm.to_source(j)
        spans += [(max(0.0, e1 - SIDE), min(duration, e1 + PAD), j), (max(0.0, s2 - PAD), min(duration, s2 + SIDE), j)]
    return merge(spans)


def snippets(info: MediaInfo, spans: list) -> list[np.ndarray]:
    """The sound of each (start, end, ...) span of the video, as 16 kHz mono samples.
    The sound is decoded once and sliced: seeking with -ss to 0 s in the cutters' mp4s lands one AAC frame early."""
    cmd = [find_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(info.path), "-map", "0:a:0", "-ac", "1",
           "-ar", str(RATE), "-f", "s16le", "-"]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"could not read the sound of {info.path.name}: "
                           f"{res.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    pcm = np.frombuffer(res.stdout, dtype="<i2")
    offset = max(0.0, info.audio_start - info.format_start)       # sample 0 is where the sound track starts
    return [pcm[max(0, round((a - offset) * RATE)):max(0, round((b - offset) * RATE))].astype(np.float32) / 32768.0
            for a, b, *_ in spans]


def listen(model, clips: list[np.ndarray], language: str | None = None) -> list[list[dict]]:
    """Each snippet's words, timed from the snippet's start. Snippets share a pass, a second of silence apart."""
    heard: list[list[dict]] = [[] for _ in clips]
    gap = np.zeros(int(GAP * RATE), dtype=np.float32)
    i = 0
    while i < len(clips):
        parts, starts, t = [], [], 0.0
        while i < len(clips) and (not parts or t + len(clips[i]) / RATE <= PASS):
            starts.append((i, t))
            parts += [clips[i], gap]
            t += len(clips[i]) / RATE + GAP
            i += 1
        segs, _ = model.transcribe(np.concatenate(parts), language=language, vad_filter=True, word_timestamps=True)
        words = join_number_parts([{"start": float(w.start), "end": float(w.end), "word": w.word.strip()}
                                   for s in segs for w in (s.words or []) if w.word.strip()])
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            k, off = next(((k, off) for k, off in reversed(starts) if mid >= off), starts[0])
            if mid <= off + len(clips[k]) / RATE:      # a word heard in the silence between snippets is dropped
                heard[k].append({**w, "start": max(0.0, w["start"] - off), "end": w["end"] - off})
    return heard


def hear(model, wins: list, clips: list[np.ndarray], saids: list[list[dict]],
         language: str | None = None, video: str = "") -> list[list[dict]]:
    """Each snippet's heard words in the video's time. A pass can stop early, at a join the model can't make sense
    of, and skip the rest of the pass. So when the words file still has speech well after the last word heard,
    the rest of that snippet is heard again on its own."""
    out = []
    for (a, _, _), x, said, heard in zip(wins, clips, saids, listen(model, clips, language)):
        heard = [{**w, "start": w["start"] + a, "end": w["end"] + a} for w in heard]
        stop = max((w["end"] for w in heard), default=a)
        if sum(w["start"] > stop + 0.5 for w in said) >= 2:
            s = max(a, stop - 0.1)
            print(f"  The model stopped listening at {fmt_time(stop)}{' of ' + video if video else ''}; "
                  "hearing the rest of that part again...", flush=True)
            heard += [{**w, "start": w["start"] + s, "end": w["end"] + s}
                      for w in listen(model, [x[round((s - a) * RATE):]], language)[0] if w["start"] + s >= stop - 0.05]
        out.append(heard)
    return out


# ----------------------------------------------------------------------------- which cut, which name

def guess_name(video: Path, work: Path) -> str:
    """work/talk.clean.mp4 -> "talk": the longest front part of the file name that has saved cut lists."""
    parts = video.stem.split(".")
    for k in range(len(parts), 0, -1):
        name = ".".join(parts[:k])
        if (work / "reports" / f"{name}.json").is_file() or (work / f"{name}.mistakes-edl.json").is_file():
            return name
    return video.stem


def cut_names(name: str, work: Path, joins: list[float]) -> dict[float, str]:
    """Which cut made each join. A mistake cut is named by its range in work/<name>.mp4's seconds,
    the times work/<name>.approved-cuts.json uses."""
    edl = work / f"{name}.mistakes-edl.json"
    later = TimeMap([(k["start"], k["end"]) for k in json.loads(edl.read_text(encoding="utf-8"))["keep_ranges"]]) \
        if edl.is_file() else None
    mistake_joins = later.joins() if later else []
    out = {}
    for j in joins:
        if any(abs(j - x) < 0.002 for x in mistake_joins):
            out[j] = f"mistake cut {later.to_source(j, end=True):.2f}-{later.to_source(j):.2f}"
        else:
            out[j] = "dead-air cut"
    return out


def source_of(name: str, work: Path, root: Path | None = None) -> Path | None:
    """The uncut video the saved cut lists start from: the dead-air cut's source, or work/<name>.mp4 when only
    mistakes were cut. None when it is gone. The report keeps the path it was given, often absolute: after the
    project folder moved, the same folder and file name in this project count (as cut_dead_air reads its report)."""
    root = root or project_root()
    report = work / "reports" / f"{name}.json"
    if report.is_file():
        src = json.loads(report.read_text(encoding="utf-8")).get("source")
        if not src:
            return None
        return next((c for c in (root / src, root / Path(src).parent.name / Path(src).name) if c.is_file()), None)
    return work / f"{name}.mp4" if (work / f"{name}.mp4").is_file() else None


# ----------------------------------------------------------------------------- main flow

def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Re-listen to every join of a cut video (local, free).")
    p.add_argument("video", nargs="?", type=Path, help="the cut video, e.g. work/talk.clean.mp4")
    p.add_argument("--words", type=Path, help="the words in the cut's time: work/<name>.mistakes-transcript.json, "
                                              "or work/<name>.words.json when only dead air was cut")
    p.add_argument("--joins", help='join times in seconds of the cut video, e.g. "5.2,12.8" '
                                   "(default: from the saved cut lists)")
    p.add_argument("--name", help="the video's name in work/ (default: from the file name)")
    p.add_argument("--model", default="large-v3", help="speech model (default large-v3)")
    p.add_argument("--language", help="language code such as en or es (default: detect)")
    p.add_argument("--work", type=Path, help="the work folder (default: work/ in the project)")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.video or not args.words:
        p.error("give the cut video and --words, or --self-test")
    try:
        return check(args)
    except Exception as e:  # a plain message for the owner, not a traceback
        print(f"Could not re-listen: {e}")
        return 2


def check(args) -> int:
    for f in (args.video, args.words):
        if not f.is_file():
            print(f"Not found: {f}")
            return 2
    root = project_root()
    work = (args.work or root / "work").resolve()
    if work.is_relative_to((root / "input").resolve()):
        print("Refusing to write into input/: that folder is only for the original videos.")
        return 2
    info = probe(args.video)
    if not info.has_audio:
        print(f"{args.video.name} has no sound, so there is nothing to listen to.")
        return 2
    name = args.name or guess_name(args.video, work)
    try:
        said_all = load_words(args.words)
    except (ValueError, KeyError, TypeError, AttributeError):
        print(f"{args.words.name} is not a words file. Pass work/<name>.mistakes-transcript.json, "
              "or work/<name>.words.json when only dead air was cut.")
        return 2
    if said_all and said_all[-1]["end"] > info.duration + 0.5:
        print(f"The words in {args.words.name} run to {fmt_time(said_all[-1]['end'])}, past the end of "
              f"{args.video.name} ({fmt_time(info.duration)}). Pass the words file of this cut.")
        return 2
    if args.joins is not None:
        try:
            joins, cuts = sorted(float(x) for x in args.joins.split(",") if x.strip()), {}
        except ValueError:
            joins = []
        if not joins or not all(0 < j < info.duration for j in joins):
            print(f'--joins takes times in seconds inside the video ({info.duration:.1f} s long), e.g. "5.2,12.8"')
            return 2
    else:
        try:
            m = load(name, work)
        except FileNotFoundError:
            print(f"No saved cut lists for {name!r} in {work}. Pass --name <name>, or the join times with --joins.")
            return 2
        if abs(m.duration - info.duration) > 0.5:
            r = work / "reports" / f"{name}.json"
            dead = json.loads(r.read_text(encoding="utf-8")).get("duration_after") if r.is_file() else None
            if dead and abs(dead - info.duration) <= 0.5 and (work / f"{name}.mistakes-edl.json").is_file():
                print(f"{args.video.name} is the cut from before the mistake cuts. Re-listen to the mistake cut: "
                      f"work/{name}.clean.mp4 --words work/{name}.mistakes-transcript.json")
            else:
                print(f"The saved cut lists describe a {fmt_time(m.duration)} cut, but {args.video.name} is "
                      f"{fmt_time(info.duration)} long. Is a cut list from an older run still in {work.name}/? "
                      "Pass the join times with --joins.")
            return 2
        joins = m.joins()
        cuts = cut_names(name, work, joins)

    out = work / f"{name}.relisten.json"
    report = {"video": str(args.video), "words": str(args.words), "model": args.model,
              "joins": [round(j, 3) for j in joins], "duration": round(info.duration, 3)}
    if not joins:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({**report, "heard_seconds": 0, "snippets": [], "findings": [], "notes": []},
                                  indent=1), encoding="utf-8")
        print("There are no joins to listen to (nothing was cut, or only the start or end was trimmed).")
        return 0
    src = None
    if args.joins is None:
        src = source_of(name, work)
        if src is None:
            print(f"The uncut video of {name!r} is gone, so the heard words are compared with {args.words.name}, "
                  "and a word it misheard can show up as a problem.")
    report["compared_with"] = str(src) if src else str(args.words)

    wins = windows(joins, info.duration)
    heard_s = sum(b - a for a, b, _ in wins)
    print(f"Re-listening to {len(joins)} join(s) in {args.video.name}: {heard_s:.1f} s around them, of the "
          f"{info.duration:.1f} s video, with the '{args.model}' speech model...", flush=True)
    t0 = time.time()
    clips = snippets(info, wins)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is missing. Use the project's Python in .venv, or run the setup (see README.md).")
        return 2
    models = project_root() / "tools" / "models"
    if not (models / f"models--Systran--faster-whisper-{args.model}").is_dir():
        print(f"The '{args.model}' speech model is not in tools/models/ yet: downloading it once "
              "(about 3 GB for large-v3), which can take a while...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8",   # the settings transcribe.py uses
                         download_root=str(models))
    saids = [[w for w in said_all if a <= (w["start"] + w["end"]) / 2 <= b] for a, b, _ in wins]
    heards = hear(model, wins, clips, saids, args.language, args.video.name)
    refs = [None] * len(wins)
    if src:
        src_info = probe(src)
        rwins = edge_windows(m, joins, src_info.duration)
        report["uncut_heard_seconds"] = round(sum(b - a for a, b, _ in rwins), 3)
        print(f"Hearing the same places in the uncut video {src.name} ({report['uncut_heard_seconds']:.1f} s), "
              "to compare with...", flush=True)
        rclips = snippets(src_info, rwins)
        lines = [max(np.percentile(lv, 95) - LOUD, np.percentile(lv, 10) + FLOOR) for lv in map(levels, rclips)]

        def sound(a: float, b: float) -> bool:      # speech-level sound in the uncut video between a and b
            return any(wa <= a <= wb and frames_over(x, wa, a, b, line) >= WORD_HOLD
                       for (wa, wb, _), x, line in zip(rwins, rclips, lines))
        in_src = [{**w, "start": m.to_source(w["start"]), "end": m.to_source(w["end"], end=True)} for w in said_all]
        rheards = hear(model, rwins, rclips, [[w for w in in_src if a <= (w["start"] + w["end"]) / 2 <= b]
                                              for a, b, _ in rwins], args.language, src.name)
        for k, (a, b, js) in enumerate(wins):
            words = [w for (_, _, rjs), ws in zip(rwins, rheards) if set(rjs) & set(js) for w in ws]
            ref = [w for w in reference(words, m, js, sound) if a <= (w["start"] + w["end"]) / 2 <= b]
            refs[k] = ref or None                   # the model heard nothing there: compare with W

    findings, heard_spans = [], []
    mistake_joins = {j for j, c in cuts.items() if c.startswith("mistake")}
    for (a, b, js), x, said, heard, ref in zip(wins, clips, saids, heards, refs):
        findings += review(a, js, x, said, heard, ref, mistake_joins)
        heard_spans.append({"start": round(a, 3), "end": round(b, 3), "joins": [round(j, 3) for j in js],
                            "said": " ".join(w["word"] for w in said), "heard": " ".join(w["word"] for w in heard)}
                           | ({"uncut": " ".join(w["word"] + ("|" if w["cut"] else "") for w in ref)} if ref else {}))
    findings.sort(key=lambda f: (f["join"], f["time"]))
    for f in findings:
        f["cut"] = cuts.get(f["join"], "")
        f["join"], f["time"] = round(f["join"], 3), round(f["time"], 3)
    sure = [f.pop("sure") for f in findings]
    findings, notes = [f for f, s in zip(findings, sure) if s], [f for f, s in zip(findings, sure) if not s]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**report, "heard_seconds": round(heard_s, 3), "snippets": heard_spans,
                               "findings": findings, "notes": notes}, indent=1), encoding="utf-8")

    def show(f):
        where = f" ({f['cut']})" if f["cut"] else ""
        when = f" (at {fmt_time(f['time'])})" if abs(f["time"] - f["join"]) >= 0.05 else ""
        print(f"  join at {fmt_time(f['join'])}{where}: {f['kind']}: {f['text']}{when}")
    if notes:
        print("Notes, nothing to change (heard differently after the cut, but the cut does not go through these "
              "words):")
        for f in notes:
            show(f)
    if findings:
        print("Problems:")
    for f in findings:
        show(f)
    bad = len({f["join"] for f in findings})
    if findings:
        print(f"Found {len(findings)} problem(s) at {bad} of {len(joins)} joins ({time.time() - t0:.0f} s). "
              f"Details: {out}")
        return 1
    print(f"Every join sounds right ({len(joins)} checked, {time.time() - t0:.0f} s). Saved {out}")
    return 0


def self_test() -> int:
    def w(word, s, e):
        return {"word": word, "start": s, "end": e}

    def toks(text):
        return [t[0] for t in tokens([w(x, i, i + 0.5) for i, x in enumerate(text.split())])]

    assert windows([5.0, 1.0, 6.0], 6.5) == [[0.0, 2.5, [1.0]], [3.5, 6.5, [5.0, 6.0]]]
    assert toks("It's 10,000 dollars, $5 and 87%!") == ["it", "is", "10000", "dollars", "5", "dollars", "and", "87",
                                                         "percent"]
    assert toks("ten thousand") == ["10000"] and toks("two hundred and five") == ["205"] == toks("205")
    assert toks("twenty twenty") == ["20", "20"] and toks("Twenty-one") == ["21"] and toks("5 million") == ["5000000"]
    assert toks("um so uh 10k") == ["so", "10000"] and toks("rock and roll") == ["rock", "and", "roll"]
    for a, b in (("OK, it's alright", "okay it is all right"), ("I'm gonna", "I am going to"), ("don't", "do not"),
                 ("can't", "cannot"), ("the 1st", "the first"), ("$1.5M", "1.5 million dollars"),
                 ("fifteen hundred", "1,500"), ("1.5k", "1500"), ("O.K.", "okay"), ("we’re", "we are"),
                 ("Tengo veinte años", "tengo 20 anos"), ("sí, también", "si tambien"), ("mil quinientos", "1500"),
                 ("treinta y cinco", "35"), ("doscientas", "200"), ("dos mil veinte", "2020"),
                 ("un millón", "1000000")):
        assert toks(a) == toks(b), (a, b, toks(a), toks(b))
    assert toks("two and three") == ["2", "and", "3"] and toks("dos y tres") == ["2", "y", "3"]
    assert fragment("started", "star") and fragment("business", "busy") and fragment("every", "ery")
    assert not fragment("then", "than") and not fragment("start", "started") and not fragment("and", "a")

    said = [w("We", 0.0, 0.2), w("started", 0.2, 0.6), w("the", 0.6, 0.8), w("business", 0.8, 1.2),
            w("in", 1.3, 1.5), w("2020.", 1.5, 2.0), w("Then", 2.6, 2.8), w("we", 2.8, 3.0), w("grew", 3.0, 3.3),
            w("it", 3.3, 3.5)]
    j = [2.3]

    def heard(*swap, drop=(), add=()):
        out = [dict(x) for i, x in enumerate(said) if i not in drop]
        for i, word in swap:
            out[i]["word"] = word
        return sorted(out + [w(x, s, e) for x, s, e in add], key=lambda x: x["start"])

    # A clean join: case, punctuation and number format differ, the snippet's outer words are garbled.
    assert judge(said, heard((0, "Wi"), (5, "twenty twenty,"), (6, "then"), (9, "eat")), j) == []
    assert judge(said, heard(drop=(6,)), j)[0]["kind"] == "missing"                       # "Then" cut away
    f = judge(said, heard((5, "20")), j)[0]                                               # "2020" heard as "20"
    assert f["kind"] == "clipped" and f["said"] == "2020." and f["heard"] == "20", f
    assert judge(said, heard((6, "Than")), j)[0]["kind"] == "changed"
    assert [f["kind"] for f in judge(said, heard(add=[("so", 2.3, 2.5)]), j)] == ["added"]
    assert [f["kind"] for f in judge(said, heard(add=[("gro-", 2.1, 2.3)]), j)] == ["clipped"]
    assert judge(said, heard(drop=(1,)), j) == []                  # far from the join: not the cut's doing
    # A leftover of a cut word next to a misheard one: "cool" (the end of a cut "school") and "three" for "free".
    f = judge(said, heard((6, "three"), add=[("cool", 2.3, 2.5)]), j)
    assert [(x["kind"], x["heard"]) for x in f] == [("added", "cool"), ("changed", "three")], f
    # The two models spell the same words differently at the join: not a problem.
    alt = [w("Okay,", 2.4, 2.6), w("it's", 2.6, 2.8), w("gonna", 2.8, 3.0), w("work.", 3.0, 3.3)]
    assert judge(said[:6] + alt, said[:6] + [w("OK.", 2.4, 2.6), w("It", 2.6, 2.7), w("is", 2.7, 2.8),
                                             w("going", 2.8, 2.9), w("to", 2.9, 3.0), w("work", 3.0, 3.3)], j) == []

    # The uncut video's words in cut time. Kept 0-5, 6-10 and 11-15 s, so the joins are at 5 and 9 s of the cut.
    tm = TimeMap([(0, 5), (6, 10), (11, 15)])
    loud = [(4.0, 4.5), (4.7, 5.3), (5.6, 5.8), (6.1, 6.5), (10.05, 10.4)]
    sound = lambda a, b: any(min(b, y) - max(a, x) >= 0.03 for x, y in loud)      # noqa: E731
    ref = reference([w("a", 4.0, 4.5), w("b", 4.7, 5.3),        # b: sound on both sides of the edge at 5
                     w("c", 5.5, 5.8),                          # all in the cut-away part
                     w("d", 5.9, 6.5),                          # its time starts early: no sound before the edge
                     w("g", 9.9, 10.4),                         # its sound is all on the cut-away side of 10
                     w("h", 10.6, 11.15)], tm, [5.0, 9.0], sound)  # no sound near the edge at 11: keeps its part
    assert [(x["word"], round(x["start"], 2), round(x["end"], 2), x["cut"]) for x in ref] == \
        [("a", 4.0, 4.5, False), ("b", 4.7, 5.0, True), ("d", 5.0, 5.5, False), ("h", 9.0, 9.15, False)], ref

    def cut_words(words, *spans):                                  # one edge at 5 s; sound where `spans` say
        hits = lambda a, b: any(min(b, y) - max(a, x) >= 0.03 for x, y in spans)    # noqa: E731
        return [x["word"] for x in reference(words, TimeMap([(0, 5), (6, 10)]), [5.0], hits) if x["cut"]]
    # Its time stops 80 ms short of the edge, but its last sound goes on past it: "Honest|ly".
    assert cut_words([w("honestly", 4.4, 4.92), w("nobody", 6.2, 6.6)], (4.4, 5.1), (6.2, 6.6)) == ["honestly"]
    # Silence at the edge, then the next word: "scratch." | "Glory" (cut away), however close.
    assert cut_words([w("scratch", 4.4, 4.85), w("glory", 5.15, 5.5)], (4.4, 4.85), (5.15, 5.5)) == []
    assert cut_words([w("end", 4.4, 4.97), w("fail", 5.02, 5.4)], (4.4, 4.97), (5.02, 5.4)) == []
    # A cut-away word timed from inside the last kept word's tail, the edge in the dip between: "going" | "Tech".
    assert cut_words([w("going", 4.3, 4.6), w("tech", 4.62, 5.14)], (4.3, 4.75), (5.06, 5.3)) == []
    # The same at the other edge: a cut-away word whose time runs on into the first kept word.
    assert cut_words([w("debt", 5.7, 6.38), w("failure", 6.4, 6.8)], (5.7, 5.94), (6.12, 6.8)) == []

    # Weighing differences against the uncut video (a 3 s snippet from 10.0 s, speech-level tone where words are).
    t = np.arange(int(3 * RATE)) / RATE
    on = lambda a, b: (t >= a) & (t < b)                           # noqa: E731
    x = (np.random.default_rng(1).normal(0, 0.01, t.size) + 0.3 * np.sin(2 * np.pi * 200 * t)
         * (on(0.2, 1.42) | on(1.68, 2.4))).astype(np.float32)
    ref = [w("We", 10.2, 10.5), w("started", 10.5, 11.0), {**w("business", 11.1, 11.5), "cut": True},
           w("Then", 11.65, 11.9), w("grew", 12.0, 12.4)]

    def weigh(*words, said=(), mistakes=()):
        out = review(10.0, [11.5], x, list(said), [w(*v) for v in words], ref, mistakes)
        return [(f["kind"], f["heard"], f["sure"]) for f in out]
    base = [("We", 10.2, 10.5), ("started", 10.5, 11.0), ("business", 11.1, 11.5), ("Then", 11.65, 11.9),
            ("grew", 12.0, 12.4)]
    assert weigh(*base) == []
    assert weigh(*base[:2], ("busy", 11.1, 11.45), *base[3:]) == [("clipped", "busy", True)]      # the cut goes through
    assert weigh(*base[:3], ("Than", 11.65, 11.9), *base[4:]) == [("changed", "Than", False)]     # a new context
    assert weigh(*base[:3], ("The", 11.5, 11.62), *base[3:]) == [("added", "The", False)]         # on silence
    assert weigh(*base[:3], ("so", 11.7, 11.85), *base[3:]) == [("added", "so", True)]            # on speech
    # A mistake cut that leaves in a word W leaves out. W mishearing a word ("vast" for "grew") is not that.
    said = [w("We", 10.2, 10.5), w("started", 10.5, 11.0), w("Then", 11.65, 11.9), w("vast", 12.0, 12.4)]
    assert weigh(*base, said=said, mistakes=[11.5]) == [("added", "business", True)]
    assert weigh(*base, said=said) == []                           # a dead-air cut takes out no words
    # That word heard as another one: the cut goes through it, even when the uncut video's sound doesn't show it.
    ref = [dict(v, cut=False) for v in ref]
    busy = (*base[:2], ("busy", 11.1, 11.45), *base[3:])
    assert weigh(*busy, said=said, mistakes=[11.5]) == [("clipped", "busy", True)]
    assert weigh(*busy, said=said) == [("clipped", "busy", False)]

    # The sound at the join. Syllables of a 200 Hz tone over a noise floor 20 dB under them, 3 s from 10.0 s.
    t = np.arange(int(3 * RATE)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    on = lambda a, b: (t >= a) & (t < b)                           # noqa: E731
    floor = np.random.default_rng(0).normal(0, 0.02, t.size).astype(np.float32)
    x = floor + tone * (on(0, .3) | on(.4, .7) | on(.8, 1.1) | on(1.6, 1.9) | on(2.4, 2.7))
    x += tone * on(1.30 + FADE, 1.30 + FADE + 0.01)               # a click as loud as the speech, right after a cut
    x += 0.12 * np.sin(2 * np.pi * 200 * t) * on(2.0, 2.3)        # steady sound 8 dB under the speech, near the floor
    hits = sound_at_joins(x, 10.0, [10.95, 11.30, 12.15], [w("business", 10.8, 11.1)],
                          [w("busy", 10.8, 10.95), w("ness", 10.95, 11.1)])
    assert [(h["join"], h["heard"], h["said"]) for h in hits] == [(10.95, "busy", "business"),
                                                                 (10.95, "ness", "")], hits
    assert "end of \"busy\"" in hits[0]["text"] and "start of \"ness\"" in hits[1]["text"], hits
    hits = sound_at_joins(x, 10.0, [10.95], [w("business", 10.8, 11.1)])           # nothing heard there
    assert 'end of "business"' in hits[0]["text"] and "a sound right after it" in hits[1]["text"], hits
    # The cut-off piece was not heard as a word, and the next word's time runs early: name neither as clipped.
    hits = sound_at_joins(x, 10.0, [10.95], [], [w("the", 10.5, 10.7), w("Every", 10.93, 11.2)])
    assert [h["text"].split("so ")[1] for h in hits] == ['a word between "the" and the cut may be cut off',
                                                         'the start of "Every" may be cut off'], hits
    # No floor, a syllable fading out: a cut in the fade, 6-10 dB under the syllable, is a dip, not a cut word.
    fade = (tone * (on(0.5, 0.8) + on(0.8, 1.0) * np.clip((1.0 - t) / 0.2, 0, 1) + on(1.6, 1.9))).astype(np.float32)
    assert sound_at_joins(fade, 0.0, [0.95], []) == []
    assert len(sound_at_joins(fade, 0.0, [0.65], [])) == 2                         # control: mid-syllable
    assert review(10.0, [11.5], np.zeros(3 * RATE, np.float32), said[:2], [])[0]["kind"] == "unheard"

    # Snippets share listening passes; each word lands back on its own snippet.
    class Fake:
        def transcribe(self, audio, **kw):
            assert abs(len(audio) / RATE - 7.0) < 1e-6                 # 3 s + 1 s gap + 2 s + 1 s gap
            ws = [SimpleNamespace(start=1.0, end=1.4, word=" a"), SimpleNamespace(start=3.3, end=3.6, word=" b"),
                  SimpleNamespace(start=4.5, end=4.9, word=" 87"), SimpleNamespace(start=4.9, end=5.0, word="%")]
            return [SimpleNamespace(words=ws)], None
    got = listen(Fake(), [np.zeros(3 * RATE, np.float32), np.zeros(2 * RATE, np.float32)])
    assert [[x["word"] for x in c] for c in got] == [["a"], ["87%"]] and abs(got[1][0]["start"] - 0.5) < 1e-6

    # A pass that stops early: what it skipped is heard again on its own, the rest is not.
    class Stops:
        calls: list = []

        def transcribe(self, audio, **kw):
            Stops.calls.append(round(len(audio) / RATE, 3))
            return [SimpleNamespace(words=[SimpleNamespace(start=0.2, end=0.5, word=" again")])], None
    wins = [[10.0, 13.0, [11.5]], [20.0, 22.0, [21.0]], [30.0, 32.0, [31.0]]]
    clips = [np.zeros(3 * RATE, np.float32), np.zeros(2 * RATE, np.float32), np.zeros(2 * RATE, np.float32)]
    saids = [[w("a", 10.2, 10.5), w("x", 11.1, 11.3), w("y", 11.6, 11.9)],         # stopped after "a"
             [w("b", 20.6, 20.9), w("c", 21.0, 21.3)],                             # nothing heard
             [w("d", 30.6, 30.9)]]                                                 # one word: no re-hearing
    with contextlib.redirect_stdout(io.StringIO()):
        got = hear(Stops(), wins, clips, saids)
    assert Stops.calls == [10.0, 3.6, 3.0], Stops.calls          # the pass, then 2.6 s and 2 s on their own, + gap
    assert [[(x["word"], round(x["start"], 2)) for x in c] for c in got] == \
        [[("again", 10.2), ("again", 10.6)], [("again", 20.2)], []], got

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "reports").mkdir()
        (d / "reports" / "my.talk.json").write_text("{}")
        assert guess_name(Path("work/my.talk.clean.mp4"), d) == "my.talk"
        (d / "input").mkdir()                                        # the project folder moved since step 2
        (d / "input" / "talk.mov").write_bytes(b"x")
        (d / "reports" / "talk.json").write_text(json.dumps({"source": str(d / "gone" / "input" / "talk.mov")}))
        assert source_of("talk", d, root=d) == d / "input" / "talk.mov"
        (d / "reports" / "talk.json").write_text(json.dumps({"source": "input/other.mov"}))
        assert source_of("talk", d, root=d) is None
        (d / "my.talk.mistakes-edl.json").write_text(json.dumps({"keep_ranges": [{"start": 0, "end": 3},
                                                                                 {"start": 3.5, "end": 8}]}))
        assert cut_names("my.talk", d, [1.0, 3.0]) == {1.0: "dead-air cut", 3.0: "mistake cut 3.00-3.50"}
        clip = d / "click.mp4"                                       # a click at exactly 1.0 s, in an mp4
        res = run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "aevalsrc='if(between(t,1.0,1.0005),0.9,0.001*sin(2*PI*300*t))':s=48000:d=2", "-c:a", "aac",
                   str(clip)])
        assert res.returncode == 0, res.stderr
        x, y = snippets(probe(clip), [(0.0, 1.5), (0.7, 1.2, [1.0])])
        assert x.size == 24000 and y.size == 8000, (x.size, y.size)
        assert abs(int(np.argmax(np.abs(x))) / RATE - 1.0) < 0.002
        assert abs(int(np.argmax(np.abs(y))) / RATE - 0.3) < 0.002
    print("relisten self-test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
