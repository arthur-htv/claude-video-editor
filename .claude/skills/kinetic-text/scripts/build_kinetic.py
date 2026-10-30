#!/usr/bin/env python3
"""Turn picked emphasis moments into kinetic text laid over the video.

Each moment becomes a short transparent HyperFrames clip in one of five styles,
timed a beat ahead of the spoken word and placed away from the face; all clips
are then laid over the video in one encode. The audio is not touched.

  pop         one word punches in and holds            ("NEVER")
  slam        a number lands hard, shakes, underlines   ("10X", "$500")
  typewriter  the words type out in a dark pill + caret ("Claude Code")
  highlight   words rise in, a marker sweeps behind     ("raw footage")
  stack       2-3 words stack in with momentum          ("STEP / ONE")

Examples (from the project folder, with the .venv python)
  python build_kinetic.py work/talk.mp4 --plan work/talk.emphasis.json          -> output/talk.mp4
  python build_kinetic.py work/talk.mp4 --plan work/talk.emphasis.json --only 1,3 --out work/preview.mp4
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent / "video-editor" / "scripts"
sys.path.insert(0, str(SHARED))
import hfbuild  # noqa: E402
from layout import analyze  # noqa: E402
from vtools import SetupError, fmt_time, probe, project_root  # noqa: E402

STYLES = ("pop", "slam", "typewriter", "highlight", "stack")
LEAD = 0.15          # the text lands just before the word, so it reads as inevitable
IN, OUT = 0.35, 0.25
# A dark halo around every letter, so white text still reads on a white shirt or a bright wall
SHADOW = ("0 0 0.05em rgba(0,0,0,.9), 0 0 0.12em rgba(0,0,0,.75), 0 0.05em 0.2em rgba(0,0,0,.6), "
          "0 0 0.02em rgba(0,0,0,.95)")


def zone_css(position: str, vertical: bool) -> tuple[str, str]:
    """CSS placing the text block, and its text alignment."""
    if position.startswith("y="):
        return f"left:6%;right:6%;top:{float(position[2:]) * 100:.1f}%;", "center"
    zones = {
        "top": (f"left:6%;right:6%;top:{14 if vertical else 11}%;", "center"),
        "center": ("left:6%;right:6%;top:42%;", "center"),
        "lower": (f"left:6%;right:6%;top:{56 if vertical else 62}%;", "center"),
        "left": ("left:6%;width:44%;top:34%;", "left"),
        "right": ("right:6%;width:44%;top:34%;", "right"),
    }
    return zones.get(position, zones["top"])


def fit_size(text: str, size: float, box_width: float, per_char: float = 0.8) -> float:
    """Shrink the font until the longest line fits the zone width."""
    longest = max((len(line) for line in text.split("\n")), default=1)
    return min(size, box_width / max(1, longest * per_char))


def moment_html(m: dict, w: int, h: int, vertical: bool, scale: float) -> tuple[str, float]:
    style = m.get("style", "pop")
    col = hfbuild.color(m.get("color"), "teal")
    text = m["text"].strip()
    base = min(w, h) * scale
    zone, align = zone_css(m.get("position", "top"), vertical)
    zone_w = w * (0.44 if align != "center" else 0.88)
    spoken = max(0.2, float(m.get("end", m["start"])) - float(m["start"]))
    hold = min(2.4, max(0.8, spoken + 0.6))
    type_time = min(0.9, max(0.35, spoken + 0.1))
    dur = float(m.get("duration") or (IN + hold + OUT + (type_time if style == "typewriter" else 0)))
    dur = round(dur, 3)
    k = w / 1920
    css, body, js = "", "", ""

    if style == "pop":
        fs = fit_size(text.upper(), 0.12 * base, zone_w)
        body = f'<span class="word" style="color:{col}">{html.escape(text)}</span>'
        css = (f".word{{display:inline-block;font:800 {fs:.0f}px/1 'Montserrat XB';text-transform:uppercase;"
               f"letter-spacing:-0.02em;text-shadow:{SHADOW}}}")
        js = (f'tl.fromTo(".word",{{scale:0.55,opacity:0,y:{fs * 0.25:.0f}}},{{scale:1,opacity:1,y:0,duration:0.32,ease:"back.out(2.2)"}},0);'
              f'tl.to(".word",{{scale:1.04,duration:{dur - 0.54:.3f},ease:"none"}},0.32);'
              f'tl.to(".word",{{opacity:0,scale:1.1,duration:0.22,ease:"power2.in"}},{dur - 0.22:.3f});')
    elif style == "slam":
        fs = fit_size(text.upper(), 0.14 * base, zone_w)
        body = (f'<div class="slam"><span class="num" style="color:{col}">{html.escape(text)}</span>'
                f'<div class="bar" style="background:{col}"></div></div>')
        css = (f".slam{{display:inline-block}}.num{{display:block;font:800 {fs:.0f}px/1 'Montserrat XB';"
               f"text-transform:uppercase;letter-spacing:-0.03em;text-shadow:{SHADOW}}}"
               f".bar{{height:{max(6, fs * 0.07):.0f}px;border-radius:99px;margin-top:{fs * 0.08:.0f}px;transform-origin:left center}}")
        js = (f'tl.fromTo(".num",{{scale:1.9,opacity:0}},{{scale:1,opacity:1,duration:0.26,ease:"power4.out"}},0);'
              f'tl.to(".slam",{{keyframes:{{x:[{-12 * k:.1f},{10 * k:.1f},{-6 * k:.1f},{3 * k:.1f},0]}},duration:0.24,ease:"none"}},0.24);'
              f'tl.fromTo(".bar",{{scaleX:0}},{{scaleX:1,duration:0.32,ease:"power3.out"}},0.3);'
              f'tl.to(".num",{{scale:1.03,duration:{dur - 0.48:.3f},ease:"none"}},0.26);'
              f'tl.to(".slam",{{opacity:0,y:{-fs * 0.2:.0f},duration:0.22,ease:"power2.in"}},{dur - 0.22:.3f});')
    elif style == "typewriter":
        fs = fit_size(text, 0.062 * base, zone_w * 0.85, 0.62)
        chars = "".join(f'<span class="ch">{"&nbsp;" if c == " " else html.escape(c)}</span>' for c in text)
        body = f'<div class="pill"><span class="txt">{chars}</span><span class="caret" style="background:{col}"></span></div>'
        css = (f".pill{{display:inline-flex;align-items:center;padding:.38em .62em;border-radius:.42em;"
               f"background:rgba(12,12,14,.86);border:1px solid rgba(255,255,255,.2);"
               f"box-shadow:0 .3em 1em rgba(0,0,0,.35);font:800 {fs:.0f}px/1.1 'Montserrat XB';color:#fff}}"
               f".ch{{opacity:0}}.caret{{display:inline-block;width:.09em;height:1.05em;margin-left:.08em;border-radius:2px}}")
        n = max(1, len(text))
        step = min(0.07, type_time / n)
        end_typing = 0.12 + n * step
        js = ('tl.fromTo(".pill",{opacity:0,scale:0.92},{opacity:1,scale:1,duration:0.18,ease:"power2.out"},0);'
              'gsap.utils.toArray(".ch").forEach((c,i)=>tl.set(c,{opacity:1},0.12+i*' + f"{step:.4f}" + '));'
              f'for(let t={end_typing + 0.2:.3f};t<{dur - 0.3:.3f};t+=0.52){{tl.set(".caret",{{opacity:0}},t);tl.set(".caret",{{opacity:1}},t+0.26);}}'
              f'tl.to(".pill",{{opacity:0,y:-10,duration:0.2,ease:"power2.in"}},{dur - 0.2:.3f});')
    elif style == "highlight":
        words = text.split()
        keys = {k.lower() for k in m.get("key", [])} if m.get("key") else None
        fs = fit_size(text.upper(), 0.078 * base, zone_w)
        spans = []
        for wd in words:
            is_key = keys is None or wd.lower().strip(",.") in keys
            spans.append(f'<span class="w{" key" if is_key else ""}"><span class="mark" style="background:{col}"></span>'
                         f'<span class="t">{html.escape(wd)}</span></span>')
        body = f'<div class="hl">{" ".join(spans)}</div>'
        css = (f".hl{{font:800 {fs:.0f}px/1.15 'Montserrat XB';text-transform:uppercase;color:#fff;letter-spacing:-0.01em}}"
               f".w{{position:relative;display:inline-block;margin:0 .1em}}"
               f".mark{{position:absolute;left:-.1em;right:-.1em;top:.06em;bottom:.02em;border-radius:.1em;z-index:0}}"
               f".t{{position:relative;z-index:1;text-shadow:{SHADOW}}}")
        js = ('gsap.set(".mark",{scaleX:0,transformOrigin:"left center"});'
              f'tl.from(".w",{{y:{fs * 0.35:.0f},opacity:0,duration:0.3,ease:"expo.out",stagger:0.07}},0);'
              'tl.to(".key .mark",{scaleX:1,duration:0.3,ease:"power2.out",stagger:0.08},0.22);'
              'tl.to(".key .t",{color:"#0b0b0b",textShadow:"none",duration:0.12,stagger:0.08},0.3);'
              f'tl.to(".hl",{{opacity:0,y:{-fs * 0.2:.0f},duration:0.22,ease:"power2.in"}},{dur - 0.22:.3f});')
    elif style == "stack":
        words = text.split()
        if len(words) <= 3:
            lines = words
        else:                                    # group into up to 3 lines, keeping reading order
            per = -(-len(words) // 3)
            lines = [" ".join(words[i:i + per]) for i in range(0, len(words), per)]
        fs = fit_size("\n".join(lines).upper(), 0.095 * base, zone_w)
        rows = []
        for i, line in enumerate(lines):
            accent = f' style="color:{col}"' if i == len(lines) - 1 else ""
            rows.append(f'<div class="line"{accent}>{html.escape(line)}</div>')
        body = '<div class="stack">' + "".join(rows) + "</div>"
        css = (f".stack{{display:inline-block;text-align:{align}}}.line{{font:800 {fs:.0f}px/0.98 'Montserrat XB';"
               f"text-transform:uppercase;letter-spacing:-0.02em;color:#fff;text-shadow:{SHADOW}}}")
        sign = "" if align != "right" else "-"
        js = (f'const offs=[{360 * k:.0f},{120 * k:.0f},{60 * k:.0f}];'
              'gsap.utils.toArray(".line").forEach((el,i)=>tl.from(el,{x:' + sign + '-offs[Math.min(i,2)],opacity:0,'
              'duration:i?0.2:0.33,ease:i?"power2.out":"expo.out"},i*0.12));'
              f'tl.to(".stack",{{opacity:0,x:{-40 * k:.0f},duration:0.22,ease:"power2.in"}},{dur - 0.22:.3f});')
    else:
        raise ValueError(f"unknown style {style!r}; use one of {', '.join(STYLES)}")

    page = f"""<!doctype html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width={w}, height={h}">
{hfbuild.scripts_html()}
<style>{hfbuild.FONT_CSS}
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent}}
#root{{position:relative;width:{w}px;height:{h}px}}
#stage{{position:absolute;inset:0}}
.kt{{position:absolute;{zone}text-align:{align}}}
{css}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{w}" data-height="{h}">
  <div id="stage" class="clip" data-start="0" data-duration="{dur}" data-track-index="0"><div class="kt">{body}</div></div>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{js}
