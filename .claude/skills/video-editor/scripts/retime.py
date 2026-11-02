#!/usr/bin/env python3
"""Move every plan onto a new cut, so each graphic, sound and caption still lands on its word.

/video-editor:auto saves the cut it times its plans on, with the words on it, once the cuts are final and before
it plans the graphics ("retime.py <name> --save" writes work/<name>.cutmap.json). When the cut changes later (a cut
put back, an extra cut, another pacing), this moves every time in every plan onto the new cut (the cut lists now in
work/). Each time keeps its distance to the word it belongs to: the word it leads into (a start) or the word it is
on; an end, the word it is on or trails; across a pause, the next word (a start) or the last one (an end). Where a
tighter cut leaves less room than that, a start stops where the word before ends (an end, where the word after
starts). A sound keeps its distance to the graphic it plays on. The words are the saved ones, each taken as the part
of it both cuts keep (Whisper often runs a word on across a pause), so neither a fresh transcription nor a longer or
shorter pause can shift anything. An item whose word was cut is dropped and listed. The director's plan stays approved.

Moved, when they exist in work/: <name>.templates.json, the kinetic plan <V-stem>.emphasis.json,
<name>.behind.json, <name>.sfx.json, the captions plan <V-stem>.captions.json and the windows in <name>.run.json.
Also the word timings given with --words (unless the re-cut already wrote them anew), and the morph windows given
with --morph (the moved string is printed). Each original is kept as <file>.pre-retime.json (.pre-retime-2.json
after a second re-cut, and so on), and <name>.cutmap.json then holds the new cut, so a second run moves nothing.

  python retime.py <name> --save                       once the cuts are final, before the graphics are planned
  python retime.py <name> --words W --morph "2.9-5.9,8.2-10.8"      after the cut changed
  python retime.py <name> --dry-run                    show what would move, write nothing
  python retime.py <name> --out-dir work/retimed       write the moved plans there, leave work/ as it is
  python retime.py <name> --old a.cutmap.json --new b.cutmap.json
  python retime.py --self-test
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import glob
import io
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "captions" / "scripts"))
from timemap import TimeMap, load  # noqa: E402
from transcribe import load_words  # noqa: E402
from vtools import fmt_time, probe, project_root  # noqa: E402

TOL = 0.25    # a start this close before a word leads into it: caption leads, a card's lead-in, a chart's --at
CUE = 0.06    # a sound this close before a word leads into it (a kinetic word's cue); a later sound is on its word
REACH = 1.0   # across a pause, a start leans on the next word and an end on the last one, up to this far
NEAR = 0.1    # cuts whose sound lengths differ by less are the same cut (probed lengths differ by a frame or two)
EPS = 1e-3    # plan times are rounded to the millisecond
KEY = 0.85    # a morph graphic's word starts this soon after its window (--at: a chart's number - 0.2 s, a check the verdict - 0.6)
RING = 2.2    # a ring-to-number counts up to its number about 1.9 s after --at (--at: the number - 1.8 s)
TIMES = {"at": False, "pick_at": False, "recap": False, "checks": False, "until": True}   # times inside a template; True: an end
NOUN = {"templates": "templates", "kinetic": "moments", "behind": "moments", "run": "windows",
        "captions": "captions", "sounds": "sounds"}


def r3(x: float) -> float:
    return round(x, 3)


def num(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:              # cut short, or not UTF-8
        raise RuntimeError(f"{path.parent.name}/{path.name} is damaged ({e}): run the step that wrote it again.") from None


def place(m: TimeMap, x: float, side: int = 0) -> float | None:
    """Source moment x on cut m. When x was cut out: None (side 0), the next kept moment (side 1),
    or the last kept moment before it (side -1)."""
    t = m.to_cut(x)
    if t is not None or not side:
        return t
    pieces = [(a, b, s) for (a, b), s in zip(m.keeps, m.starts)]
    if side > 0:
        return next((s for a, b, s in pieces if a > x), None)
    return next((s + b - a for a, b, s in reversed(pieces) if b < x), None)


def held(m: TimeMap, s: float, e: float) -> tuple[float, float] | None:
    """The longest part of source stretch s-e that cut m keeps in one piece, or None when it keeps none of it."""
    return max(((max(s, a), min(e, b)) for a, b in m.keeps if a < e and b > s), key=lambda p: p[1] - p[0], default=None)


@dataclass
class Word:
    src: tuple[float, float]   # source seconds
    os: float                  # start and end on the old cut
    oe: float
    ns: float | None           # on the new cut; None when the new cut removes the word
    ne: float | None
    text: str


class Retimer:
    def __init__(self, old: TimeMap, new: TimeMap, src_words=()):
        self.old, self.new = old, new
        self.words: list[Word] = []          # the old cut's words
        self.back: list[list[dict]] = []     # runs of words the new cut puts back, in new-cut seconds
        self.gone: list[tuple[float, float, float]] = []      # dropped graphics: old start, old end, a sound's lead-in
        self.events: list[tuple[float, float, float, float]] = []   # moments sounds are timed from: old, new, old end, lead-in
        run: list[dict] = []
        for s, e, mid, text in sorted(src_words):
            in_old, in_new = old.to_cut(mid) is not None, new.to_cut(mid) is not None
            if in_old:
                # Whisper often runs a word on across a pause, but it is heard only in what both cuts keep: anchor on
                # that, so a pause that grows or shrinks can't shift what is timed from it. A cut removes a word at
                # its edges, while a pacing change keeps air by every heard word: 0.1 s kept is a kept word
                s, e = held(old, s, e) or (s, e)
                h = held(new, s, e)
                in_new = in_new or (h is not None and h[1] - h[0] >= 0.1)
                if in_new:
                    s, e = h
                self.words.append(Word((s, e), place(old, s, 1), place(old, e, -1),
                                       place(new, s, 1) if in_new else None, place(new, e, -1) if in_new else None, text))
            if in_new and not in_old:
                run.append({"start": r3(place(new, s, 1)), "end": r3(place(new, e, -1)), "word": text})
            elif run:
                self.back.append(run)
                run = []
        if run:
            self.back.append(run)
        self._os = [w.os for w in self.words]
        self._oe = [w.oe for w in self.words]

    def anchor(self, t: float, end: bool, lead: float = TOL) -> int | None:
        """The word a time belongs to (its index). A start: the word it leads into (within `lead`), else the word it
        is on, else across a pause the next word (within REACH). An end: the word it is on, else the last (REACH)."""
        ws = self.words
        if not ws:
            return None
        if end:
            j = bisect.bisect_right(self._oe, t + EPS) - 1                  # the last word ending by t
            if j + 1 < len(ws) and ws[j + 1].os < t - EPS:
                return j + 1
            return j if j >= 0 and t - ws[j].oe <= REACH else None
        i = bisect.bisect_left(self._os, t - EPS)                           # the first word starting at or after t
        if i < len(ws) and ws[i].os - t <= lead:
            return i
        if i and ws[i - 1].oe > t + EPS:
            return i - 1
        return i if i < len(ws) and ws[i].os - t <= REACH else None

    def move(self, t: float, end: bool = False, lead: float = TOL) -> tuple[float | None, Word | None]:
        """A time on the old cut -> (its time on the new cut, the word it moved with). The time is None when that
        word was cut, or, with no words known, when the moment itself was cut. Where a tighter cut leaves less room,
        a start never reaches further back into the word before than it did, nor an end into the word after."""
        i = self.anchor(t, end, lead)
        w = None if i is None else self.words[i]
        if w is not None:
            if w.ns is None:
                return None, w
            nt = w.ne + t - w.oe if end else w.ns + t - w.os
            k = i + 1 if end else i - 1
            o = self.words[k] if 0 <= k < len(self.words) else None
            if o is not None and o.ns is not None:
                nt = min(nt, o.ns + max(0.0, t - o.os)) if end else max(nt, o.ne + min(0.0, t - o.oe))
        else:
            x = self.old.to_source(t, end=end)
            nt = self.new.to_cut(x)
            if nt is None and self.words:        # only a pause was cut here: keep to the nearest kept moment
                nt = place(self.new, x, -1 if end else 1)
            if nt is None:
                return None, None
        return min(max(nt, 0.0), self.new.duration), w

    def span(self, a: float, b: float) -> tuple[float, float] | None:
        """A window moved to the new cut, or None when the word it starts on was cut (or nothing of it is left).
        An end whose word was cut moves back to where that cut begins."""
        na, _ = self.move(a)
        if na is None:
            return None
        nb, w = self.move(b, end=True)
        if nb is None:
            nb = place(self.new, w.src[0] if w else self.old.to_source(b, end=True), -1)
        return (na, nb) if nb is not None and nb > na + EPS else None

    def inner(self, t, win, end: bool, what: str, say: list) -> float:
        """A time inside a window (a flowchart box, a tag's exit, a card's check frame), kept inside the window.
        When its word was cut it goes to where that cut ends (an end: where it begins)."""
        nt, w = self.move(float(t), end)
        if nt is None:
            nt = place(self.new, (w.src[0] if end else w.src[1]) if w else self.old.to_source(float(t), end=end),
                       -1 if end else 1)
            nt = min(max(win[1] if nt is None else nt, win[0]), win[1])
            say.append(f"  {what}: the moment at {fmt_time(float(t))} was on cut words; it now falls at "
                       f"{fmt_time(nt)}, where the cut {'begins' if end else 'ends'}.")
        return r3(min(max(nt, win[0]), win[1]))

    def inner_times(self, node, win, what: str, say: list) -> None:
        if isinstance(node, list):
            for x in node:
                self.inner_times(x, win, what, say)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k in TIMES and isinstance(v, list):
                    node[k] = [self.inner(t, win, TIMES[k], what, say) for t in v]
                elif k in TIMES and isinstance(v, (int, float)) and not isinstance(v, bool):   # "recap": true is no time
                    node[k] = self.inner(v, win, TIMES[k], what, say)
                elif isinstance(v, (dict, list)):
                    self.inner_times(v, win, what, say)

    def cut_inside(self, a: float, b: float) -> bool:
        """True when the new cut removes a word said between a and b (old cut times)."""
        for w in self.words[bisect.bisect_right(self._oe, a + EPS):]:
            if w.os >= b - EPS:
                return False
            if w.ns is None:
                return True
        return False

    def cut_from(self, a: float, b: float) -> bool:
        """True when the new cut removes a word that starts between a and b (old cut times): not the word a is in."""
        return any(w.ns is None for w in self.words if a - EPS <= w.os < b - EPS)

    def morph_gone(self, a: float, b: float) -> bool:
        """A morph window goes when the word it shows was cut: its number (a ring reaches it up to RING s in, a chart at
        once), else the word within KEY of its start (a check's verdict). A lead-in word before the number may go."""
        # shortcut: a number in digits only (Whisper writes most); a check with a number in its first 2.2 s follows the
        # number, not its verdict. Store the template in the window if that shows up
        n = next((w for w in self.words if a - EPS <= w.os < min(b, a + RING) - EPS and any(c.isdigit() for c in w.text)),
                 None)
        return n.ns is None if n else self.cut_from(a, min(b, a + KEY))

    def drop(self, say: list, what: str, a: float, b: float | None = None, lead: float = 0.0) -> None:
        say.append(f"  Dropped {what} at {fmt_time(a)}: its words were cut.")
        self.gone.append((a, a if b is None else b, lead))


# ---------------------------------------------------------------------------- the plans

def label(sp: dict) -> str:
    """A template's name in messages: its title or text, else the first text inside it (a tag, a step, a box)."""
    for k in ("name", "title", "text", "handle", "label", "file"):
        if sp.get(k):
            return str(sp[k])
    inside = (x for v in sp.values() for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict))
    return next((str(x["text"]) for x in inside if x.get("text")), "")


