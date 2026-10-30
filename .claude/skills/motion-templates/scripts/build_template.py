#!/usr/bin/env python3
"""Render motion templates (flowchart, steps, compare, quote, chapter, hook-title, tag, cta, card, lower-third, title-card,
annotate) and put them into a video.

Examples (from the project folder, with the .venv python)
  python build_template.py work/talk.templates.json --video work/talk.mp4 --out work/talk.t.mp4
  python build_template.py work/flow.json --video work/talk.mp4 --theme midnight --out work/talk.t.mp4
  python build_template.py work/flow.json --size 1080x1920        -> work/previews/tpl-flowchart-....mp4 (a preview)
  python build_template.py --self-test

The spec file holds one template spec or a list of them; a list goes into the video in one encode.
A clip whose page, size and fps are unchanged since its last render is reused (its .key file says so).
Times in a spec are seconds on the video's timeline. Every field: ../references/templates.md
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tpl import Ctx, Scene, hfbuild, load_theme, page  # noqa: E402
from vtools import SetupError, fmt_time, probe, project_root  # noqa: E402

TEMPLATES = ("flowchart", "steps", "compare", "quote", "chapter", "hook-title", "tag", "cta", "card", "lower-third",
             "title-card", "annotate")


def scene_for(spec: dict, w: int, h: int, theme_name: str) -> tuple[Ctx, Scene]:
    name = spec.get("template")
    if name not in TEMPLATES:
        raise ValueError(f"unknown template {name!r} (have: {', '.join(TEMPLATES)})")
    start = float(spec.get("start", 0.0))
    if "end" not in spec:
        raise ValueError(f"{name}: give an \"end\" time (seconds on the video's timeline)")
    end = float(spec["end"])
    if end - start < 0.5:
        raise ValueError(f"{name}: end must be at least 0.5 s after start")
    ctx = Ctx(w, h, load_theme(theme_name), start, end)
    return ctx, importlib.import_module(f"templates.{name.replace('-', '_')}").build(spec, ctx)


def example(name: str) -> dict:
    """The JSON example in a template module's docstring."""
    doc = importlib.import_module(f"templates.{name.replace('-', '_')}").__doc__
    return json.loads(doc[doc.index("{"):doc.rindex("}") + 1])


def fresh(clip: Path, key: str) -> bool:
    """True when `clip` was rendered from exactly this page, size and fps (the .key file next to it holds the hash)."""
    stamp = clip.with_name(clip.name + ".key")
    return clip.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8") == key


