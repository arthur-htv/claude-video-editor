#!/usr/bin/env python3
"""Keep an automatic edit's progress in work/<name>.run.json, so any session can pick up the work.

/video-editor:auto updates the run file after every step: the source, profile, preset and theme, the current
video V and word timings W, each step's status and output file, every graphic's window (cutaway or overlay,
and what it is), the director's plan approval and the report row. The --skip, --hide-during and --morph
strings are built here from those windows, so their rules (references/auto-edit.md) live in one place.

  python run_state.py <name> next                     where to pick up: the first unfinished step, V and W
  python run_state.py <name> init input/<file> --profile short --preset tight [--theme blueprint]
  python run_state.py <name> step 2 done --out work/<name>.mp4 --note "9 cuts"    (a video --out becomes V)
  python run_state.py <name> step 7 skipped --note "captions already burned in"
  python run_state.py <name> set W work/<name>.words.json      (also V, theme, profile, preset, notes)
  python run_state.py <name> window add cutaway 2.9 5.9 morph "bars 6 -> 1"
  python run_state.py <name> window clear                      forget every window (before re-planning)
  python run_state.py <name> approve-director
  python run_state.py <name> skip-string                       for find_emphasis --skip
  python run_state.py <name> hide-string                       for make_captions --hide-during
  python run_state.py <name> morph-string                      for suggest_sfx --morph
  python run_state.py <name> report "Dead air" "9 cuts (tight)"    one cell of the report row; alone, prints it
  python run_state.py <name> show                              everything in the run file
  python run_state.py --self-test

<name> is the source file's name without its extension (talk for input/talk.mov). A window's kind is morph,
kinetic, behind, or the template's name (flowchart, card, steps, hook-title, ...). Paths are stored as typed,
from the project folder.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vtools import VIDEO_EXTS, project_root  # noqa: E402

# The steps of references/auto-edit.md, in the order they run.
STEPS = {"1": "profile", "2": "dead air", "3": "transcribe", "4": "mistakes", "4b": "re-listen",
         "4c": "voice level", "4d": "punch-ins", "5": "direct", "6": "render", "6b": "sounds",
         "7": "captions", "8": "check"}
FACTS = ("profile", "preset", "theme", "V", "W", "notes")   # a new source is a new run: init --overwrite
COLUMNS = ("Video", "Length", "Dead air", "Mistakes", "Voice", "Punch-ins", "Templates and cards", "Kinetic text",
           "Graphics", "Sounds", "Captions")
NOT_TEMPLATES = ("morph", "kinetic", "behind")   # every other kind is a template's name, card and flowchart too


def run_path(name: str, work: Path | str | None = None) -> Path:
    return (Path(work) if work else project_root() / "work") / f"{name}.run.json"


def read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SystemExit(f"{path} is damaged ({e}). Fix it by hand, or start over with init --overwrite.")
    if not (isinstance(d, dict) and {*FACTS, "name", "source", "steps", "windows", "director_approved", "report"} <= d.keys()):
        raise SystemExit(f"{path} is damaged (it isn't a run file). Fix it by hand, or start over with init --overwrite.")
    return d


def load(name: str, work: Path | str | None = None) -> dict:
    return read(run_path(name, work))


def save(state: dict, path: Path) -> None:
    """Write a temp file beside it, then swap it in: a crash leaves the old file or the new one, never half."""
    text = json.dumps(state, indent=1, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def next_step(state: dict) -> str | None:
    return next((s for s in STEPS if s not in state["steps"]), None)


def where(state: dict) -> str:
    s = next_step(state)
    return f"step {s} ({STEPS[s]})" if s else "nothing, every step is finished"


def windows(state: dict) -> list[dict]:
    """Every graphic window, cutaway and overlay together, by start time."""
    return sorted(({**w, "mode": m} for m in ("cutaway", "overlay") for w in state["windows"][m]),
                  key=lambda w: (w["start"], w["end"]))


def spans(pairs) -> str:
    """[(2.9, 5.9), (8.2, 10.8)] -> '2.9-5.9,8.2-10.8', the form find_emphasis, make_captions and suggest_sfx read."""
    num = lambda x: f"{x:.3f}".rstrip("0").rstrip(".")  # noqa: E731
    return ",".join(f"{num(a)}-{num(b)}" for a, b in pairs)


def skip_string(state: dict) -> str:
    """find_emphasis --skip: every template, card and morph window, widened by 1 s on each side.
    Never below 0: the readers split on '-', so '-0.6' would break them."""
    return spans((max(0.0, w["start"] - 1), w["end"] + 1) for w in windows(state)
                 if w["kind"] not in ("kinetic", "behind"))


def hide_string(state: dict) -> str:
    """make_captions --hide-during: the morph windows, the cutaway templates and cards except the flowchart
    (it keeps its bottom fifth free for captions), and the text-behind windows."""
    return spans((w["start"], w["end"]) for w in windows(state)
                 if w["kind"] in ("morph", "behind")
                 or (w["mode"] == "cutaway" and w["kind"] not in NOT_TEMPLATES + ("flowchart",)))


def morph_string(state: dict) -> str:
    """suggest_sfx --morph: the morph windows as they are."""
    return spans((w["start"], w["end"]) for w in windows(state) if w["kind"] == "morph")


def report_table(state: dict) -> str:
    """The report row under its header, in the guide's column order; extra columns go last."""
    cells = {"Video": Path(state["source"]).name, **state["report"]}
    cols = list(COLUMNS) + [c for c in cells if c not in COLUMNS]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
                      "| " + " | ".join(cells.get(c, "") for c in cols) + " |"])