def named(kind, text) -> str:
    """An item in messages: its kind, then its text in quotes when it has one."""
    return f'{kind} "{text}"' if text else f"{kind}"


def ats(node):
    """Each "at" inside a template, in order: the moments its parts appear, which its sounds are timed from."""
    if isinstance(node, list):
        for x in node:
            yield from ats(x)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k == "at" and isinstance(v, (int, float)) and not isinstance(v, bool):
                yield float(v)
            elif k == "at" and isinstance(v, list):
                yield from (float(t) for t in v)
            elif isinstance(v, (dict, list)):
                yield from ats(v)


def templates(data, rt: Retimer, say: list):
    """work/<name>.templates.json: one spec or a list (motion-templates/references/templates.md)."""
    specs, kept = (data if isinstance(data, list) else [data]), []
    for sp in specs:
        what, a, b = named(sp.get("template"), label(sp)), float(sp.get("start", 0.0)), float(sp["end"])
        win = rt.span(a, b)
        if win is None:
            rt.drop(say, what, a, b)
            continue
        before = list(ats(sp))
        sp["start"], sp["end"] = r3(win[0]), r3(win[1])
        rt.inner_times(sp, win, what, say)
        rt.events += [(a, win[0], b, 0.0)] + [(x, y, b, 0.0) for x, y in zip(before, ats(sp))]
        if sp.get("template") == "card" and abs((win[1] - win[0]) - (b - a)) > 1 / 30:
            say.append(f"  {what} is now {win[1] - win[0]:.1f} s long (was {b - a:.1f} s): its own motion is timed "
                       "from its start, so look at it again.")
        kept.append(sp)
    return (kept if isinstance(data, list) or not kept else kept[0]), len(kept), len(specs)


def moments(data, rt: Retimer, say: list, kind: str):
    """Kinetic text (find_emphasis.py) or text behind (build_behind.py): {"moments": [...]} or a list.
    A moment shows its words, so it is dropped when any of them was cut. A kinetic word's sound plays just before it."""
    cues = kind == "kinetic text"
    lead = CUE if cues else 0.0

    def move_all(items, shown):
        kept = []
        for m in items:
            a, b = float(m["start"]), (float(m["end"]) if m.get("end") is not None else None)
            if b is None:
                t = rt.move(a)[0]
                win = None if t is None else (t, t)
            else:
                win = rt.span(a, b)
            if win is None or (b is not None and rt.cut_inside(a, b)):
                if shown:
                    rt.drop(say, named(kind, m.get("text")), a, b, lead)
                continue
            m["start"] = r3(win[0])
            if b is not None:
                m["end"] = r3(win[1])
            if shown and any(win[0] - EPS <= r[0]["start"] and r[-1]["end"] <= win[1] + EPS for r in rt.back):
                say.append(f"  {named(kind, m.get('text'))} now runs over words put back: look at it again.")
            if shown and cues:
                rt.events.append((a, win[0], a if b is None else b, lead))
            kept.append(m)
        return kept
    if isinstance(data, list):
        kept = move_all(data, True)
        return kept, len(kept), len(data)
    total = len(data.get("moments", []))
    data["moments"] = move_all(data.get("moments", []), True)
    if isinstance(data.get("other_candidates"), list):
        data["other_candidates"] = move_all(data["other_candidates"], False)
    return data, len(data["moments"]), total


