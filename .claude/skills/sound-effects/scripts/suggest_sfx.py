#!/usr/bin/env python3
"""Plan sound effects on a video's graphics: one cue per visual hit, in work/<name>.sfx.json.

Reads the graphics plans the automatic edit already wrote (templates and designed cards,
kinetic-text moments, morph-chart windows), finds the moment each one lands on screen,
and picks a sound for it: a whoosh when a card or template enters, a pop when a pill,
tag or count lands, a soft tick when a list line appears, an impact on the one
full-screen statement. Then it keeps the strongest hits (no stacking, a cap per minute),
rotates the takes, and sets each level relative to the speaker's voice.

The sounds are the 21 free Pixabay effects inside the hyperframes npm package. They are read
from node_modules at run time and never copied into this folder: the Pixabay licence does not
allow passing them on as standalone files. A finished video that uses them is fine.

Examples (from the project folder)
  PY .claude/skills/sound-effects/scripts/suggest_sfx.py work/talk.t.mp4 --templates work/talk.templates.json
  PY .claude/skills/sound-effects/scripts/suggest_sfx.py V --templates work/talk.templates.json \
     --emphasis work/talk.emphasis.json --morph "2.9-5.9,8.2-10.8" --words work/talk.words.json

Each cue: {"at": 8.733, "sound": "whoosh-short", "gain_db": -12.4, "why": "card c01-stat enters"}
`at` is when the sound's peak plays (one frame after the picture lands). An optional "rate"
(1.06 or 0.94) replays a take slightly higher or lower so a repeat never sounds identical.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "video-editor" / "scripts"))
from vtools import SETUP_HINT, SetupError, find_tool, probe, project_root  # noqa: E402

SFX_REL = Path("node_modules/hyperframes/dist/skills/media-use/audio/assets/sfx")

# family: (takes in rotation order, level vs the voice in dB, priority: lower wins a clash)
# whoosh.mp3 = whoosh-short.mp3 and click.mp3 = click-soft.mp3 byte for byte, so each counts as one take.
FAMILIES = {
    "impact": (["impact-bass-1", "impact-bass-2"], -6, 0),  # mostly under 150 Hz: phone speakers play it softer
    "whoosh": (["whoosh-short"], -10, 1),
    "pop": (["pop"], -9, 2),
    "tick": (["click-soft", "key-press"], -12, 3),           # bright and sharp: cuts through even when quiet
    "tap": (["click"], -10, 3),
}
RATES = [1.0, 1.06, 0.94]   # a take's 2nd and 3rd round play about a semitone up / down
MIN_GAP = 0.6               # s between two hits; closer ones stack into one smear
CUTAWAY_DUCK = 3.0          # dB off a cue on a spoken word in a cutaway: the face is gone, nobody can lip-read
WIN = 0.03                  # RMS window (s) for every level and peak time here
SEEN = 0.8                  # an entrance reads as "landed" once it is 80% of the way in (checked on rendered frames)
LAND = 0.13                 # shortcut: motion-templates entrances (0.4-0.45 s, back.out) reach 80% ~0.13 s in, measured; re-measure if templates/*.py change
CUTAWAY_TEMPLATES = {"flowchart", "compare", "chapter"}
KINETIC = {"pop": "pop", "slam": "pop", "typewriter": "tick", "highlight": "tick", "stack": "whoosh"}


def sfx_dir() -> Path:
    d = project_root() / SFX_REL
    if not (d / "manifest.json").is_file():
        raise SystemExit(f"The free sound effects were not found in {d}.\n"
                         f"They come with HyperFrames (npm install, part of the setup). {SETUP_HINT}")
    return d


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((sfx_dir() / "manifest.json").read_text(encoding="utf-8"))


def mono_pan(channels: int) -> str:
    """The plain average of all channels; add_sfx mixes with the same downmix this measures."""
    n = max(1, channels)
    return "pan=mono|c0=" + "+".join(f"{1 / n:.6g}*c{i}" for i in range(n))


def decode(path: Path, sr: int) -> np.ndarray:
    """First audio stream as mono float32 at `sr`."""
    res = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:a:0", "-af",
                          mono_pan(probe(path).audio_channels), "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True)
    if res.returncode != 0:
        raise SystemExit(f"Could not read the audio of {path}: {res.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(res.stdout, dtype=np.float32)


def envelope(x: np.ndarray, sr: int, hop: float) -> tuple[np.ndarray, np.ndarray]:
    """RMS in dBFS over WIN-long windows every `hop` s: (window centre times, dB)."""
    w, h = max(1, int(WIN * sr)), max(1, int(hop * sr))
    cs = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    starts = np.arange(0, max(1, len(x) - w + 1), h)
    ends = np.minimum(starts + w, len(x))
    rms = np.sqrt(np.maximum((cs[ends] - cs[starts]) / w, 1e-12))
    return (starts + w / 2) / sr, 20 * np.log10(rms)


@lru_cache(maxsize=None)
def measure(sound: str) -> tuple[float, float]:
    """(seconds from the file's start to its loudest 30 ms, that window's level in dBFS), read with ffmpeg."""
    if sound not in manifest():
        raise SystemExit(f"Unknown sound '{sound}'. Choose from: {', '.join(sorted(manifest()))}")
    t, db = envelope(decode(sfx_dir() / manifest()[sound]["file"], 48000), 48000, 0.001)
    i = int(np.argmax(db))
    return float(t[i]), float(db[i])


def speech_level(video: Path) -> float:
    """The voice's loud syllables: 90th percentile of the 30 ms RMS over the parts above -50 dBFS."""
    _, db = envelope(decode(video, 16000), 16000, 0.01)
    voiced = db[db > -50]
    if voiced.size < 10:
        raise SystemExit(f"{video.name} has no speech loud enough to set sound levels against.")
    return float(np.percentile(voiced, 90))