def self_test() -> None:
    from templates.flowchart import layout
    pos = layout([{"id": "a"}, {"id": "b", "after": "a"}, {"id": "c", "after": "b"}, {"id": "d", "after": "a"}])
    assert pos == {"c": (0.0, 2), "b": (0.0, 1), "d": (1.0, 1), "a": (0.5, 0)}, pos
    for bad in ([{"id": "a"}, {"id": "a"}], [{"id": "a", "after": "zz"}],
                [{"id": "a", "after": "b"}, {"id": "b", "after": "a"}]):
        try:
            layout(bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    ctx = Ctx(1080, 1920, load_theme("blueprint"), 10.0, 20.0)
    assert ctx.t(12.5) == 2.5 and ctx.t(None) == 0.0 and ctx.u == 1080 and ctx.vertical
    try:
        ctx.t(25)
        raise AssertionError("accepted a time outside the window")
    except ValueError:
        pass
    for name in TEMPLATES:                         # every template builds from its own docstring example
        for theme in ("blueprint", "midnight", "paper", "apple"):
            for w, h in ((1080, 1920), (1920, 1080)):
                c, s = scene_for(example(name), w, h, theme)
                assert "<script>" in page(c, s) and s.html
    for bad in ({"template": "card", "start": 0, "end": 2, "html": '<img src="https://x.io/a.png">'},
                {"template": "lower-third", "start": 0, "end": 3, "name": "A", "style": "zz"},
                {"template": "lower-third", "start": 0, "end": 3, "name": "A", "style": "kicker-name"},
                {"template": "title-card", "start": 0, "end": 3, "title": "A", "style": "zz"},
                {"template": "annotate", "start": 0, "end": 3, "marks": [{"shape": "zz"}]}):
        try:
            scene_for(bad, 1080, 1920, "apple")
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    for name, styles, extras in (                   # every style, with and without the optional fields, short windows
            ("lower-third", ("clean-bar", "accent-underline", "kicker-name", "side-rule"),
             ({"kicker": "K"}, {"kicker": "K", "title": "", "position": "top"}, {"kicker": "K", "position": 0.5})),
            ("title-card", ("calm", "lockup"), ({}, {"kicker": "", "sub": "", "mode": "overlay", "position": 0.3}))):
        for style in styles:
            for extra in extras:
                sp = {**example(name), "style": style, **extra, "start": 2.0, "end": 3.0}
                for w, h in ((1080, 1920), (1920, 1080)):
                    c, s = scene_for(sp, w, h, "paper")
                    assert all(0 <= t <= c.dur for t in s.checks), (sp, s.checks)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        clip = Path(d) / "c.webm"
        assert not fresh(clip, "k")
        clip.write_bytes(b"x")
        clip.with_name("c.webm.key").write_text("k", encoding="utf-8")
        assert fresh(clip, "k") and not fresh(clip, "k2")
    print("self-test ok")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Render motion templates and put them into a video.")
    p.add_argument("spec", type=Path, nargs="?", help="JSON file: one template spec or a list of them")
    p.add_argument("--video", type=Path, help="put the templates into this video (default: standalone previews)")
    p.add_argument("--theme", help="blueprint, midnight, paper or apple (default: the spec's \"theme\", else blueprint)")
    p.add_argument("--out", type=Path, help="output video (default: output/<name>.mp4)")
    p.add_argument("--size", default="1080x1920", help="standalone canvas, e.g. 1920x1080 (default 1080x1920)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--self-test", action="store_true", help="check the layout and every template, render nothing")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.spec:
        p.error("give a spec file (or --self-test)")

    root = project_root()
    specs = json.loads(args.spec.read_text(encoding="utf-8"))
    specs = specs if isinstance(specs, list) else [specs]
    try:
        if args.video:
            video = args.video if args.video.exists() else root / "input" / args.video
            info = probe(video)
            s = min(1.0, 1920 / max(info.width, info.height))
            w, h, fps = int(info.width * s) // 2 * 2, int(info.height * s) // 2 * 2, hfbuild.video_fps(info)
        else:
            w, h = (int(x) for x in args.size.lower().split("x"))
            fps = 30
        clips = []
        for sp in specs:
            ctx, scene = scene_for(sp, w, h, args.theme or sp.get("theme") or "blueprint")
            label = sp.get("name") or sp.get("title") or sp.get("text") or sp.get("handle") or sp.get("label") or ""
            name = f"tpl-{sp['template']}-{hfbuild.slug(str(label))}-{int(ctx.start * 10)}"
            html = page(ctx, scene)
            comp = hfbuild.new_composition(name, html)
            ext = "webm" if scene.overlay else "mp4"
            dest = root / "work" / ("templates" if args.video else "previews") / f"{name}.{ext}"
            key = hashlib.sha256(f"{w}x{h}@{fps}|{scene.overlay}|{html}".encode("utf-8")).hexdigest()
            what = f"{sp['template']} ({fmt_time(ctx.start)}-{fmt_time(ctx.end)}, {ctx.theme['name']})"
            if fresh(dest, key):
                print(f"Reused {what}: unchanged since its last render.", flush=True)
                clip = dest
            else:
                print(f"Rendering {what}...", flush=True)
                dest.with_name(dest.name + ".key").unlink(missing_ok=True)   # a failed render must not look fresh
                clip = hfbuild.render(comp, dest, fps=fps, transparent=scene.overlay)
                clip.with_name(clip.name + ".key").write_text(key, encoding="utf-8")
            checks = scene.checks or [ctx.dur * f for f in (0.2, 0.5, 0.85)]
            clips.append({"path": clip, "start": ctx.start, "checks": [ctx.start + c for c in checks]})
        if args.video:
            out = args.out or root / "output" / f"{video.stem}.mp4"
            if out.resolve() == video.resolve() or (out.exists() and not args.overwrite):
                print(f"{out} exists or is the source (use --out or --overwrite).")
                return 1
            print("Laying the templates over the video...", flush=True)
            hfbuild.overlay(video, [{"path": c["path"], "start": c["start"]} for c in clips], out)
            times = sorted(t for c in clips for t in c["checks"])
            sheet = hfbuild.contact_sheet(out, times, root / "work" / f"{out.stem}.templates-check.png")
            print(f"OK  {out}  ({len(clips)} template(s))")
            print(f"Check frames: {sheet}")
        else:
            for c in clips:
                rel = [t - c["start"] for t in c["checks"]]
                sheet = hfbuild.contact_sheet(c["path"], rel, root / "work" / f"{c['path'].stem}.check.png")
                print(f"OK  {c['path']}\n    check frames: {sheet}")
        print("Editable compositions: work/hyperframes/tpl-*/index.html")
    except (ValueError, KeyError, SetupError) as e:
        print(str(e) if isinstance(e, SetupError) else f"Spec problem: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