def captions(plan: dict, rt: Retimer, say: list):
    """The captions plan (make_captions.py --plan-only). Each caption keeps to its words: cut words leave its text,
    a caption left with no word to show is dropped, and words a put-back brings back get captions in its style (a
    caption they land inside is split around them). Burning it with --hide-during hides the moved windows again."""
    fps, total, out = float(plan.get("fps") or 30), len(plan.get("chunks", [])), []    # out: (caption, its index)
    for n, c in enumerate(plan.get("chunks", [])):
        a, b, ws = float(c["start"]), float(c["end"]), c.get("words")
        spans = ([(float(w["start"]), float(w["end"])) for w in ws] if ws else
                 [(w.os, w.oe) for w in rt.words if a - EPS <= w.os < b])
        what = named("caption", c.get("text"))
        if not spans:                                # no word timings at all: the caption moves as one window
            win = rt.span(a, b)
            if win is None:
                say.append(f"  Dropped {what} at {fmt_time(a)}: its words were cut.")
            else:
                c["start"], c["end"] = r3(win[0]), r3(win[1])
                out.append((c, n))
            continue
        moved = [(rt.move(s)[0], rt.move(e, end=True)[0]) for s, e in spans]
        keep = [i for i, (s, e) in enumerate(moved) if s is not None and e is not None]
        toks = str(c.get("text", "")).split()
        trailing = a >= spans[-1][1] - EPS          # shown after its words: --hide-during kept it off a graphic so
        parts = [[keep[0]]] if keep else []          # split where put-back words land between two of its words
        for i, j in zip(keep, keep[1:]):
            if not trailing and len(toks) == len(spans) and any(moved[i][1] - EPS <= r[0]["start"] and r[-1]["end"] <= moved[j][0] + EPS
                                               for r in rt.back):
                parts.append([])
            parts[-1].append(j)
        shown = []
        for k, p in enumerate(parts):
            first, last = moved[p[0]][0], moved[p[-1]][1]
            if k:
                s = first - 2 / fps
            elif a <= spans[0][0]:                   # the same lead into its first word left
                s = first - (spans[0][0] - a)
            elif trailing:                          # the same distance after its last word left
                s = last + a - spans[p[-1]][1]
            else:                                   # it starts late, within its words (--hide-during): a time
                s, w = rt.move(a)
                if s is None and w is not None:
                    s = place(rt.new, w.src[1], 1)   # its word was cut: where that cut ends
                s = first if s is None else s
                if s >= last - EPS:                 # the words it has left are all said before it would show
                    continue
            part = dict(c)
            if len(toks) == len(spans):
                part["text"] = " ".join(toks[i] for i in p)
            trail = b - spans[-1][1] if k == len(parts) - 1 else 0.3
            part["start"], part["end"] = r3(max(0.0, s)), r3(s + b - a if trailing else last + trail)
            if ws:
                part["words"] = [{**ws[i], "start": r3(moved[i][0]), "end": r3(moved[i][1])} for i in p]
            shown.append(part)
        if not shown:
            say.append(f"  Dropped {what} at {fmt_time(a)}: its words were cut.")
            continue
        if len(keep) < len(spans) or len(shown) > 1:
            say.append(f'  {what} now reads "{" | ".join(x["text"] for x in shown)}".' if len(toks) == len(spans)
                       else f"  {what} lost some cut words: fix its text by hand.")
        out += [(x, n) for x in shown]
    added = 0
    if rt.back and plan.get("style"):
        from make_captions import plan_captions
        for words_back in rt.back:
            more = plan_captions(words_back, plan["style"], fps, plan.get("height", 0) > plan.get("width", 0))
            out, added = out + [(x, None) for x in more], added + len(more)
        say.append(f"  Added {added} caption(s) for the words put back: check their text and colour.")
    out.sort(key=lambda x: x[0]["start"])
    for i, (c, _) in enumerate(out):                # a hard swap, never two captions at once
        nxt = out[i + 1][0]["start"] if i + 1 < len(out) else float("inf")
        c["end"] = r3(min(max(c["end"], c["start"] + 1 / fps), nxt))
    for c, _ in out:
        if c["end"] <= c["start"] + EPS:
            say.append(f"  Dropped {named('caption', c.get('text'))}: the next caption starts at the same moment.")
    out = [x for x in out if x[0]["end"] > x[0]["start"] + EPS]
    plan["chunks"] = [c for c, _ in out]
    return plan, len({n for _, n in out if n is not None}), total


def run_windows(state, rt: Retimer, say: list):
    """The graphic windows in work/<name>.run.json (run_state.py), which the --skip and --hide-during strings use.
    Each goes when its graphic went: a kinetic or text-behind window when any of its words was cut, a morph window
    when its word was (as morph() drops it)."""
    wins = state.get("windows") if isinstance(state, dict) else None
    if not (isinstance(wins, dict) and all(isinstance(v, list) for v in wins.values())):
        say.append("  Its windows are not in a shape this knows: left as they are.")
        return state, 0, 0
    moved = total = 0
    for mode, items in wins.items():
        kept = []
        for w in items:
            a, b = float(w["start"]), float(w["end"])
            win = rt.span(a, b)
            if win is None or (w.get("kind") in ("kinetic", "behind") and rt.cut_inside(a, b)) or \
                    (w.get("kind") == "morph" and rt.morph_gone(a, b)):
                say.append(f"  Dropped the {w.get('kind', 'graphic')} window at {fmt_time(a)}: its words were cut.")
                continue
            w["start"], w["end"] = r3(win[0]), r3(win[1])
            kept.append(w)
        wins[mode], moved, total = kept, moved + len(kept), total + len(items)
    return state, moved, total


def sounds(cues, rt: Retimer, say: list):
    """work/<name>.sfx.json (suggest_sfx.py): each cue keeps its distance to the graphic moment it is timed from, the
    latest one at or before it (an entrance, an item, a tag, a chart, or a kinetic word just after it); it goes when
    that graphic went. A cue with no graphic moment moves with its word."""
    kept = []
    for c in cues:
        t, what = float(c["at"]), f'sound {c.get("sound")} ({c.get("why", "")})'
        owners = [(e[0], 1, e) for e in rt.events if e[0] - e[3] - EPS <= t <= e[2] + EPS] + \
                 [(g[0], 0, None) for g in rt.gone if g[0] - g[2] - EPS <= t <= g[1] + EPS]
        # shortcut: two graphics under about 0.15 s apart can swap sounds (it matters only when a join between them
        # changes); match suggest_sfx's offsets per kind of cue if that shows up
        owner = max(owners, key=lambda o: o[:2], default=None)      # the latest; on a tie, a graphic still there
        if owner and owner[2] is None:
            say.append(f"  Dropped {what} at {fmt_time(t)}: its graphic was dropped.")
            continue
        nt = t + owner[2][1] - owner[2][0] if owner else rt.move(t, lead=CUE)[0]
        if nt is None:
            say.append(f"  Dropped {what} at {fmt_time(t)}: its words were cut.")
            continue
        c["at"] = r3(min(max(nt, 0.0), rt.new.duration))
        kept.append(c)
    return kept, len(kept), len(cues)


def morph(spec: str, rt: Retimer, say: list) -> str:
    """'2.9-5.9,8.2-10.8' on the old cut -> the same windows on the new cut. A window goes when the word it lands on
    (its number, or else its verdict within KEY of its start) was cut, even if the short word before it stays."""
    out = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        a, b = (float(x) for x in part.split("-"))
        win = rt.span(a, b)
        if win is None or rt.morph_gone(a, b):
            rt.drop(say, f"morph window {part}", a, b)
        else:
            rt.events.append((a, win[0], b, 0.0))
            out.append(f"{num(win[0])}-{num(win[1])}")
    return ",".join(out)


def word_file(data, rt: Retimer):
    """The word timings W: a list, or {"words": [...]} (kit shape). Cut words go."""
    items = data.get("words", []) if isinstance(data, dict) else data
    kept = []
    for w in items:
        if not (isinstance(w, dict) and "start" in w and "end" in w):
            kept.append(w)
            continue
        s, e = rt.move(float(w["start"]))[0], rt.move(float(w["end"]), end=True)[0]
        if s is not None and e is not None:
            w["start"], w["end"] = r3(s), r3(e)
            kept.append(w)
    if not isinstance(data, dict):
        return kept, len(kept), len(items)
    data["words"] = kept
    if "audio_duration_secs" in data:
        data["audio_duration_secs"] = r3(rt.new.duration)
    return data, len(kept), len(items)