def gain_db(speech_db: float, rel_db: float, sfx_db: float) -> float:
    """Gain that puts the sound's loudest 30 ms `rel_db` away from the voice's loud syllables."""
    return round(speech_db + rel_db - sfx_db, 1)


def file_start(at: float, peak: float, rate: float = 1.0) -> float:
    """Where the file must start so its peak (moved by the playback rate) plays at `at`."""
    return at - peak / rate


# ---------------------------------------------------------------- where the picture lands

def ease_time(ease: str, q: float) -> float:
    """Share of a GSAP '.out' tween's duration at which its progress reaches q."""
    name = ease.split(".")[0].split("(")[0]
    if name == "expo":
        return -math.log2(1 - q) / 10
    if name == "sine":
        return math.asin(q) * 2 / math.pi
    if name in ("none", "linear"):
        return q
    power = {"back": 3}.get(name, int(name[5:]) if name[5:].isdigit() else 1)  # GSAP's default ease is power1.out
    return 1 - (1 - q) ** (1 / (power + 1))


def card_events(spec: dict, name: str) -> list[dict]:
    """Hits from a designed card's GSAP lines: entrances that move, and count-ups landing."""
    text = spec.get("html") or ""
    if not text and spec.get("file"):
        f = Path(spec["file"])
        f = f if f.is_absolute() else project_root() / f
        text = f.read_text(encoding="utf-8") if f.is_file() else ""
    start, cutaway = float(spec["start"]), spec.get("mode") == "cutaway"
    found = []
    for m in re.finditer(r"tl\.(?:fromTo|from)\((.*?)\)\s*;", text, re.S):
        args = m.group(1).replace(" ", "")
        pos = re.search(r",([\d.]+)$", args)          # shortcut: relative positions ("<", "+=0.2") are skipped
        dur = re.search(r"duration:([\d.]+)", args)
        sel = re.match(r"[\"']([^\"']+)", args)
        if not (pos and sel):
            continue
        at, d, sel = float(pos.group(1)), float(dur.group(1)) if dur else 0.5, sel.group(1)
        e = re.search(r"ease:[\"']([\w.()]+)", args)
        ease = e.group(1) if e else "power1.out"
        if "innerText" in args:
            # a snapped count shows its last number once the tween passes N - 0.5, well before it ends
            n = max(float(v) for v in re.findall(r"innerText:([\d.]+)", args))
            q = 1 - 0.5 / n if "snap" in args and n >= 1 else 0.99
            found.append({"t": start + at + ease_time(ease, q) * d, "family": "pop",
                          "why": f"card {name}: count lands on {n:g}", "kind": "count"})
        elif re.search(r"opacity:0[,}]", args) and re.search(r"(?<![a-zA-Z])(x|y|scale):|blur\(", args):
            found.append({"t": start + at + ease_time(ease, SEEN) * d, "order": at, "sel": sel, "blur": "blur(" in args,
                          "family": "pop" if "scale:" in args else "tick", "kind": "entrance",
                          "why": f"card {name}: {sel} " + ("pops in" if "scale:" in args else "appears")})
    entrances = sorted((e for e in found if e["kind"] == "entrance"), key=lambda e: e["order"])
    if entrances:
        first = entrances[0]
        first.update(family="whoosh", why=f"card {name} enters" + (" (full screen)" if cutaway else ""))
        if cutaway:
            hero = next((e for e in entrances if e["blur"]), first)
            hero.update(family="impact", why=f"card {name}: full-screen statement lands ({hero['sel']})")
    else:  # unreadable card or no moving entrance: one cue as it comes in
        found.append({"t": start + LAND, "family": "impact" if cutaway else "whoosh", "why": f"card {name} enters"})
    return found


