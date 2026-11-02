#!/usr/bin/env python3
"""Map times between a source video and its cut, from the cut lists the two cutters save.

/video-editor:auto cuts in two passes, and each pass saves what it did:
  - cut_dead_air.py -> work/reports/<name>.json: "cuts" (removed, in source seconds) and "duration_before"
  - apply-cuts.mjs  -> work/<name>.mistakes-edl.json: "keep_ranges" (kept, in seconds of the dead-air cut)
Composed, they give one list of kept pieces in source seconds. From that list: where the joins fall in
the cut video, and where any moment lands when the cut changes.

  python timemap.py <name>            kept pieces and joins of work/<name>'s current cut
  python timemap.py --self-test
(retime.py <name> --save writes work/<name>.cutmap.json, the cut the plans are timed on.)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vtools import project_root  # noqa: E402

EPS = 1e-6


class TimeMap:
    """The kept pieces of a source, in source seconds (sorted, not overlapping)."""

    def __init__(self, keeps):
        merged: list[tuple[float, float]] = []
        for a, b in sorted((float(a), float(b)) for a, b in keeps):
            if b - a <= EPS:
                continue
            if merged and a - merged[-1][1] <= EPS:       # pieces that touch are one piece, not a join
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        self.keeps = merged
        self.starts: list[float] = []                     # where each piece starts in the cut video
        t = 0.0
        for a, b in merged:
            self.starts.append(t)
            t += b - a
        self.duration = t

    @classmethod
    def from_cuts(cls, cuts, duration: float) -> "TimeMap":
        keeps, pos = [], 0.0
        for a, b in sorted((float(a), float(b)) for a, b in cuts):
            if a > pos:
                keeps.append((pos, a))
            pos = max(pos, b)
        if pos < duration:
            keeps.append((pos, float(duration)))
        return cls(keeps)

    @classmethod
    def read(cls, path) -> "TimeMap":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["keeps"])

    def to_json(self) -> dict:
        return {"keeps": [[round(a, 6), round(b, 6)] for a, b in self.keeps]}

    def joins(self) -> list[float]:
        """Times in the cut video where two kept pieces meet."""
        return self.starts[1:]

    def to_cut(self, t: float) -> float | None:
        """Source time -> cut time, or None when that moment was cut out."""
        for (a, b), s in zip(self.keeps, self.starts):
            if a - EPS <= t <= b + EPS:
                return s + min(max(t - a, 0.0), b - a)
        return None

    def to_source(self, t: float, end: bool = False) -> float:
        """Cut time -> source time. A time on a join belongs to the piece after it,
        or to the piece before it with end=True (use that for the end of a span)."""
        if not self.keeps:
            raise ValueError("this cut keeps nothing")
        t = min(max(float(t), 0.0), self.duration)
        last = len(self.keeps) - 1
        for i, ((a, b), s) in enumerate(zip(self.keeps, self.starts)):
            e = s + (b - a)
            if t < e - EPS or (end and t <= e + EPS) or i == last:
                return a + (t - s)
        raise AssertionError("unreachable")

    def then(self, later: "TimeMap") -> "TimeMap":
        """This cut, cut again: `later` keeps ranges of this map's cut video. Returns source pieces."""
        out = []
        for la, lb in later.keeps:
            for (a, b), s in zip(self.keeps, self.starts):
                lo, hi = max(la, s), min(lb, s + (b - a))
                if hi - lo > EPS:
                    out.append((a + lo - s, a + hi - s))
        return TimeMap(out)


def load(name: str, work: Path | str | None = None) -> TimeMap:
    """The current cut of work/<name>: the dead-air cut, then the mistake cuts on top. A pass whose
    file is missing counts as no cut. A file left from an older run is read like a current one.
    RuntimeError when the dead-air report is from a run that didn't finish (its cuts aren't in the video), or when
    a cut list is damaged (the message names it)."""
    work = Path(work) if work else project_root() / "work"
    report, edl = work / "reports" / f"{name}.json", work / f"{name}.mistakes-edl.json"
    m = None
    if report.is_file():
        try:
            r = json.loads(report.read_text(encoding="utf-8"))
            status = r.get("status", "done")
            if status != "done":
                raise RuntimeError(f"reports/{name}.json is from a dead-air run that ended '{status}', not from the "
                                   "cut video in work/: run the dead-air render (step 2) again with --overwrite.")
            m = TimeMap.from_cuts(r.get("cuts") or [], float(r["duration_before"]))
        except (ValueError, KeyError, TypeError, AttributeError) as x:
            raise RuntimeError(f"reports/{name}.json is damaged ({x}): run the dead-air render (step 2) again "
                               "with --overwrite.") from None
    if edl.is_file():
        try:
            e = json.loads(edl.read_text(encoding="utf-8"))
            later = TimeMap([(k["start"], k["end"]) for k in e["keep_ranges"]])
        except (ValueError, KeyError, TypeError, AttributeError) as x:
            raise RuntimeError(f"{edl.name} is damaged ({x}): run the mistake cuts' apply line (step 4) "
                               "again.") from None
        m = later if m is None else m.then(later)
    if m is None:
        raise FileNotFoundError(f"no cut lists for {name!r} in {work} "
                                f"(expected reports/{name}.json or {name}.mistakes-edl.json)")
    return m