HANDLERS = {"templates": templates, "kinetic": lambda d, rt, say: moments(d, rt, say, "kinetic text"),
            "behind": lambda d, rt, say: moments(d, rt, say, "text behind"), "run": run_windows,
            "captions": captions, "sounds": sounds}


def other_video(work: Path, name: str, path: Path) -> bool:
    """True when a plan <name>.<part>.<plan>.json belongs to another video, such as talk.v2 next to talk: one with
    its own source in input/, dead-air report, transcript, run file or saved cut."""
    # shortcut: a second video with none of these is taken for a pass of this one; read the plan names from the
    # run file's step outputs if that ever happens
    parts = path.name[len(name) + 1:].split(".")[:-2]          # talk.v2.k.emphasis.json -> ["v2", "k"]
    inp = work.parent / "input"
    sources = {p.stem for p in inp.iterdir()} if inp.is_dir() else set()
    for i in range(1, len(parts) + 1):
        stem = ".".join([name, *parts[:i]])
        if stem in sources or any((work / f).is_file() for f in (f"reports/{stem}.json", f"{stem}.transcript.json",
                                                                  f"{stem}.run.json", f"{stem}.cutmap.json")):
            return True
    return False


def plan_files(work: Path, name: str) -> list[tuple[str, Path]]:
    """The plans of work/<name>, sound plans last (they follow the graphics they belong to)."""
    n = glob.escape(name)
    pats = (("templates", (f"{n}.templates.json",)), ("kinetic", (f"{n}.emphasis.json", f"{n}.*.emphasis.json")),
            ("behind", (f"{n}.behind.json",)), ("run", (f"{n}.run.json",)),
            ("captions", (f"{n}.captions.json", f"{n}.*.captions.json")), ("sounds", (f"{n}.sfx.json", f"{n}.*.sfx.json")))
    return [(kind, p) for kind, ps in pats for pat in ps for p in sorted(work.glob(pat))
            if not other_video(work, name, p)]


# ---------------------------------------------------------------------------- the cuts and the words

def closest(length, cands: list) -> TimeMap | None:
    """The cut of `cands` ((its length, the cut) pairs) that is `length` seconds long, within NEAR, or None."""
    cands = [(n, m) for n, m in cands if m]
    if length is None or not cands:
        return None
    n, m = min(cands, key=lambda c: abs(c[0] - float(length)))
    return m if abs(n - float(length)) <= NEAR else None


def stated_length(data):
    return data.get("audio_duration_secs") if isinstance(data, dict) else None


def dead_air(work: Path, name: str) -> tuple[TimeMap | None, float]:
    """The dead-air cut, and its length as Whisper measures it: its sound's. Its picture can run on up to 0.3 s
    with no sound under it, and the transcript and the mistake cuts state the sound's length."""
    p = work / "reports" / f"{name}.json"
    if not p.is_file():
        return None, 0.0
    r = read_json(p)
    m = TimeMap.from_cuts(r.get("cuts") or [], float(r["duration_before"]))
    out = r.get("output")
    video = Path(out) if out and Path(out).is_file() else work / f"{name}.mp4"    # the project folder may have moved
    try:
        heard = probe(video).audio_duration if video.is_file() else 0.0
    except RuntimeError:                    # no ffprobe, or a file it can't read: the picture's length will do
        heard = 0.0
    return m, heard or m.duration


def source_words(work: Path, name: str, old: TimeMap, new: TimeMap, words_path) -> tuple[list, str]:
    """Every word in source seconds, as (start, end, middle, text), and the file they came from.
    work/<name>.transcript.json has every word, the ones a mistake cut removed too; the words file W is next.
    A words file is read on the cut it is as long as."""
    t = work / f"{name}.transcript.json"
    if t.is_file():
        n = stated_length(read_json(t))
        d, heard = dead_air(work, name)
        cands = [(heard, d)] if d else ([(float(n), TimeMap([(0.0, float(n))]))] if n else [])
        m = closest(n, cands + [(old.duration, old), (new.duration, new)])
        if m:
            return to_source(load_words(t), m), str(t)
    if words_path and Path(words_path).is_file():
        m = closest(stated_length(read_json(words_path)), [(new.duration, new), (old.duration, old)]) or old
        return to_source(load_words(words_path), m), str(words_path)
    return [], ""


def to_source(words: list[dict], m: TimeMap) -> list[tuple]:
    return [(m.to_source(w["start"]), m.to_source(w["end"], end=True), m.to_source((w["start"] + w["end"]) / 2),
             w["word"]) for w in words]


def matches(times: list[float], ref: list[float]) -> int:
    """How many of `times` lie within 20 ms of a time in the sorted list `ref`."""
    n = 0
    for t in times:
        i = bisect.bisect_left(ref, t - 0.02)
        n += i < len(ref) and ref[i] <= t + 0.02
    return n


def words_on(data, rt: Retimer) -> str:
    """'new' when a words file is already timed on the new cut (the re-cut wrote it), else 'old'.
    Its words land on the known words on one cut only; failing that, its stated length decides."""
    items = data.get("words", []) if isinstance(data, dict) else data
    starts = [float(w["start"]) for w in items if isinstance(w, dict) and "start" in w]
    on_old = matches(starts, rt._os)
    on_new = matches(starts, sorted(w.ns for w in rt.words if w.ns is not None))
    if on_old != on_new and 2 * max(on_old, on_new) >= len(starts):
        return "new" if on_new > on_old else "old"
    cut = closest(stated_length(data), [(rt.old.duration, rt.old), (rt.new.duration, rt.new)])
    return "new" if cut is rt.new else "old"


def stale_mistakes(work: Path, name: str) -> str | None:
    """A message when the mistake cuts were made on another dead-air cut than today's (their times would be wrong)."""
    (d, heard), edl = dead_air(work, name), work / f"{name}.mistakes-edl.json"
    if d is None or not edl.is_file():
        return None
    made_on = read_json(edl).get("source_duration")
    if made_on is None or abs(float(made_on) - heard) <= NEAR:
        return None
    return (f"The mistake cuts ({edl.name}) were made on a {fmt_time(float(made_on))} dead-air cut, but the dead-air "
            f"cut is now {fmt_time(heard)}. Run steps 3 and 4 again on the new dead-air cut, then run this again.")


def subtract(keeps, minus) -> list[tuple[float, float]]:
    """Source stretches in `keeps` that `minus` does not keep."""
    out = []
    for a, b in keeps:
        pos = a
        for c, d in minus:
            if d > pos and c < b:
                if c > pos:
                    out.append((pos, c))
                pos = max(pos, d)
        if pos < b:
            out.append((pos, b))
    return [(a, b) for a, b in out if b - a > EPS]


def same(x: TimeMap, y: TimeMap) -> bool:
    return len(x.keeps) == len(y.keeps) and all(abs(p - q) < EPS for u, v in zip(x.keeps, y.keeps)
                                                for p, q in zip(u, v))


def cut_json(m: TimeMap, src) -> dict:
    """A cut map, with the words its plans are timed on in source seconds (a later transcription can't move them)."""
    return {**m.to_json(), "words": [{"start": round(s, 6), "end": round(e, 6), "mid": round(x, 6), "word": t}
                                     for s, e, x, t in src]}


def backup(path: Path) -> Path:
    """<file>.pre-retime.json, or .pre-retime-2.json and on when an earlier re-cut kept one: every original stays."""
    i, b = 1, path.with_suffix(".pre-retime.json")
    while b.exists():
        i += 1
        b = path.with_suffix(f".pre-retime-{i}.json")
    return b