def template_events(spec: dict) -> list[dict]:
    kind, start = spec["template"], float(spec["start"])
    a = float(spec.get("at", start))
    if kind == "card":
        return card_events(spec, Path(spec.get("file", "")).stem or f"at {start:g}")
    if kind == "cta":
        return [{"t": a + 0.2 + LAND, "family": "pop", "why": "save / follow button pops in"},
                {"t": a + 1.12, "family": "tap", "why": "save / follow button is tapped"}]
    statement = kind == "quote" and spec.get("mode") != "overlay"
    ev = [] if kind == "tag" else [{"t": a + LAND, "family": "impact" if statement else "whoosh",
                                     "why": f"{kind} enters" + (" (full-screen statement)" if statement else "")}]
    for i, it in enumerate(spec.get("items", []), 1):
        ev.append({"t": float(it["at"]) + LAND, "family": "tick", "why": f"{kind} item {i} appears"})
    for side in ("left", "right"):
        col = spec.get(side) or {}
        for i, it in enumerate(col.get("items", []), 1):
            ev.append({"t": float(it["at"]) + LAND, "family": "tick", "why": f"compare {side} item {i} appears"})
    for g in spec.get("tags", []):
        ev.append({"t": float(g["at"]) + LAND, "family": "pop", "why": f"tag \"{g.get('text', '')}\" pops in"})
    for n in spec.get("nodes", []):
        ev.append({"t": float(n["at"]) + LAND, "family": "whoosh", "why": f"flowchart box \"{n.get('text', '')}\""})
        if n.get("sticker"):
            ev.append({"t": float(n["at"]) + 0.6 + LAND, "family": "pop", "why": f"sticker {n['sticker']} pops"})
    return ev