tl.to({{}}, {{ duration: {dur} }}, 0);
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
"""
    return page, dur


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Lay kinetic text over a video at the planned moments.")
    p.add_argument("video", type=Path)
    p.add_argument("--plan", type=Path, required=True, help="emphasis JSON from find_emphasis.py (or your own)")
    p.add_argument("--only", help="comma-separated moment numbers (1-based) to build, e.g. for a preview")
    p.add_argument("--position", help="override every moment: top, center, lower, left, right or y=0.3")
    p.add_argument("--scale", type=float, default=1.0, help="text size multiplier (default 1.0)")
    p.add_argument("--out", type=Path, help="output video (default: output/<name>.mp4)")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    root = project_root()
    video = args.video if args.video.exists() else root / "input" / args.video
    try:
        info = probe(video)
    except SetupError as e:
        print(e)
        return 2
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    moments = plan.get("moments", []) if isinstance(plan, dict) else plan
    if args.only:
        picks = {int(x) for x in args.only.split(",") if x.strip()}
        moments = [m for i, m in enumerate(moments, 1) if i in picks]
    if not moments:
        print("The plan has no moments.")
        return 1
    out = args.out or root / "output" / f"{video.stem}.mp4"
    if out.resolve() == video.resolve():
        print("The output would overwrite the source. Use --out with a different name.")
        return 2
    if out.exists() and not args.overwrite:
        print(f"{out} already exists (use --overwrite or --out).")
        return 1

    lay = analyze(video, info)
    big = max(info.width, info.height)
    s = min(1.0, 1920 / big)                       # render overlays at most 1920 px wide, scale up later
    w, h = int(info.width * s) // 2 * 2, int(info.height * s) // 2 * 2
    fps = hfbuild.video_fps(info)
    clips = []
    print(f"Layout: {lay.note}; default text zone: {lay.text_zone}")
    # One moment on screen at a time: shorten a moment that would run into the next one,
    # and drop it if the two are too close to both read.
    moments = sorted((dict(m) for m in moments), key=lambda m: float(m["start"]))
    kept = []
    for j, m in enumerate(moments):
        m["position"] = args.position or m.get("position") or lay.text_zone
        if m.get("style") not in STYLES:
            m["style"] = "pop"
        _, natural = moment_html(m, w, h, lay.vertical, args.scale)
        if j + 1 < len(moments):
            room = float(moments[j + 1]["start"]) - float(m["start"]) - 0.05
            if room < 0.9:
                print(f"  skipped \"{m['text']}\": only {room:.1f}s before the next moment (too cluttered)")
                continue
            m["duration"] = round(min(natural, room), 3)
        kept.append(m)
    for i, m in enumerate(kept, 1):
        page, dur = moment_html(m, w, h, lay.vertical, args.scale)
        name = f"kt-{hfbuild.slug(video.stem)}-{i:02d}-{hfbuild.slug(m['text'])}"
        comp = hfbuild.new_composition(name, page)
        clip = hfbuild.render(comp, root / "work" / "kinetic" / f"{name}.webm", fps=fps, transparent=True)
        start = max(0.0, float(m["start"]) - LEAD)
        clips.append({"path": clip, "start": start, "peak": start + IN + 0.25, "text": m["text"]})
        print(f"  [{i}/{len(kept)}] {fmt_time(start):>7} {m['style']:<10} \"{m['text']}\" ({dur:.1f}s, {m['position']})",
              flush=True)
    print("Laying the text over the video...", flush=True)
    hfbuild.overlay(video, clips, out)
    sheet = hfbuild.contact_sheet(out, [c["peak"] for c in clips], root / "work" / f"{video.stem}.kinetic-check.png")
    print(f"OK  {out}  ({len(clips)} kinetic moments, audio untouched)")
    print(f"Check frames: {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