# ---------------------------------------------------------------------------- the run

def has_windows(state) -> bool:
    """True when a run file holds a graphic window: timed on the saved cut, and the only record of morph graphics."""
    wins = state.get("windows") if isinstance(state, dict) else None
    return isinstance(wins, dict) and any(isinstance(v, list) and v for v in wins.values())


def save_cut(name: str, work: Path, words_file=None, dry_run: bool = False) -> int:
    """--save: the cut the plans are about to be timed on, with its words, in work/<name>.cutmap.json."""
    problem = stale_mistakes(work, name)
    if problem:
        print(problem)
        return 2
    try:
        cur = load(name, work)
    except FileNotFoundError as e:
        print(f"No cut to save yet: {e}")
        return 2
    path = work / f"{name}.cutmap.json"
    if path.is_file() and any(k != "run" or has_windows(read_json(p)) for k, p in plan_files(work, name)):   # plans on it
        saved = read_json(path)
        if not same(TimeMap(saved["keeps"]), cur):
            print(f"The plans in work/ are timed on the cut saved in {path.name}, and the cut has changed since. Run "
                  f"'retime.py {name}' to move them onto the new cut: it saves the new cut itself. To plan the graphics "
                  f"again from the start instead, delete {path.name} first.")
            return 2
        if saved.get("words"):
            print(f"{path.name} already holds this cut and the words the plans are timed on: left as it is.")
            return 0
    src, origin = source_words(work, name, cur, cur, words_file)
    if not dry_run:
        path.write_text(json.dumps(cut_json(cur, src), indent=1), encoding="utf-8")
    pieces = f"{len(cur.keeps)} piece" + "s" * (len(cur.keeps) != 1)
    print(f"{'Would save' if dry_run else 'Saved'} the cut the plans will be timed on ({fmt_time(cur.duration)}, "
          f"{pieces}) and " + (f"its {len(src)} words (from {Path(origin).name})" if src else
                               "no words (no transcript, and no --words)") + f" in {path.name}.")
    return 0


def retime(name: str, work: Path, old_file=None, new_file=None, words_file=None, morph_spec: str = "",
           out_dir=None, dry_run: bool = False) -> int:
    old_path = Path(old_file) if old_file else work / f"{name}.cutmap.json"
    if not old_path.is_file():
        print(f"No saved cut to move the plans from: {old_path} is missing. 'retime.py {name} --save' writes it "
              "once the cuts are final, before the graphics are planned. Give the cut the plans were made on with --old.")
        return 2
    if words_file and not Path(words_file).is_file():
        print(f"{words_file} is not there: give the word timings W with --words, or leave it out.")
        return 2
    try:                         # checked before anything moves: after the run, the cut map holds the new cut
        for w in filter(str.strip, morph_spec.split(",")):
            a, b = map(float, w.split("-"))
        old_data = read_json(old_path)
        old = TimeMap(old_data["keeps"])
        saved = [(float(w["start"]), float(w["end"]), float(w["mid"]), str(w["word"])) for w in old_data.get("words") or []]
        new = TimeMap.read(new_file) if new_file else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f'Could not read the cut maps or --morph ({e}). --morph takes windows like "2.9-5.9,8.2-10.8".')
        return 2
    if new is None:
        problem = stale_mistakes(work, name)
        if problem:
            print(problem)
            return 2
        try:
            new = load(name, work)
        except FileNotFoundError as e:
            print(f"No current cut to move the plans to: {e}")
            return 2
    if same(old, new):
        print("The cut is the same as the one the plans were made on: nothing to move. (Just changed the cut? Step 2 "
              "only redoes a video it already made with --overwrite.)")
        return 0
    print(f"The plans were made on a {fmt_time(old.duration)} cut; the cut is now {fmt_time(new.duration)}.")
    for a, b in subtract(new.keeps, old.keeps):
        print(f"  Put back: {b - a:.2f} s at {fmt_time(new.to_cut(a))}.")
    for a, b in subtract(old.keeps, new.keeps):
        print(f"  Cut: {b - a:.2f} s at {fmt_time(old.to_cut(a))} of the old cut.")
    src, origin = (saved, str(old_path)) if saved else source_words(work, name, old, new, words_file)
    rt = Retimer(old, new, src)
    k = len(rt.words)
    print(f"Each time moves with its word ({k} word{'s' * (k != 1)} from {Path(origin).name})." if src else
          "No word timings found (work/<name>.transcript.json or --words): times move with the cut alone, "
          "and an item on cut material is dropped.")

    writes = []
    jobs = plan_files(work, name)
    if not jobs:
        print(f"No plans for {name} in {work}.")
    for kind, path in [j for j in jobs if j[0] != "sounds"] + [("morph", None)] + [j for j in jobs if j[0] == "sounds"]:
        say: list[str] = []
        if kind == "morph":
            if morph_spec:
                print(f'Morph windows on the new cut: --morph "{morph(morph_spec, rt, say)}"')
        else:
            n_events, n_gone = len(rt.events), len(rt.gone)
            try:
                data, moved, total = HANDLERS[kind](read_json(path), rt, say)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RuntimeError) as e:
                del rt.events[n_events:], rt.gone[n_gone:]
                print(f"{path.name}: could not be read as a {kind} plan ({e}); left as it is.")
                continue
            print(f"{path.name}: {moved} of {total} {NOUN[kind]} moved.")
            writes.append((path, data))
        for line in say:
            print(line)
    if words_file:
        data = read_json(words_file)
        if words_on(data, rt) == "new":
            print(f"{words_file}: already timed on the new cut (the re-cut wrote it), left as it is.")
        else:
            data, moved, total = word_file(data, rt)
            print(f"{words_file}: {moved} of {total} words moved" + (f" ({total - moved} were cut)." if total > moved else "."))
            writes.append((Path(words_file), data))

    if dry_run:
        print("Dry run: nothing was written.")
        return 0
    plans_moved = bool(writes)
    writes.append((work / f"{name}.cutmap.json", cut_json(new, src)))
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    numbered, done = False, []                           # done: (file in work/, its backup or None) written so far
    try:
        for path, data in writes:
            if out_dir:
                path = Path(out_dir) / path.name
            else:
                keep = None
                if path.is_file():
                    keep = backup(path)                  # keep the original
                    numbered |= keep.name != path.with_suffix(".pre-retime.json").name
                    shutil.copyfile(path, keep)
                done.append((path, keep))
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as e:   # a full disk, a read-only file: put back what moved, or a second run would move it twice
        for p, keep in reversed(done):
            with contextlib.suppress(OSError):
                if keep is None:
                    p.unlink(missing_ok=True)            # it wasn't there before
                else:
                    if p.read_bytes() != keep.read_bytes():
                        shutil.copyfile(keep, p)
                    keep.unlink()
        print(f"Could not write {path.name} ({e}). Nothing was moved: every plan is as it was. Fix that, then run "
              "this again.")
        return 2
    if out_dir:
        print(f"Wrote the moved plans and the new cut to {out_dir}; work/ is unchanged.")
    elif plans_moved:
        print("Kept each original as <file>.pre-retime.json" + (" (or .pre-retime-2.json and on, next to the ones an "
              "earlier re-cut kept)" if numbered else "") + f". The plans now follow the new cut, and {name}.cutmap.json "
              "holds it.")
    else:
        print(f"Nothing else to move: {name}.cutmap.json now holds the new cut.")
    return 0


# ---------------------------------------------------------------------------- self-test

LAND = 0.13   # (self-test) suggest_sfx's cue lands this long after a template part appears, plus a frame