def cutaway_windows(specs: list[dict], morph: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Where the speaker's face is off screen. Morph windows count: 3 of the 5 morph charts are cutaways."""
    out = list(morph)
    for s in specs:
        k, mode = s["template"], s.get("mode")
        if k in CUTAWAY_TEMPLATES or (k in ("steps", "quote") and mode != "overlay") or mode == "cutaway":
            out.append((float(s["start"]), float(s["end"])))
    return out


def parse_windows(text: str) -> list[tuple[float, float]]:
    out = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        a, b = part.split("-", 1)
        out.append((float(a), float(b)))
    return out


def load_words(path: Path | None) -> list[dict]:
    if not path:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("words", [])


# ---------------------------------------------------------------- choosing and leveling

def select(events: list[dict], duration: float, per_minute: float, min_gap: float = MIN_GAP) -> list[dict]:
    """Keep the strongest hits: none within min_gap of another, at most per_minute in any minute
    (prorated for videos under a minute). One impact per video: the last statement, the payoff."""
    impacts = [e for e in sorted(events, key=lambda e: e["t"]) if e["family"] == "impact"]
    for e in impacts[:-1]:
        e["family"] = "whoosh"
    window = min(60.0, max(duration, 1.0))
    cap = max(1, round(per_minute * window / 60))
    kept: list[dict] = []
    for e in sorted(events, key=lambda e: (FAMILIES[e["family"]][2], e["t"])):
        if not 0.05 <= e["t"] <= duration - 0.1 or any(abs(e["t"] - k["t"]) < min_gap - 1e-6 for k in kept):
            continue
        times = sorted([k["t"] for k in kept] + [e["t"]])
        if max(sum(1 for u in times if s <= u < s + window) for s in times) <= cap:
            kept.append(e)
    return sorted(kept, key=lambda e: e["t"])


def assign_takes(cues: list[dict]) -> None:
    """Rotate each family's takes in time order; once every take is used, vary the rate."""
    used: dict[str, int] = {}
    for c in cues:
        takes = FAMILIES[c["family"]][0]
        k = used.get(c["family"], 0)
        used[c["family"]] = k + 1
        c["sound"] = takes[k % len(takes)]
        c["rate"] = RATES[(k // len(takes)) % len(RATES)]


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Plan free sound effects on a video's graphics.")
    p.add_argument("video", type=Path, help="the video the sounds go on (after the graphics passes)")
    p.add_argument("--templates", type=Path, help="work/<name>.templates.json (templates and designed cards)")
    p.add_argument("--emphasis", type=Path, help="work/<V-stem>.emphasis.json (kinetic-text moments)")
    p.add_argument("--morph", default="", help="morph-chart windows 'at-end,...', e.g. '2.9-5.9,8.2-10.8'")
    p.add_argument("--words", type=Path, help="word timings, so cues on a word in a cutaway play 3 dB lower")
    p.add_argument("--per-minute", type=float, default=15, help="most cues in any minute (default 15; 8 for long videos)")
    p.add_argument("--level", type=float, default=0.0, help="dB added to every cue: +3 louder, -3 quieter")
    p.add_argument("--out", type=Path, help="default: work/<name>.sfx.json next to the templates plan")
    args = p.parse_args()
    if not (args.templates or args.emphasis or args.morph):
        p.error("give at least one of --templates, --emphasis, --morph")

    sfx_dir()  # fail before any work when the sounds aren't installed
    info = probe(args.video)
    if not info.has_audio:
        raise SystemExit(f"{args.video.name} has no audio track to put sounds on.")
    frame = 1 / (info.fps or 30)
    specs = []
    if args.templates:
        data = json.loads(args.templates.read_text(encoding="utf-8"))
        specs = sorted(data if isinstance(data, list) else [data], key=lambda s: float(s["start"]))
    morph = parse_windows(args.morph)

    events = [e for s in specs for e in template_events(s)]
    for t, _ in morph:  # the first shape scales in at 0.1-0.15 s over 0.4 s (back.out): 80% in at ~0.25 s
        events.append({"t": t + 0.25, "family": "pop", "why": f"chart at {t:g} pops in"})
    if args.emphasis:
        for m in json.loads(args.emphasis.read_text(encoding="utf-8")).get("moments", []):
            fam = KINETIC.get(m.get("style", "pop"), "pop")
            # the text starts 0.15 s before its word and is 80% in about 0.1 s later
            events.append({"t": float(m["start"]) - 0.05, "family": fam,
                           "why": f"kinetic \"{m.get('text', '')}\" ({m.get('style', 'pop')})"})

    cues = select(events, info.duration, args.per_minute)
    assign_takes(cues)
    speech = speech_level(args.video)
    cutaways, words = cutaway_windows(specs, morph), load_words(args.words)
    plan = []
    for c in cues:
        peak, level = measure(c["sound"])
        g = gain_db(speech, FAMILIES[c["family"]][1] + args.level, level)
        why = c["why"]
        on = next((w for w in words if w["start"] <= c["t"] <= w["end"]), None)
        if on and any(a <= c["t"] <= b for a, b in cutaways):
            g = round(g - CUTAWAY_DUCK, 1)
            why += f"; on \"{on['word'].strip()}\" in a cutaway, {CUTAWAY_DUCK:g} dB lower"
        cue = {"at": round(c["t"] + frame, 3), "sound": c["sound"], "gain_db": g, "why": why}
        if c["rate"] != 1.0:
            cue["rate"] = c["rate"]
        if file_start(cue["at"], peak, c["rate"]) < 0:
            continue  # its build-up would start before the video does
        plan.append(cue)

    out = args.out
    if not out:
        base = args.templates or args.emphasis or Path("work") / args.video.name
        out = base.with_name(re.sub(r"(\.templates|\.emphasis)?\.(json|mp4|mov|mkv|m4v|webm)$", "", base.name) + ".sfx.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"Voice level (loud syllables): {speech:.1f} dBFS. {len(plan)} of {len(events)} possible cues kept "
          f"(at most {args.per_minute:g} a minute, {MIN_GAP} s apart).")
    for c in plan:
        print(f"  {c['at']:7.2f}s  {c['sound']:<14} {c['gain_db']:+6.1f} dB  {c['why']}")
    print(f"Plan: {out}  (edit or remove cues, then run add_sfx.py)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as err:
        sys.exit(str(err))