def check_kind(kind: str) -> None:
    if kind in NOT_TEMPLATES:
        return
    sys.path.insert(0, str(HERE.parent.parent / "motion-templates" / "scripts"))
    from build_template import TEMPLATES   # the template names live there
    if kind not in TEMPLATES:
        raise SystemExit(f"Unknown kind {kind!r}. Use morph, kinetic, behind, or a template: {', '.join(TEMPLATES)}.")


def warnings(state: dict, root: Path) -> list[str]:
    out = []
    src = root / state["source"]
    if not src.is_file():
        out.append(f"Warning: the source {state['source']} is missing.")
    elif src.stat().st_size != state.get("source_size"):
        out.append(f"Warning: {state['source']} changed since this run started. Start over with init --overwrite.")
    if not (root / state["V"]).is_file():
        out.append(f"Warning: V ({state['V']}) is missing. Redo the step that made it.")
    return out


def cmd_next(state: dict, root: Path) -> None:
    s = next_step(state)
    print(f"{state['name']}: next is {where(state)}.")
    later = [t for t in list(STEPS)[list(STEPS).index(s) + 1:] if t in state["steps"]] if s else []
    if later:
        print(f"Note: step {later[-1]} is already marked, so step {s} may have run without being marked. "
              f"If it did, mark it done or skipped.")
    print(f"  V = {state['V']}")
    print(f"  W = {state['W'] or '(not yet)'}")
    n = {m: len(state["windows"][m]) for m in ("cutaway", "overlay")}
    print(f"  profile {state['profile'] or '?'}, preset {state['preset'] or '?'}, theme {state['theme'] or '?'}; "
          f"director's plan {'approved' if state['director_approved'] else 'not approved'}; "
          f"windows: {n['cutaway']} cutaway, {n['overlay']} overlay")
    if state["notes"]:
        print(f"  notes: {state['notes']}")
    for w in warnings(state, root):
        print(w)
    if not s:
        print(report_table(state))


def cmd_show(state: dict, path: Path, root: Path) -> None:
    print(f"Run file {path}")
    print(f"  source {state['source']}; profile {state['profile'] or '?'}, preset {state['preset'] or '?'}, "
          f"theme {state['theme'] or '?'}")
    if state["notes"]:
        print(f"  notes: {state['notes']}")
    print(f"  V = {state['V']}\n  W = {state['W'] or '(not yet)'}\n  steps:")
    for s, label in STEPS.items():
        e = state["steps"].get(s, {})
        note = f"  ({e['note']})" if e.get("note") else ""
        print(f"    {s:<3} {label:<12} {e.get('status', 'to do'):<8} {e.get('out', '')}{note}")
    print(f"  director's plan: {'approved' if state['director_approved'] else 'not approved yet'}")
    print("  windows:" + ("" if windows(state) else " none"))
    for w in windows(state):
        print(f"    {w['mode']:<8} {spans([(w['start'], w['end'])]):<12} {w['kind']:<11} {w.get('label', '')}")
    print(f'  --skip "{skip_string(state)}"\n  --hide-during "{hide_string(state)}"\n  --morph "{morph_string(state)}"')
    print(report_table(state))
    for w in warnings(state, root):
        print(w)