def self_test() -> int:
    from make_captions import plan_captions
    frame = 1 / 30
    near = lambda x, y: x is not None and y is not None and abs(x - y) <= frame  # noqa: E731
    SRC = [(0.50, 0.70, "So"), (0.75, 0.90, "the"), (0.95, 1.10, "the"), (1.10, 1.40, "best"), (1.45, 1.70, "way."),
           (3.20, 3.35, "to"), (3.40, 3.62, "learn"), (3.67, 4.00, "is"), (4.05, 4.60, "simple."),
           (6.00, 6.20, "do"), (6.25, 6.60, "this"), (6.70, 7.00, "every"), (7.05, 7.50, "day.")]
    DEAD = [(0.0, 0.4), (1.8, 3.1), (4.7, 5.9), (7.6, 8.0)]        # pauses; 0.1 s of air stays by each word
    old = TimeMap.from_cuts(DEAD + [(0.75, 0.95)], 8.0)            # + the stutter "the", cut at its word edges
    cuts = {"put back": TimeMap.from_cuts(DEAD, 8.0),
            "extra cut": TimeMap.from_cuts(DEAD + [(0.75, 0.95), (3.67, 4.05), (6.0, 6.25)], 8.0)}   # "is", "do"
    src = [(s, e, (s + e) / 2, w) for s, e, w in SRC]
    KIN = ((3, 4, "best way"), (7, 8, "is simple"), (8, 10, "simple. do this"), (11, 12, "every day"))

    def at(m, i, off=0.0, end=False):         # word i's start (or end) on cut m, plus off; None when m cut the word
        s, e, _ = SRC[i]
        return None if m.to_cut((s + e) / 2) is None else (place(m, e, -1) if end else place(m, s, 1)) + off

    o = lambda i, off=0.0, end=False: r3(at(old, i, off, end))  # noqa: E731  (times as the planners write them)

    def plans():
        tpl = [{"template": "card", "start": o(2, -0.067), "end": o(4, end=True), "file": "c.html", "checks": [o(3), o(4)]},
               {"template": "steps", "start": o(5, -0.05), "end": o(8, 0.05, True),
                "items": [{"text": "a", "at": o(5)}, {"text": "b", "at": o(6)}, {"text": "c", "at": o(8)}]},
               {"template": "tag", "start": o(9, -0.05), "end": o(10, end=True),
                "tags": [{"text": "Do this", "at": o(9), "until": o(10, end=True)}]},
               {"template": "tag", "start": o(0, -0.05), "end": o(0, end=True),     # "So" is short, then the put-back "the"
                "tags": [{"text": "So", "at": o(0), "until": o(0, end=True)}]},
               {"template": "tag", "start": o(6, -0.05), "end": o(6, end=True),     # "learn" is short, then the cut "is"
                "tags": [{"text": "learn", "at": o(6)}]}]
        kin = {"moments": [{"start": o(a), "end": o(b, end=True), "text": t} for a, b, t in KIN]}
        # cues where suggest_sfx puts them: a part appears + LAND + a frame; a kinetic word 0.05 s early + a frame
        sfx = [{"at": r3(t + frame), "sound": "pop", "why": why} for t, why in
               [(m["start"] - 0.05, m["text"]) for m in kin["moments"]] +
               [(tpl[0]["start"] + LAND, "card"), (tpl[1]["start"] + LAND, "steps")] +
               [(x["at"] + LAND, x["text"]) for sp in tpl[1:] for x in sp.get("items", []) + sp.get("tags", [])]]
        words = [{"start": o(i), "end": o(i, end=True), "word": w} for i, (_, _, w) in enumerate(SRC) if at(old, i)]
        cap = {"style": "apple", "fps": 30, "width": 1080, "height": 1920, "chunks": plan_captions(words, "apple", 30, True)}
        reel = {**cap, "style": "reel", "chunks": plan_captions(words, "reel", 30, True)}
        run = {"windows": {"cutaway": [{"start": tpl[1]["start"], "end": tpl[1]["end"], "kind": "steps"}],
                           "overlay": [{"start": tpl[2]["start"], "end": tpl[2]["end"], "kind": "tag"},
                                       {"start": o(8), "end": o(10, end=True), "kind": "kinetic"}]}}
        beh = {"moments": [{"start": o(6), "end": o(6, end=True), "text": "LEARN"},
                           {"start": o(0), "end": o(2, end=True), "text": "SO THE"}]}
        return tpl, kin, beh, sfx, cap, reel, run, words

    for label_, new in cuts.items():
        e = lambda i, off=0.0, end=False: at(new, i, off, end)  # noqa: E731
        extra = label_ == "extra cut"
        rt, say = Retimer(old, new, src), []
        tpl, kin, beh, sfx, cap, reel, run, words = plans()
        tpl, n, _ = templates(tpl, rt, say)
        card, steps = tpl[0], tpl[1]
        assert near(card["start"], e(2, -0.067)), (label_, card)          # its lead stays on the second "the"
        assert near(card["end"], e(4, end=True)) and all(near(x, e(i)) for x, i in zip(card["checks"], (3, 4)))
        assert near(steps["start"], e(5, -0.05)) and near(steps["end"], e(8, 0.05, True)), (label_, steps)
        assert all(near(x["at"], e(i)) for x, i in zip(steps["items"], (5, 6, 8)))
        if extra:
            assert n == 4 and any('Dropped tag "Do this"' in s for s in say), say
        else:
            tag = tpl[2]
            assert near(tag["start"], e(9, -0.05)) and near(tag["tags"][0]["until"], e(10, end=True))
        kin, n, _ = moments(kin, rt, say, "kinetic text")
        gone = {"is simple", "simple. do this", "Do this"} if extra else set()
        assert [(m["text"], m["start"], m["end"]) for m in kin["moments"]] == \
            [(t, r3(e(a)), r3(e(b, end=True))) for a, b, t in KIN if t not in gone], kin
        beh, _, _ = moments(beh, rt, say, "text behind")
        assert near(beh["moments"][0]["start"], e(6)) and near(beh["moments"][0]["end"], e(6, end=True))
        spec = morph(f"{num(o(8, -0.15))}-{num(o(10, end=True))}", rt, say)
        a, b = (float(x) for x in spec.split("-"))
        assert near(a, e(8, -0.15)) and near(b, e(10, end=True)), (label_, spec)
        run, n, total = run_windows(run, rt, say)                     # the kinetic window goes with its moment
        assert near(run["windows"]["cutaway"][0]["start"], e(5, -0.05)) and (n, total) == ((1, 3) if extra else (3, 3))
        # each sound keeps its distance to its graphic, even inside a short word whose neighbour comes back or goes
        sfx, n, _ = sounds(sfx, rt, say)
        want = {"best way": (3, -0.05), "is simple": (7, -0.05), "simple. do this": (8, -0.05), "every day": (11, -0.05),
                "card": (2, -0.067 + LAND), "steps": (5, -0.05 + LAND), "a": (5, LAND), "b": (6, LAND), "c": (8, LAND),
                "Do this": (9, LAND), "So": (0, LAND), "learn": (6, LAND)}
        assert sorted(c["why"] for c in sfx) == sorted(set(want) - gone), (label_, sfx)
        assert all(near(c["at"], e(*want[c["why"]]) + frame) for c in sfx), (label_, sfx)
        for plan in (cap, reel):                 # each caption leads into its first word as before; no two at once
            plan, n, total = captions(plan, rt, say)
            assert extra or n == total, (n, total)                   # a caption split around "the" counts once
            starts = sorted(x for i in range(len(SRC)) if (x := e(i)) is not None)
            for c in plan["chunks"]:
                first = starts[bisect.bisect_left(starts, c["start"] - EPS)]
                assert near(first - c["start"], 2 * frame), (label_, plan["style"], c)
            assert all(c["end"] <= d["start"] + EPS for c, d in zip(plan["chunks"], plan["chunks"][1:]))
            text = " ".join(c["text"] for c in plan["chunks"]).lower().split()
            assert text.count("the") == (1 if extra else 2) and ("is" in text) != extra and ("do" in text) != extra, text
            for c in plan["chunks"]:
                assert all(any(near(w["start"], x) for x in starts) for w in c.get("words", [])), c
        # captions that --hide-during started late: on "is" (it goes when "is" is cut, as "learn" is said before it),
        # and after "way." (it stays after its word, whatever the cut)
        hid = {"fps": 30, "chunks": [
            {"start": o(4, 0.05, True), "end": o(4, 0.35, True), "text": "way.", "words": [
                {"start": o(4), "end": o(4, end=True), "word": "way."}]},
            {"start": o(6, end=True), "end": o(7, end=True), "text": "learn is", "words": [
                {"start": o(6), "end": o(6, end=True), "word": "learn"}, {"start": o(7), "end": o(7, end=True), "word": "is"}]}]}
        hid, n, _ = captions(hid, rt, say)
        assert n == len(hid["chunks"]) == (1 if extra else 2), hid
        assert near(hid["chunks"][0]["start"], e(4, 0.05, True)) and near(hid["chunks"][0]["end"], e(4, 0.35, True)), hid
        assert extra or near(hid["chunks"][1]["start"], e(6, end=True)), hid
        assert any("runs over words put back" in s for s in say) != extra, say      # text behind "So the the"
        w_old = json.loads(json.dumps({"words": words, "audio_duration_secs": r3(old.duration)}))
        assert words_on(w_old, rt) == "old"
        w_new, _, _ = word_file(w_old, rt)
        assert words_on(w_new, rt) == "new" and w_new["audio_duration_secs"] == r3(new.duration)
        assert all(any(near(w["start"], e(i)) for i in range(len(SRC))) for w in w_new["words"])
    assert near(Retimer(old, cuts["put back"]).move(o(12))[0], at(cuts["put back"], 12))   # no words known: by the cut
    assert Retimer(old, cuts["put back"], src).back                 # the put-back "the" is found ...
    assert Retimer(old, cuts["extra cut"], src).back == []          # ... and nothing comes back in an extra cut
    # pacing: Whisper runs "do" on from the end of "so" (0.7) across a pause; "do" is heard at 3.1. Tight to gentle
    # and back, it stays a kept word (on the tight cut its middle is in air), a card 0.29 s and a sound 0.12 s before
    # it stay so, and "do" itself, or text shown from 0.8 (0.8 s before "do" when gentle), still starts after "so" ends
    tight, gentle = TimeMap.from_cuts([(0.95, 3.0)], 4.0), TimeMap.from_cuts([(1.2, 2.7)], 4.0)
    for a, b in ((tight, gentle), (gentle, tight)):
        mid = a.to_source((0.7 + a.to_cut(3.3)) / 2)               # as source_words finds it
        rt = Retimer(a, b, [(0.5, 0.7, 0.6, "so"), (0.7, 3.3, mid, "do")])
        for lead in (0.29, 0.12):
            assert near(rt.move(a.to_cut(3.1) - lead)[0], b.to_cut(3.1) - lead), (b is tight, lead)
        assert all(rt.move(t)[0] >= rt.move(0.7, end=True)[0] - EPS for t in (0.7, 0.8)), b is tight
    # a morph window lands on its number (a chart: --at = the number - 0.2 s; a ring: the number - 1.8 s) or, with no
    # number, the word just after its start (a check: the verdict - 0.6 s). Cut that word and the window and its sound
    # go, though the short word before it stays; cut a word later on, or a ring's lead-in, and the window stays
    full = TimeMap([(0.0, 14.0)])
    ring = [(9.5, 9.82, 9.66, "It"), (9.82, 10.0, 9.91, "takes"), (10.0, 10.3, 10.15, "10"), (10.3, 10.8, 10.55, "minutes."),
            (11.0, 11.3, 11.15, "and"), (11.4, 12.4, 11.9, "done."), (8.1, 8.3, 8.2, "it"), (8.88, 9.2, 9.04, "free,")]
    for spec, cut, gone in (("9.8-12.4", (10.0, 10.8), True), ("8.28-9.4", (8.88, 9.2), True), ("9.8-12.4", (11.0, 11.3), False),
                            ("8.2-11.2", (10.0, 10.8), True), ("8.2-11.2", (8.88, 9.2), False)):
        rt, say = Retimer(full, TimeMap.from_cuts([cut], 14.0), ring), []
        a, b = map(float, spec.split("-"))
        assert (morph(spec, rt, say) == "") == gone and any("Dropped morph window" in s for s in say) == gone, (spec, say)
        win = {"windows": {"cutaway": [], "overlay": [{"start": a, "end": b, "kind": "morph"}]}}
        assert run_windows(win, rt, say)[1] == (0 if gone else 1), (spec, win)          # the run file agrees
        assert sounds([{"at": a + 0.163, "sound": "riser"}], rt, say)[1] == (0 if gone else 1), (spec, say)
    file_test(old, cuts["put back"], DEAD, SRC, plans, at)
    media_test()
    print("retime self-test: OK")
    return 0


