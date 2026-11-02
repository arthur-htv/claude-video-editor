"""Sound-effects planner checks. Run: .venv/Scripts/python .claude/skills/sound-effects/scripts/test_sfx.py (or .venv/bin/python)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suggest_sfx import (FAMILIES, SFX_REL, assign_takes, card_events, ease_time, file_start, gain_db,  # noqa: E402
                         mono_pan, project_root, select)


def ev(t, family, why=""):
    return {"t": t, "family": family, "why": why}


# dB math: the sound's loudest 30 ms lands rel_db away from the voice's loud syllables.
assert gain_db(-15.8, -10, -8.6) == -17.2
assert gain_db(-20.0, -6, -3.3) == -22.7
# The file starts early by its peak offset; a faster rate brings the peak forward.
assert abs(file_start(8.633, 0.162) - 8.471) < 1e-9
assert abs(file_start(8.633, 0.162, 1.06) - (8.633 - 0.162 / 1.06)) < 1e-9
assert mono_pan(2) == "pan=mono|c0=0.5*c0+0.5*c1" and mono_pan(1) == "pan=mono|c0=1*c0"

# Ease curves: when an entrance is 80% in, and when a snapped count to 10 shows "10".
assert abs(ease_time("power3.out", 0.8) - 0.331) < 0.001
assert abs(ease_time("expo.out", 0.8) - 0.232) < 0.001
assert abs(ease_time("power2.out", 0.95) - 0.632) < 0.001
assert abs(ease_time("back.out(1.7)", 0.8) - ease_time("power3.out", 0.8)) < 1e-9

# No stacking: of two hits 0.3 s apart the stronger family wins; 0.6 s apart both stay.
kept = select([ev(5.0, "tick"), ev(5.3, "whoosh"), ev(9.0, "pop"), ev(9.6, "tick")], 30, 15)
assert [(k["t"], k["family"]) for k in kept] == [(5.3, "whoosh"), (9.0, "pop"), (9.6, "tick")], kept

# One impact per video: the last statement keeps it, earlier ones become whooshes.
kept = select([ev(3.0, "impact"), ev(20.0, "impact")], 30, 15)
assert [k["family"] for k in kept] == ["whoosh", "impact"], kept

# Cap per minute, prorated under a minute: 30 s at 15 a minute allows 8 (round(7.5)).
kept = select([ev(1.0 + i, "tick") for i in range(28)], 30, 15)
assert len(kept) == 8, len(kept)
# Over a long video no 60 s stretch holds more than the cap, but later minutes still get theirs.
kept = select([ev(1.0 + i, "pop") for i in range(180)], 200, 15)
times = [k["t"] for k in kept]
assert max(sum(1 for u in times if s <= u < s + 60) for s in times) <= 15
assert any(t > 120 for t in times) and len(kept) >= 40, len(kept)
# Strong hits survive the cap first: whooshes are kept over ticks.
kept = select([ev(1.0 + i, "tick") for i in range(10)] + [ev(1.5 + i, "whoosh") for i in range(10)], 12, 15)
assert all(k["family"] == "whoosh" for k in kept), kept

# Rotation: takes alternate, and a repeated take comes back at another rate, never identical twice running.
cues = [ev(i, "whoosh") for i in range(4)] + [ev(10 + i, "tick") for i in range(3)]
assign_takes(cues)
assert [c["rate"] for c in cues[:4]] == [1.0, 1.06, 0.94, 1.0]
assert [(c["sound"], c["rate"]) for c in cues[4:]] == [("click-soft", 1.0), ("key-press", 1.0), ("click-soft", 1.06)]
for x, y in zip(cues, cues[1:]):
    assert (x["sound"], x["rate"]) != (y["sound"], y["rate"]), (x, y)
assert all(len(set(t)) == len(t) for t, _, _ in FAMILIES.values())

# Cards: moving entrances and count landings; fades and tl.to lines are silent.
html = """<script>
tl.fromTo(".c09",{opacity:0,y:40,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.6,ease:"power3.out"},0.0);
tl.fromTo(".c09-pill",{opacity:0,scale:0.85},{opacity:1,scale:1,duration:0.45,ease:"power3.out"},1.0);
tl.fromTo(".c09-n",{innerText:0},{innerText:10,duration:1.4,ease:"power2.out",snap:{innerText:1}},0.2);
tl.fromTo(".c09-sub",{opacity:0},{opacity:1,duration:0.4},2.0);
tl.to(".c09-pill",{opacity:0.4,duration:0.4},3.0);
</script>"""
e = sorted(card_events({"template": "card", "start": 10.0, "end": 14.0, "html": html}, "c09"), key=lambda x: x["t"])
assert [x["family"] for x in e] == ["whoosh", "pop", "pop"], e
count = next(x for x in e if x["kind"] == "count")
assert abs(e[0]["t"] - (10.0 + 0.331 * 0.6)) < 0.002 and abs(count["t"] - (10.0 + 0.2 + 0.632 * 1.4)) < 0.002, e
# A full-screen card puts the one impact on its blurred hero, not on the small line before it.
cut = """tl.fromTo(".a",{opacity:0,y:20},{opacity:1,y:0,duration:0.5,ease:"power3.out"},0.05);
tl.fromTo(".n",{opacity:0,scale:0.92,filter:"blur(16px)"},{opacity:1,scale:1,filter:"blur(0px)",duration:0.7,ease:"expo.out"},0.35);"""
e = card_events({"template": "card", "start": 0, "end": 3, "mode": "cutaway", "html": cut}, "c10")
assert [(x["sel"], x["family"]) for x in e] == [(".a", "whoosh"), (".n", "impact")], e

# The cap: each graphic's lead hit comes before a card's later pops, so no graphic goes silent (12 s: cap 3).
card = [dict(ev(1.0 + i, "whoosh" if i == 0 else "pop"), graphic=0) for i in range(4)]
kept = select(card + [dict(ev(8.0, "pop"), graphic=1), dict(ev(10.0, "tap"), graphic=2)], 12, 15)
assert [k["t"] for k in kept] == [1.0, 8.0, 10.0], kept

# The real sounds: present only after setup's npm install, so this part needs node_modules.
if (project_root() / SFX_REL / "manifest.json").is_file():
    from add_sfx import filter_graph
    cue = {"sound": "pop", "gain_db": -12.3, "start": 2.0, "rate": 1.06}
    inputs, graph = filter_graph([cue], 48000, 2, "stereo", 0.0)
    assert inputs[-1].endswith("pop.mp3") and "volume=-12.30dB" in graph and "adelay=96000S" in graph
    assert "asetrate=50880" in graph and "normalize=0" in graph and "duration=first" in graph, graph
    assert "atrim=start=0.50000" in filter_graph([dict(cue, start=-0.5)], 48000, 1, "mono", -1.0)[1]

print("sound-effects: all checks pass")