def main(argv: list[str] | None = None) -> int:
    with contextlib.suppress(AttributeError):   # UTF-8: a pipe on Windows would turn the report's "→" into "?"
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:   # before parsing: the name is required otherwise
        return self_test()
    p = argparse.ArgumentParser(description="The run file of an automatic edit: where to pick up, and the window strings.")
    # required, or argparse hands the name to the command when an option such as --work sits between them
    p.add_argument("name", help="the source file's name without extension (talk for input/talk.mov)")
    p.add_argument("--work", type=Path, help="the work folder (default: work/ in the project)")
    p.add_argument("--self-test", action="store_true", help="run the built-in checks and stop")
    sub = p.add_subparsers(dest="cmd", metavar="command", required=True)
    sub.add_parser("next", help="the first unfinished step, with V and W")
    c = sub.add_parser("init", help="start the run file (after step 1)")
    c.add_argument("source", help="the source video, e.g. input/talk.mov")
    for f in ("profile", "preset", "theme"):
        c.add_argument(f"--{f}", default="")
    c.add_argument("--overwrite", action="store_true", help="start over, forgetting the old run")
    c = sub.add_parser("step", help="mark a step done or skipped")
    c.add_argument("id", choices=list(STEPS))
    c.add_argument("status", choices=("done", "skipped"))
    c.add_argument("--out", help="the file the step made (a video becomes V)")
    c.add_argument("--note", help="what it did, or why it was skipped")
    c = sub.add_parser("set", help="change one fact: " + ", ".join(FACTS))
    c.add_argument("key", choices=FACTS)
    c.add_argument("value")
    c = sub.add_parser("window", help="add a graphic's window, or clear them all")
    wsub = c.add_subparsers(dest="action", required=True)
    a = wsub.add_parser("add")
    a.add_argument("mode", choices=("cutaway", "overlay"))
    a.add_argument("start", type=float)
    a.add_argument("end", type=float)
    a.add_argument("kind", help="morph, kinetic, behind, or the template's name (flowchart, card, steps, ...)")
    a.add_argument("label", nargs="?", default="")
    wsub.add_parser("clear")
    sub.add_parser("approve-director", help="the user OK'd the director's plan")
    for name, use in (("skip-string", "find_emphasis --skip"), ("hide-string", "make_captions --hide-during"),
                      ("morph-string", "suggest_sfx --morph")):
        sub.add_parser(name, help=f"the windows for {use}")
    c = sub.add_parser("report", help="set one cell of the report row; with nothing after it, print the row")
    c.add_argument("column", nargs="?")
    c.add_argument("text", nargs="?")
    sub.add_parser("show", help="everything in the run file")
    args = p.parse_args(argv)
    if Path(args.name).name != args.name or Path(args.name).suffix.lower() in VIDEO_EXTS:
        p.error(f"give the video's name without its folder or extension (talk for input/talk.mov), not {args.name!r}")

    path = run_path(args.name, args.work)
    root = path.parent.parent   # the project folder: stored paths are relative to it
    if args.cmd == "init":
        if path.is_file() and not args.overwrite:
            raise SystemExit(f"{path} already exists; next is {where(read(path))}. "
                             f"Pick it up with next, or add --overwrite to start over.")
        if not (root / args.source).is_file():
            raise SystemExit(f"{args.source} was not found. Give the source video's path from the project folder.")
        path.parent.mkdir(parents=True, exist_ok=True)
        save({"name": args.name, "source": args.source, "source_size": (root / args.source).stat().st_size,
              "profile": args.profile, "preset": args.preset, "theme": args.theme, "notes": "",
              "V": args.source, "W": "", "steps": {}, "windows": {"cutaway": [], "overlay": []},
              "director_approved": False, "report": {}}, path)
        print(f"Started {path}. V = {args.source}.")
        return 0
    if not path.is_file():
        if args.cmd == "next":
            print(f"No run file for {args.name} yet: start at step 1, then run init.")
            return 0
        raise SystemExit(f"No run file for {args.name} ({path}). Start one with: init input/<file>")
    state = read(path)

    if args.cmd == "next":
        cmd_next(state, root)
    elif args.cmd == "show":
        cmd_show(state, path, root)
    elif args.cmd in ("skip-string", "hide-string", "morph-string"):
        # no newline: "$(... skip-string)" must not pick up a Windows "\r"
        print({"skip-string": skip_string, "hide-string": hide_string, "morph-string": morph_string}[args.cmd](state),
              end="")
    elif args.cmd == "report" and args.column is None:
        print(report_table(state))
    else:
        if args.cmd == "step":
            redo = []
            if args.id in state["steps"]:   # done again (a change, a re-render after a FAIL): every later step runs again
                redo = [t for t in list(STEPS)[list(STEPS).index(args.id) + 1:] if state["steps"].pop(t, None)]
            state["steps"][args.id] = {"status": args.status, **({"out": args.out} if args.out else {}),
                                       **({"note": args.note} if args.note else {})}
            if args.status == "done" and args.out and Path(args.out).suffix.lower() in VIDEO_EXTS:
                state["V"] = args.out
            msg = (f"Step {args.id} ({STEPS[args.id]}) {args.status}. V = {state['V']}. "
                   + (f"Later steps to do again: {', '.join(redo)}. " if redo else "") + f"Next: {where(state)}.")
        elif args.cmd == "set":
            state[args.key] = args.value
            msg = f"{args.key} = {args.value}"
            if args.key in ("V", "W") and not (root / args.value).is_file():
                msg += f" (note: {args.value} was not found)"
        elif args.cmd == "window" and args.action == "clear":
            state["windows"] = {"cutaway": [], "overlay": []}
            msg = "Every window cleared."
        elif args.cmd == "window":
            check_kind(args.kind)
            if not 0 <= args.start < args.end:
                raise SystemExit(f"A window needs 0 <= start < end (seconds on the current cut), not {args.start}-{args.end}.")
            w = {"start": round(args.start, 3), "end": round(args.end, 3), "kind": args.kind, "label": args.label}
            for m in ("cutaway", "overlay"):   # adding a window again replaces it, so a resumed step can re-add its windows
                state["windows"][m] = [x for x in state["windows"][m]
                                       if (x["start"], x["end"], x["kind"]) != (w["start"], w["end"], w["kind"])]
            state["windows"][args.mode] = sorted(state["windows"][args.mode] + [w], key=lambda x: (x["start"], x["end"]))
            msg = f"Window added: {args.mode} {spans([(w['start'], w['end'])])} {args.kind} {args.label}".rstrip()
        elif args.cmd == "approve-director":
            state["director_approved"] = True
            msg = "The director's plan is approved."
        else:   # report <column> <text>
            if args.text is None:
                raise SystemExit('Give the column and the text, e.g. report "Dead air" "9 cuts (tight)".')
            norm = lambda s: s.lower().replace("-", " ")  # noqa: E731  ("punch-ins", "dead-air" as typed)
            col = next((c for c in COLUMNS if norm(c).startswith(norm(args.column))), args.column)
            state["report"][col] = args.text
            msg = f"Report: {col} = {args.text}"
        save(state, path)
        print(msg)
    return 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        work, src = root / "work", root / "input" / "talk.mov"
        work.mkdir()
        src.parent.mkdir()
        src.write_bytes(b"x" * 100)

        def cli(*argv: str) -> str:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["talk", "--work", str(work), *argv])
            return out.getvalue()

        def refused(*argv: str) -> str:
            try:
                cli(*argv)
            except SystemExit as e:
                return str(e)
            raise AssertionError(f"{argv} should have been refused")

        # A session that stops after step 5...
        assert "No run file" in cli("next")
        cli("init", "input/talk.mov", "--profile", "short", "--preset", "tight")
        assert "already exists" in refused("init", "input/talk.mov")
        cli("step", "1", "done", "--out", "work/talk.source-check.png")
        cli("step", "2", "done", "--out", "work/talk.mp4", "--note", "9 cuts")
        cli("step", "3", "done", "--out", "work/talk.srt")
        cli("set", "W", "work/talk.words.json")
        cli("step", "4", "done", "--out", "work/talk.clean.mp4")
        cli("set", "W", "work/talk.mistakes-transcript.json")
        for s in ("4b", "4c", "4d"):
            cli("step", s, "skipped")
        cli("set", "theme", "blueprint")
        for mode, a, b, kind in [("overlay", "0.4", "2.4", "hook-title"), ("cutaway", "2.9", "5.9", "morph"),
                                 ("overlay", "8.2", "10.8", "morph"), ("overlay", "12", "13.1", "kinetic"),
                                 ("cutaway", "15", "24", "flowchart"), ("cutaway", "26", "28.5", "card"),
                                 ("overlay", "30", "32", "card"), ("overlay", "35", "37", "behind"),
                                 ("cutaway", "40", "42.5", "steps"), ("overlay", "44", "47", "steps")]:
            cli("window", "add", mode, a, b, kind)
        cli("window", "add", "cutaway", "2.9", "5.9", "morph", "bars 6 -> 1")   # added again: replaced, not doubled
        cli("approve-director")
        cli("step", "5", "done", "--out", "work/talk.director.md")

        # ...and a fresh one picks it up at step 6, with the same V, W and windows.
        state = load("talk", work)
        assert next_step(state) == "6", state["steps"]
        assert state["V"] == "work/talk.clean.mp4" and state["W"] == "work/talk.mistakes-transcript.json"
        assert len(windows(state)) == 10 and state["director_approved"] and state["theme"] == "blueprint"
        assert windows(state)[1] == {"start": 2.9, "end": 5.9, "kind": "morph", "label": "bars 6 -> 1", "mode": "cutaway"}
        out = cli("next")
        assert "next is step 6 (render)" in out and "V = work/talk.clean.mp4" in out and "approved" in out, out

        # The strings, built by hand from the guide's rules (steps 5 to 7 of auto-edit.md).
        assert cli("skip-string") == "0-3.4,1.9-6.9,7.2-11.8,14-25,25-29.5,29-33,39-43.5,43-48", cli("skip-string")
        assert cli("hide-string") == "2.9-5.9,8.2-10.8,26-28.5,35-37,40-42.5", cli("hide-string")
        assert cli("morph-string") == "2.9-5.9,8.2-10.8"
        guide = {"windows": {"cutaway": [{"start": 2.9, "end": 5.9, "kind": "morph"}],
                             "overlay": [{"start": 8.2, "end": 10.8, "kind": "morph"}]}}
        assert hide_string(guide) == "2.9-5.9,8.2-10.8" and skip_string(guide) == "1.9-6.9,7.2-11.8"

        # Bad input is refused, and nothing is written.
        assert "Unknown kind" in refused("window", "add", "overlay", "1", "2", "morhp")
        assert "start < end" in refused("window", "add", "overlay", "5", "4", "morph")
        assert len(windows(load("talk", work))) == 10

        # The file round-trips, and a write that fails half way leaves the old file whole.
        path = run_path("talk", work)
        before = path.read_bytes()
        save(load("talk", work), path)
        assert path.read_bytes() == before and load("talk", work) == state
        def crash(*_):
            raise OSError("simulated crash")
        real, os.replace = os.replace, crash
        try:
            save({**state, "V": "changed"}, path)
            raise AssertionError("the simulated crash did not happen")
        except OSError:
            pass
        finally:
            os.replace = real
        assert path.read_bytes() == before and not list(work.glob("*.tmp"))

        # The report row, in the guide's column order; an extra column goes last.
        cli("report", "dead air", "9 cuts (tight)")
        cli("report", "templates", "none")
        cli("report", "Voice level", "-14 LUFS")
        cli("report", "punch-ins", "3 (112%)")              # typed lower case, with its dash
        head, _, row = cli("report").splitlines()
        assert head.startswith("| Video | Length | Dead air |") and head.endswith("| Captions | Voice level |"), head
        assert row.startswith("| talk.mov |  | 9 cuts (tight) |  |  | 3 (112%) | none |") and row.endswith("| -14 LUFS |"), row

        # A step done again (a change after the hand-over) unmarks every later step, so a resumed session redoes them;
        # a step marked late (it ran without being marked) leaves the later marks alone.
        for s in ("6", "6b", "7", "8"):
            cli("step", s, "done")
        assert "every step is finished" in cli("next")
        out = cli("step", "4", "done", "--out", "work/talk.clean.mp4")
        assert "to do again: 4b, 4c, 4d, 5, 6, 6b, 7, 8. Next: step 4b (re-listen)." in out, out
        assert next_step(load("talk", work)) == "4b" and "next is step 4b" in cli("next")
        cli("step", "6", "done")
        cli("step", "5", "done")
        assert {"5", "6"} <= load("talk", work)["steps"].keys()

        # A run file that isn't one (not UTF-8, the wrong shape, cut short) is named plainly, not a traceback.
        bad = work / "bad.run.json"
        for raw in (b"\xff\xfe\x00garbage", b"{}", b"[1, 2]", b'{"steps": {'):
            bad.write_bytes(raw)
            try:
                read(bad)
                raise AssertionError(f"{raw!r} was read as a run file")
            except SystemExit as e:
                assert "is damaged" in str(e), e

        cli("window", "clear")
        assert cli("skip-string") == cli("hide-string") == ""
        src.write_bytes(b"y" * 50)
        assert "changed since this run started" in cli("next")
    print("run_state self-test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