def file_test(old, new, dead, words, plans, at) -> None:
    """The command on files: --save, dry run, --out-dir, in place with backups, a second run, a second re-cut,
    another video's plans, a broken plan, stale mistake cuts and a missing saved cut."""
    quiet = lambda **kw: _quiet(retime, "x", **kw)  # noqa: E731
    d_map = TimeMap.from_cuts(dead, 8.0)
    da = lambda s: r3(d_map.to_cut(s))  # noqa: E731  (source -> dead-air cut seconds)
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "work"
        (w / "reports").mkdir(parents=True)
        (Path(d) / "input").mkdir()
        put = lambda name, data: (w / name).write_text(json.dumps(data, indent=1), encoding="utf-8")  # noqa: E731
        snap = lambda: {p.name: p.read_bytes() for p in w.glob("*.json")}  # noqa: E731

        def edl(*cuts):                    # the mistake cuts, on the dead-air cut (source stretches in, as apply-cuts)
            m = TimeMap.from_cuts([(da(a), da(b)) for a, b in cuts], d_map.duration)
            put("x.mistakes-edl.json", {"source_duration": r3(d_map.duration),
                                        "keep_ranges": [{"start": a, "end": b} for a, b in m.keeps]})
        put("reports/x.json", {"duration_before": 8.0, "cuts": [list(c) for c in dead]})
        transcript = {"audio_duration_secs": r3(d_map.duration), "words": [
            {"text": t, "start": da(s), "end": da(e), "type": "word"} for s, e, t in words]}
        put("x.transcript.json", transcript)
        edl((0.75, 0.95))                                          # the cut the plans are made on
        code, out = _quiet(save_cut, "x", w)
        assert code == 0 and same(TimeMap.read(w / "x.cutmap.json"), old) and "13 words" in out, out
        tpl, kin, beh, sfx, cap, _, run, _ = plans()
        for name, data in (("x.templates.json", tpl), ("x.k.emphasis.json", kin), ("x.behind.json", beh),
                           ("x.sfx.json", sfx), ("x.s.captions.json", cap), ("x.run.json", run),
                           ("x.v2.emphasis.json", kin)):          # x.v2 is another video (input/x.v2.mp4)
            put(name, data)
        (Path(d) / "input" / "x.v2.mp4").write_bytes(b"")
        put("x.mistakes-transcript.json", {"audio_duration_secs": r3(new.duration), "words": [   # W, from the re-cut
            {"text": t, "start": r3(at(new, i)), "end": r3(at(new, i, end=True))} for i, (_, _, t) in enumerate(words)]})
        edl()                                                      # the re-cut: the stutter put back
        fresh = json.loads(json.dumps(transcript))                 # a fresh transcription starts "the" in air the old
        fresh["words"][2]["start"] = da(0.85)                      # cut removed: the saved words must win
        put("x.transcript.json", fresh)
        before = snap()
        code, out = _quiet(save_cut, "x", w)                       # saving now would lose the cut the plans are on
        assert code == 2 and "retime.py x" in out and snap() == before, out
        kw = dict(work=w, words_file=w / "x.mistakes-transcript.json", morph_spec="3.4-4.9")
        for bad in (dict(kw, morph_spec="3.4"), dict(kw, words_file=w / "nope.json")):     # refused before any write
            code, out = quiet(**bad)
            assert code == 2 and snap() == before, out
        code, out = quiet(dry_run=True, **kw)
        assert code == 0 and "Dry run" in out and "Put back: 0.20 s" in out and snap() == before, out
        code, out = quiet(out_dir=w / "retimed", **kw)
        assert code == 0 and (w / "retimed" / "x.templates.json").is_file() and (w / "retimed" / "x.cutmap.json").is_file()
        assert snap() == before, "--out-dir changed work/"
        real = Path.write_text                                     # the last write fails (a full disk): every plan
        def full_disk(self, *a, **k):                              # written before it goes back, with no backups left
            if self.name == "x.cutmap.json":
                raise OSError("simulated full disk")
            return real(self, *a, **k)
        Path.write_text = full_disk
        try:
            code, out = quiet(**kw)
        finally:
            Path.write_text = real
        assert code == 2 and "Nothing was moved" in out and snap() == before, out
        code, out = quiet(**kw)
        assert code == 0 and "already timed on the new cut" in out and "from x.cutmap.json" in out, out
        assert "x.v2" not in out and (w / "x.v2.emphasis.json").read_bytes() == before["x.v2.emphasis.json"], out
        assert (w / "x.templates.pre-retime.json").read_bytes() == before["x.templates.json"]
        assert TimeMap.read(w / "x.cutmap.json").keeps == new.keeps
        assert (w / "x.mistakes-transcript.json").read_bytes() == before["x.mistakes-transcript.json"]
        card = read_json(w / "x.templates.json")[0]
        assert abs(card["start"] - (at(new, 2) - 0.067)) <= 1 / 30, card       # on the saved words, not the fresh ones
        after = snap()
        code, out = quiet(**kw)
        assert code == 0 and "nothing to move" in out and snap() == after, out
        code, out = _quiet(save_cut, "x", w)                       # the saved words stay, fresh transcript or not
        assert code == 0 and "left as it is" in out and snap() == after, out
        edl((6.0, 6.25))                                           # a second re-cut: "do" too. The first originals stay
        code, out = quiet(**kw)
        assert code == 0 and "Dropped tag" in out and "pre-retime-2" in out, out
        assert (w / "x.templates.pre-retime.json").read_bytes() == before["x.templates.json"]
        assert (w / "x.templates.pre-retime-2.json").read_bytes() == after["x.templates.json"]
        put("x.templates.json", [1, 2])                            # a broken plan is left alone, the rest still move
        (w / "x.behind.json").write_text('{"moments": [', encoding="utf-8")       # one cut short too
        edl()
        code, out = quiet(**kw)
        assert code == 0 and "x.templates.json: could not be read" in out and "x.k.emphasis.json: 3 of 3" in out, out
        assert "x.behind.json: could not be read" in out, out
        put("reports/x.json", {"duration_before": 9.0, "cuts": [list(c) for c in dead]})   # a re-cut dead air pass
        code, out = quiet(**kw)
        assert code == 2 and "Run steps 3 and 4 again" in out, out
        (w / "reports" / "x.json").write_text('{"duration_before": 8.0, "cu', encoding="utf-8")   # a damaged cut list
        for fn in (lambda: quiet(**kw), lambda: _quiet(save_cut, "x", w)):     # named plainly (main prints it, exit 2)
            try:
                fn()
                raise AssertionError("a damaged cut list must stop retime")
            except RuntimeError as e:
                assert "reports/x.json is damaged" in str(e), e
        (w / "x.cutmap.json").unlink()
        code, out = quiet(**kw)
        assert code == 2 and "--save" in out, out


