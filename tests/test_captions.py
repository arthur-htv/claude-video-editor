"""Caption planner checks. Run: .venv/Scripts/python tests/test_captions.py (or .venv/bin/python)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude/skills/captions/scripts"))
from make_captions import hide_during, named_y, plan_captions  # noqa: E402


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


# No windows: nothing is dropped, however short.
short = [{"start": 1.0, "end": 1.1, "text": "get"}]
assert hide_during(short, "") == short

# A window that leaves only a sliver drops it; a caption outside every window stays.
chunks = [{"start": 1.0, "end": 2.0, "text": "a"}, {"start": 4.0, "end": 4.1, "text": "b"}]
kept = hide_during(chunks, "1.1-3.0")
assert [c["text"] for c in kept] == ["b"], kept

# A quick one-word phrase start ("get", 0.16 s) joins the next words instead of flashing alone,
# and every spoken word makes it into the plan.
words = [w("two,", 21.28, 21.56), w("get", 21.98, 22.14), w("a", 22.14, 22.26), w("secured", 22.26, 22.52),
         w("business", 22.52, 22.86), w("credit", 22.86, 23.2), w("card.", 23.2, 23.58)]
plan = plan_captions(words, "hand", 30, True)
assert sum(len(c["words"]) for c in plan) == len(words), plan
assert not any(c["text"].lower() == "get" for c in plan), [c["text"] for c in plan]

# --position: named places (bottom sits higher on a vertical video) or a share of the height
assert (named_y("bottom", True), named_y("bottom", False), named_y("top", True), named_y("0.7", True)) == (0.78, 0.86, 0.16, 0.7)

print("captions: all checks pass")