def self_test() -> int:
    near = lambda x, y: x is not None and abs(x - y) < 1e-9  # noqa: E731
    m = TimeMap.from_cuts([(1, 2), (5, 6)], 10)
    assert m.keeps == [(0, 1), (2, 5), (6, 10)] and near(m.duration, 8) and m.joins() == [1, 4]
    assert m.to_cut(1.5) is None and near(m.to_cut(3), 2) and near(m.to_cut(5), 4) and near(m.to_cut(6), 4)
    assert near(m.to_source(4), 6) and near(m.to_source(4, end=True), 5) and near(m.to_source(99), 10)
    later = TimeMap([(0, 3), (3.5, 8)])                  # the mistake pass removes cut time 3-3.5
    both = m.then(later)
    assert both.keeps == [(0, 1), (2, 4), (4.5, 5), (6, 10)], both.keeps
    assert near(both.duration, 7.5) and both.joins() == [1, 3, 3.5]
    assert TimeMap([(0, 1), (1, 2)]).joins() == []       # touching pieces make no join
    put_back = TimeMap.from_cuts([(1, 2)], 10)            # a re-cut that restores 5-6
    assert near(put_back.to_cut(m.to_source(4.5)), 5.5)
    with tempfile.TemporaryDirectory() as d:
        w = Path(d)
        (w / "reports").mkdir()
        (w / "reports" / "x.json").write_text(json.dumps({"duration_before": 10, "cuts": [[1, 2], [5, 6]]}))
        (w / "x.mistakes-edl.json").write_text(json.dumps(
            {"keep_ranges": [{"start": 0, "end": 3}, {"start": 3.5, "end": 8}]}))
        assert load("x", w).keeps == both.keeps
        # A report from a preview or a failed render describes cuts the video doesn't have: refused, not read.
        for status, ok in (("done", True), ("analyzed", False), ("failed", False)):
            (w / "reports" / "y.json").write_text(json.dumps({"status": status, "duration_before": 10, "cuts": []}))
            try:
                assert load("y", w).keeps == [(0, 10)] and ok, status
            except RuntimeError as e:
                assert not ok and status in str(e), (status, e)
        # A damaged cut list gives a plain message naming it, not a traceback
        for f, text in ((w / "reports" / "z.json", '{"duration_before": 1'), (w / "z.mistakes-edl.json", "[]")):
            f.write_text(text)
            try:
                load("z", w)
                raise AssertionError(f"{f.name} should have been refused")
            except RuntimeError as e:
                assert f"{f.name} is damaged" in str(e), e
            f.unlink()
        (w / "x.cutmap.json").write_text(json.dumps(both.to_json()))
        assert TimeMap.read(w / "x.cutmap.json").keeps == both.keeps
        (w / "reports" / "x.json").unlink()
        assert load("x", w).keeps == [(0, 3), (3.5, 8)]   # mistake pass alone
    print("timemap self-test: OK")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Kept pieces and joins of a cut, from the saved cut lists.")
    p.add_argument("name", nargs="?", help="the video's name in work/ (work/<name>.mp4 is the dead-air cut)")
    p.add_argument("--work", type=Path, help="the work folder (default: work/ in the project)")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.name:
        p.error("give the video's name, or --self-test")
    try:
        m = load(args.name, args.work)
    except (OSError, RuntimeError, ValueError, KeyError) as e:     # a plain message for the owner, not a traceback
        print(e)
        return 2
    print(f"{len(m.keeps)} kept pieces, {m.duration:.3f} s long")
    print("joins at: " + (", ".join(f"{j:.3f}" for j in m.joins()) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