def media_test() -> None:
    """A dead-air cut whose picture runs 0.3 s past its sound: its mistake cuts aren't stale and its transcript is
    read, as both state the sound's length, even when its report names a folder that has since moved. With no plans,
    only the saved cut changes."""
    from vtools import find_tool, run as run_cmd
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "work"
        (w / "reports").mkdir(parents=True)
        video = w / "x.mp4"
        res = run_cmd([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=3.3",
                       "-f", "lavfi", "-i", "sine=f=440:r=16000:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", str(video)])
        assert res.returncode == 0, res.stderr
        heard = probe(video).audio_duration
        put = lambda name, data: (w / name).write_text(json.dumps(data), encoding="utf-8")  # noqa: E731
        put("reports/x.json", {"duration_before": 3.3, "cuts": [], "output": str(Path(d) / "moved" / "x.mp4")})
        put("x.transcript.json", {"audio_duration_secs": r3(heard), "words": [{"text": "hi", "start": 2.2, "end": 2.6}]})
        put("x.mistakes-edl.json", {"source_duration": r3(heard), "keep_ranges": [{"start": 0, "end": 2.0}]})
        put("x.cutmap.json", {"keeps": [[0, 3.3]]})
        assert stale_mistakes(w, "x") is None
        put("x.run.json", {"windows": {"cutaway": [], "overlay": []}})        # a run file with no windows yet: no plan
        code, out = _quiet(save_cut, "x", w, dry_run=True)
        assert code == 0 and "Would save" in out, out
        put("x.run.json", {"windows": {"cutaway": [], "overlay": [{"start": 2.3, "end": 2.6, "kind": "morph"}]}})
        code, out = _quiet(save_cut, "x", w)                       # its morph windows are timed on the saved cut
        assert code == 2 and "retime.py x" in out, out
        (w / "x.run.json").unlink()
        code, out = _quiet(retime, "x", w)
        assert code == 0 and "(1 word from x.transcript.json)" in out and "No plans for x" in out, out
        assert "Nothing else to move" in out and same(TimeMap.read(w / "x.cutmap.json"), TimeMap([(0, 2.0)])), out
        put("x.mistakes-edl.json", {"source_duration": r3(heard - 1), "keep_ranges": [{"start": 0, "end": 1.0}]})
        assert "Run steps 3 and 4 again" in (stale_mistakes(w, "x") or "")


def _quiet(fn, *args, **kw) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kw)
    return code, buf.getvalue()


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Move every plan's times onto a new cut, keeping each on its word.")
    p.add_argument("name", nargs="?", help="the video's name in work/ (input/talk.mov -> talk)")
    p.add_argument("--save", action="store_true",
                   help="save the cut and its words as the ones the plans are timed on (once, before planning)")
    p.add_argument("--old", type=Path, help="the cut the plans were made on (default: work/<name>.cutmap.json)")
    p.add_argument("--new", type=Path, help="the new cut, as a cut map file (default: work/<name>'s cut lists now)")
    p.add_argument("--words", type=Path, help="the word timings W: moved too unless the re-cut already wrote them anew")
    p.add_argument("--morph", default="", help="morph windows 'at-end,...' on the old cut; the moved string is printed")
    p.add_argument("--out-dir", type=Path, help="write the moved plans here and leave work/ as it is")
    p.add_argument("--dry-run", action="store_true", help="show what would move, write nothing")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.name:
        p.error("give the video's name, or --self-test")
    work = project_root() / "work"
    try:
        if args.save:
            return save_cut(args.name, work, args.words, args.dry_run)
        return retime(args.name, work, args.old, args.new, args.words, args.morph, args.out_dir, args.dry_run)
    except RuntimeError as e:            # a damaged cut list, words file or saved cut
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
