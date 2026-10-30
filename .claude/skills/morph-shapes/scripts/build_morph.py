#!/usr/bin/env python3
"""Morphing-shape motion graphics: a shape that transforms into a chart or a symbol.

Templates (the shape always transforms; nothing just fades in):
  circle-to-bars   one circle splits into dots that grow into a bar chart, values count up
  circle-to-donut  a disk hollows into a ring whose segments sweep out, with percentages
  dot-to-line      a dot draws a line chart through the points, points pop on arrival
  check / cross    a circle morphs into a check mark (yes, done) or an X (no, wrong)
  ring-to-number   a progress ring fills while the number in the middle counts up
  shape-sequence   circle -> square -> triangle -> star -> circle (abstract loop / transition)

Numbers must come from the user or from what the speaker says. Never invent data.

Examples (from the project folder, with the .venv python)
  python build_morph.py --template circle-to-bars --title "Hours per edit" --labels "Before,After" --values "6,1"
      -> output/morph-circle-to-bars-hours-per-edit.mp4 (standalone, dark background)
  python build_morph.py --template circle-to-bars --labels "2024,2025" --values "12,48" --unit % \\
      --video work/talk.mp4 --at 12.4            -> full-screen cutaway inside the video (audio continues)
  python build_morph.py --template check --label "Approved" --video work/talk.mp4 --at 30 --mode overlay
"""
from __future__ import annotations

import argparse
import html
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent / "video-editor" / "scripts"
sys.path.insert(0, str(SHARED))
import hfbuild  # noqa: E402
from vtools import SetupError, fmt_time, probe, project_root  # noqa: E402

TEMPLATES = ("circle-to-bars", "circle-to-donut", "dot-to-line", "check", "cross", "ring-to-number", "shape-sequence")
PALETTE = ["teal", "yellow", "purple", "green", "orange", "blue", "red"]
BG = "#0b0d12"


def label_div(cls: str, x: float, y: float, text: str, size: float, color: str = "#fff",
              anchor: str = "center") -> str:
    tx = {"center": "-50%", "left": "0", "right": "-100%"}[anchor]
    return (f'<div class="{cls}" style="left:{x:.1f}px;top:{y:.1f}px;font-size:{size:.0f}px;color:{color};'
            f'transform:translate({tx},-50%)">{text}</div>')


def counter(cls: str, x: float, y: float, value: float, decimals: int, prefix: str, unit: str, size: float,
            color: str = "#fff") -> str:
    inner = (f'{html.escape(prefix)}<span class="n" data-to="{value}" data-dec="{decimals}">0</span>'
             f'<span class="u">{html.escape(unit)}</span>')
    return label_div(cls, x, y, inner, size, color)


def count_js(sel: str, at: float, dur: float, stagger: float = 0.0) -> str:
    """Tween the numbers in `sel` up from 0 (a property tween, so it renders correctly when seeked)."""
    return (f'gsap.utils.toArray("{sel} .n").forEach((el,i)=>{{const d=+el.dataset.dec;'
            f'tl.fromTo(el,{{innerText:0}},{{innerText:+el.dataset.to,duration:{dur},ease:"power2.out",'
            f'snap:{{innerText:d?Math.pow(10,-d):1}},'
            f'modifiers:{{innerText:v=>(+v).toLocaleString("en-US",{{minimumFractionDigits:d,maximumFractionDigits:d}})}}'
            f'}},{at}+i*{stagger});}});')


def build(spec: dict, w: int, h: int, box: tuple[float, float, float, float], background: str) -> tuple[str, float]:
    t = spec["template"]
    col = hfbuild.color(spec.get("color"), "teal")
    bx, by, bw, bh = box
    unit = min(bw, bh)
    title = spec.get("title", "")
    values = [float(v) for v in spec.get("values", [])]
    labels = spec.get("labels", [])
    colors = spec.get("colors") or []
    prefix, suffix = spec.get("prefix", ""), spec.get("unit", "")
    decimals = min(2, max((len(str(v).split(".")[1]) if "." in str(v) else 0 for v in spec.get("values", [])),
                          default=0))
    dur = float(spec.get("duration") or 4.0)
    svg, divs, js = [], [], []
    title_h = 0.0
    if title:
        tsize = unit * 0.075
        divs.append(label_div("title", bx + bw / 2, by + tsize * 0.9, html.escape(title), tsize))
        title_h = tsize * 2.0
        js.append('tl.from(".title",{y:20,opacity:0,duration:0.4,ease:"power2.out"},0.1);')
    cx, cy = bx + bw / 2, by + title_h + (bh - title_h) / 2

    if t == "circle-to-bars":
        if not values:
            raise ValueError("circle-to-bars needs --values")
        n = len(values)
        top_pad, label_pad = unit * 0.12, unit * 0.13
        ch = (bh - title_h) - top_pad - label_pad
        base = by + title_h + top_pad + ch
        slot = bw * 0.9 / n
        bar_w = min(slot * 0.62, unit * 0.22)
        x0 = bx + bw * 0.05
        r = unit * 0.16
        vmax = max(values) or 1
        for i, v in enumerate(values):
            bxi = x0 + slot * i + (slot - bar_w) / 2
            hi = max(bar_w * 0.15, ch * v / vmax)
            c = hfbuild.color(colors[i]) if i < len(colors) else col
            svg.append(f'<rect class="b" x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                       f'rx="{r:.1f}" fill="{c}" data-x="{bxi:.1f}" data-w="{bar_w:.1f}" data-h="{hi:.1f}" '
                       f'data-base="{base:.1f}"/>')
            divs.append(counter(f"val v{i}", bxi + bar_w / 2, base - hi - unit * 0.06, v, decimals, prefix, suffix,
                                unit * 0.07))
            if i < len(labels):
                divs.append(label_div(f"lab l{i}", bxi + bar_w / 2, base + label_pad * 0.55,
                                      html.escape(str(labels[i])), unit * 0.05, "#cfd3dc"))
        svg.append(f'<line class="axis" x1="{x0:.1f}" y1="{base:.1f}" x2="{x0 + slot * n:.1f}" y2="{base:.1f}" '
                   f'stroke="rgba(255,255,255,.25)" stroke-width="2"/>')
        js.append('gsap.set(".b",{transformOrigin:"50% 50%"});'
                  'tl.from(".b",{scale:0,duration:0.45,ease:"back.out(1.8)"},0.15);'
                  'tl.from(".axis",{opacity:0,duration:0.3},0.7);'
                  'gsap.utils.toArray(".b").forEach((b,i)=>{const d=b.dataset,s=+d.w;'
                  'tl.to(b,{attr:{x:+d.x,y:+d.base-s,width:s,height:s,rx:s/2},duration:0.5,ease:"power3.inOut"},0.75+i*0.05);'
                  'tl.to(b,{attr:{y:+d.base-(+d.h),height:+d.h,rx:Math.min(s/2,s*0.18)},duration:0.7,ease:"power3.out"},1.3+i*0.1);});'
                  'tl.from(".val",{opacity:0,y:12,duration:0.3,stagger:0.1},1.35);'
                  'tl.from(".lab",{opacity:0,y:12,duration:0.3,stagger:0.1},1.35);')
        js.append(count_js(".val", 1.3, 0.75, 0.1))
    elif t == "circle-to-donut":
        if not values:
            raise ValueError("circle-to-donut needs --values (parts of a whole)")
        total = sum(values) or 1
        R = unit * 0.27
        sw = R * 0.36
        svg.append(f'<circle class="disk" cx="{cx:.1f}" cy="{cy:.1f}" r="{R + sw / 2:.1f}" fill="{col}"/>')
        svg.append(f'<circle class="track" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="none" '
                   f'stroke="rgba(255,255,255,.12)" stroke-width="{sw:.1f}"/>')
        acc = 0.0
        legend_x = cx + R + sw + unit * 0.08
        for i, v in enumerate(values):
            frac = v / total
            c = hfbuild.color(colors[i]) if i < len(colors) else hfbuild.color(PALETTE[i % len(PALETTE)])
            svg.append(f'<circle class="seg" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="none" stroke="{c}" '
                       f'stroke-width="{sw:.1f}" transform="rotate(-90 {cx:.1f} {cy:.1f})" '
                       f'data-a="{acc * 100:.2f}" data-b="{(acc + frac) * 100:.2f}"/>')
            name = html.escape(str(labels[i])) if i < len(labels) else ""
            ly = cy - (len(values) - 1) * unit * 0.055 + i * unit * 0.11
            divs.append(label_div(f"leg g{i}", legend_x, ly, f'<span class="dot" style="background:{c}"></span>{name} '
                                  f'<b>{round(frac * 100)}%</b>', unit * 0.05, "#e8eaf0", "left"))
            acc += frac
        js.append('gsap.set(".disk",{transformOrigin:"50% 50%"});'
                  'tl.from(".disk",{scale:0,duration:0.45,ease:"back.out(1.8)"},0.15);'
                  'tl.to(".disk",{scale:0.62,opacity:0,duration:0.55,ease:"power3.in"},0.75);'
                  'tl.from(".track",{opacity:0,duration:0.35},0.85);'
                  'gsap.utils.toArray(".seg").forEach((s,i)=>{tl.fromTo(s,{drawSVG:`${s.dataset.a}% ${s.dataset.a}%`},'
                  '{drawSVG:`${s.dataset.a}% ${s.dataset.b}%`,duration:0.55,ease:"power2.inOut"},1.1+i*0.35);});'
                  'tl.from(".leg",{opacity:0,x:-16,duration:0.3,stagger:0.35},1.25);')
    elif t == "dot-to-line":
        if len(values) < 2:
            raise ValueError("dot-to-line needs at least two --values")
        n = len(values)
        top_pad, label_pad = unit * 0.14, unit * 0.12
        ch = (bh - title_h) - top_pad - label_pad
        base = by + title_h + top_pad + ch
        x0, x1 = bx + bw * 0.08, bx + bw * 0.92
        vmin, vmax = min(values + [0]), max(values)
        span = (vmax - vmin) or 1
        pts = [(x0 + (x1 - x0) * i / (n - 1), base - ch * (v - vmin) / span) for i, v in enumerate(values)]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        svg.append(f'<line class="axis" x1="{x0:.1f}" y1="{base:.1f}" x2="{x1:.1f}" y2="{base:.1f}" '
                   f'stroke="rgba(255,255,255,.25)" stroke-width="2"/>')
        svg.append(f'<path class="ln" d="{d}" fill="none" stroke="{col}" stroke-width="{unit * 0.018:.1f}" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
        for i, (x, y) in enumerate(pts):
            svg.append(f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="{unit * 0.022:.1f}" fill="#fff" '
                       f'stroke="{col}" stroke-width="{unit * 0.01:.1f}"/>')
            divs.append(counter(f"val v{i}", x, y - unit * 0.07, values[i], decimals, prefix, suffix, unit * 0.055))
            if i < len(labels):
                divs.append(label_div(f"lab l{i}", x, base + label_pad * 0.5, html.escape(str(labels[i])),
                                      unit * 0.045, "#cfd3dc"))
        draw, step = 1.6, 1.6 / (n - 1)
        js.append('gsap.set(".pt",{transformOrigin:"50% 50%"});'
                  'tl.from(".axis",{opacity:0,duration:0.3},0.2);'
                  f'tl.from(".pt",{{scale:0,duration:0.3,ease:"back.out(2.4)",stagger:{step:.3f}}},0.35);'
                  f'tl.fromTo(".ln",{{drawSVG:"0%"}},{{drawSVG:"100%",duration:{draw},ease:"none"}},0.45);'
                  f'tl.from(".val",{{opacity:0,y:10,duration:0.25,stagger:{step:.3f}}},0.5);'
                  f'tl.from(".lab",{{opacity:0,y:10,duration:0.25,stagger:{step:.3f}}},0.5);')
        js.append(count_js(".val", 0.5, 0.5, step))
    elif t in ("check", "cross"):
        good = t == "check"
        c = hfbuild.color(spec.get("color"), "green" if good else "red")
        R = unit * 0.2
        s = R * 0.62
        circle_path = (f"M{cx - s:.1f},{cy:.1f} A{s:.1f},{s:.1f} 0 1,1 {cx + s:.1f},{cy:.1f} "
                       f"A{s:.1f},{s:.1f} 0 1,1 {cx - s:.1f},{cy:.1f}Z")
        k = s / 100
        if good:   # a thick check mark
            shape = (f"M{cx - 62 * k:.1f},{cy + 2 * k:.1f} L{cx - 36 * k:.1f},{cy - 24 * k:.1f} "
                     f"L{cx - 14 * k:.1f},{cy - 2 * k:.1f} L{cx + 42 * k:.1f},{cy - 58 * k:.1f} "
                     f"L{cx + 68 * k:.1f},{cy - 32 * k:.1f} L{cx - 14 * k:.1f},{cy + 50 * k:.1f} Z")
        else:      # a thick X
            a, b = 64, 22
            pts = [(-a, -a + b), (-a + b, -a), (0, -b), (a - b, -a), (a, -a + b), (b, 0), (a, a - b), (a - b, a),
                   (0, b), (-a + b, a), (-a, a - b), (-b, 0)]
            shape = "M" + " L".join(f"{cx + x * k:.1f},{cy + y * k:.1f}" for x, y in pts) + " Z"
        svg.append(f'<circle class="ring" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="none" stroke="{c}" '
                   f'stroke-width="{R * 0.06:.1f}"/>')
        svg.append(f'<circle class="disk" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="{c}"/>')
        svg.append(f'<path class="glyph" d="{circle_path}" fill="#fff"/>')
        svg.append(f'<path id="target" d="{shape}" style="display:none"/>')
        if spec.get("label"):
            divs.append(label_div("title2", cx, cy + R + unit * 0.12, html.escape(spec["label"]), unit * 0.07))
            js.append('tl.from(".title2",{y:16,opacity:0,duration:0.35,ease:"power2.out"},1.0);')
        # fast: the circle is up by 0.3 s and the symbol is complete at ~0.75 s, so it lands on the word
        js.append('gsap.set(".disk,.glyph,.ring",{transformOrigin:"50% 50%"});'
                  'tl.from(".disk,.glyph",{scale:0,duration:0.3,ease:"back.out(1.9)"},0.0);'
                  'tl.to(".glyph",{morphSVG:{shape:"#target",shapeIndex:0},duration:0.45,ease:"power3.inOut"},0.3);'
                  'tl.fromTo(".ring",{scale:1,opacity:0.9},{scale:1.45,opacity:0,duration:0.6,ease:"power2.out"},0.7);'
                  'tl.to(".disk,.glyph",{scale:1.06,duration:0.12,yoyo:true,repeat:1,ease:"power1.inOut"},0.72);')
    elif t == "ring-to-number":
        if not values:
            raise ValueError("ring-to-number needs one --values number (and optionally --max, default 100)")
        v = values[0]
        vmax = float(spec.get("max") or 100)
        R = unit * 0.25
        sw = R * 0.16
        svg.append(f'<circle class="track" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="none" '
                   f'stroke="rgba(255,255,255,.12)" stroke-width="{sw:.1f}"/>')
        svg.append(f'<circle class="arc" cx="{cx:.1f}" cy="{cy:.1f}" r="{R:.1f}" fill="none" stroke="{col}" '
                   f'stroke-width="{sw:.1f}" stroke-linecap="round" transform="rotate(-90 {cx:.1f} {cy:.1f})"/>')
        svg.append(f'<circle class="dotc" cx="{cx:.1f}" cy="{cy:.1f}" r="{R * 0.5:.1f}" fill="{col}"/>')
        divs.append(counter("big", cx, cy, v, decimals, prefix, suffix, R * 0.55))
        if labels:
            divs.append(label_div("lab", cx, cy + R + sw + unit * 0.07, html.escape(str(labels[0])), unit * 0.055,
                                  "#cfd3dc"))
        pct = max(0.0, min(1.0, v / vmax)) * 100
        js.append('gsap.set(".dotc",{transformOrigin:"50% 50%"});'
                  'tl.from(".dotc",{scale:0,duration:0.4,ease:"back.out(2)"},0.1);'
                  f'tl.to(".dotc",{{attr:{{r:{R:.1f}}},opacity:0,duration:0.5,ease:"power2.in"}},0.55);'
                  'tl.from(".track",{opacity:0,duration:0.3},0.75);'
                  f'tl.fromTo(".arc",{{drawSVG:"0%"}},{{drawSVG:"{pct:.2f}%",duration:1.2,ease:"power2.out"}},0.85);'
                  'tl.from(".big,.lab",{opacity:0,scale:0.8,duration:0.3,ease:"power2.out"},0.85);')
        js.append(count_js(".big", 0.85, 1.2))
    elif t == "shape-sequence":
        R = unit * 0.2

        def poly(points):
            return "M" + " L".join(f"{cx + x * R:.1f},{cy + y * R:.1f}" for x, y in points) + " Z"
        circle = (f"M{cx - R:.1f},{cy:.1f} A{R:.1f},{R:.1f} 0 1,1 {cx + R:.1f},{cy:.1f} "
                  f"A{R:.1f},{R:.1f} 0 1,1 {cx - R:.1f},{cy:.1f}Z")
        square = poly([(-0.85, -0.85), (0.85, -0.85), (0.85, 0.85), (-0.85, 0.85)])
        tri = poly([(0, -1.05), (0.98, 0.75), (-0.98, 0.75)])
        star = poly([(math.cos(math.pi / 2 + i * math.pi / 5) * (1.05 if i % 2 == 0 else 0.45),
                      -math.sin(math.pi / 2 + i * math.pi / 5) * (1.05 if i % 2 == 0 else 0.45)) for i in range(10)])
        cols = [hfbuild.color(c) for c in (colors or ["teal", "yellow", "purple", "green"])]
        svg.append(f'<path class="sh" d="{circle}" fill="{cols[0]}"/>')
        for k, dd in enumerate((square, tri, star)):
            svg.append(f'<path id="s{k}" d="{dd}" style="display:none"/>')
        step = max(0.7, (dur - 0.8) / 4)
        js.append('gsap.set(".sh",{transformOrigin:"50% 50%"});'
                  'tl.from(".sh",{scale:0,duration:0.4,ease:"back.out(2)"},0.1);')
        for k in range(3):
            js.append(f'tl.to(".sh",{{morphSVG:"#s{k}",fill:"{cols[(k + 1) % len(cols)]}",rotation:"+=30",'
                      f'duration:{step * 0.7:.2f},ease:"power3.inOut"}},{0.5 + k * step:.2f});')
        js.append(f'tl.to(".sh",{{morphSVG:"{circle}",fill:"{cols[0]}",rotation:"+=30",duration:{step * 0.7:.2f},'
                  f'ease:"power3.inOut"}},{0.5 + 3 * step:.2f});')
    else:
        raise ValueError(f"unknown template {t!r}")

    js.append(f'tl.to("#stage",{{opacity:0,scale:0.97,duration:0.3,ease:"power2.in"}},{dur - 0.32:.2f});')
    panel = ""
    if background == "glass":
        panel = (f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="{unit * 0.06:.1f}" '
                 f'fill="rgba(12,13,18,0.78)" stroke="rgba(255,255,255,0.18)" stroke-width="2"/>')
    bg_css = "transparent" if background in ("glass", "transparent") else BG
    grid = '<div class="grid"></div><div class="vig"></div>' if background == "dark" else ""
    page = f"""<!doctype html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width={w}, height={h}">
{hfbuild.scripts_html()}
<style>{hfbuild.FONT_CSS}
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg_css}}}
#root{{position:relative;width:{w}px;height:{h}px}}
#stage{{position:absolute;inset:0;transform-origin:50% 50%}}
svg{{position:absolute;inset:0}}
.grid{{position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(255,255,255,.035) 0 1px,transparent 1px {unit * 0.09:.0f}px),repeating-linear-gradient(90deg,rgba(255,255,255,.035) 0 1px,transparent 1px {unit * 0.09:.0f}px)}}
.vig{{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 35%,#000 100%)}}
.title,.title2,.val,.lab,.leg,.big{{position:absolute;white-space:nowrap;font-family:'Montserrat XB';font-weight:800;line-height:1}}
.dot{{display:inline-block;width:.7em;height:.7em;border-radius:50%;margin-right:.4em;vertical-align:middle}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{w}" data-height="{h}">
  <div id="stage" class="clip" data-start="0" data-duration="{dur}" data-track-index="0">
    {grid}
    <svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{panel}{''.join(svg)}</svg>
    {''.join(divs)}
  </div>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{''.join(js)}
tl.to({{}}, {{ duration: {dur} }}, 0);
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
"""
    return page, dur


def chart_box(w: int, h: int, mode: str, position: str) -> tuple[float, float, float, float]:
    vertical = h > w
    if mode != "overlay":
        return (w * 0.07, h * 0.24, w * 0.86, h * 0.48) if vertical else (w * 0.14, h * 0.12, w * 0.72, h * 0.76)
    if vertical:
        return (w * 0.06, h * 0.06 if position == "top" else h * 0.58, w * 0.88, h * 0.34)
    return (w * 0.05 if position == "left" else w * 0.55, h * 0.18, w * 0.4, h * 0.62)


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Morphing-shape charts and symbols, standalone or inside a video.")
    p.add_argument("--template", choices=TEMPLATES, required=True)
    p.add_argument("--title", default="")
    p.add_argument("--label", default="", help="caption under a check / cross")
    p.add_argument("--labels", default="", help="comma-separated category names")
    p.add_argument("--values", default="", help="comma-separated numbers (from the user or the speaker)")
    p.add_argument("--colors", default="", help="comma-separated colors per bar / segment / shape")
    p.add_argument("--prefix", default="", help="e.g. $")
    p.add_argument("--unit", default="", help="e.g. %% or x")
    p.add_argument("--max", type=float, default=100, help="ring-to-number: the value of a full ring")
    p.add_argument("--color", default="", help="teal, green, red, yellow, purple, blue, orange or #hex")
    p.add_argument("--duration", type=float, default=4.0, help="seconds on screen (default 4)")
    p.add_argument("--video", type=Path, help="put the graphic inside this video (default: standalone clip)")
    p.add_argument("--at", type=float, default=0.0, help="when it appears in the video (seconds)")
    p.add_argument("--mode", choices=("cutaway", "overlay"), default="cutaway",
                   help="cutaway = full-screen graphic, audio continues (default); overlay = glass panel beside the speaker")
    p.add_argument("--position", default="auto", help="overlay panel: left, right, top, bottom (default: away from the face)")
    p.add_argument("--size", default="1920x1080", help="standalone canvas, e.g. 1080x1920 (default 1920x1080)")
    p.add_argument("--transparent", action="store_true", help="standalone: transparent WebM instead of a dark MP4")
    p.add_argument("--out", type=Path)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    spec = {"template": args.template, "title": args.title, "label": args.label, "labels": split(args.labels),
            "values": split(args.values), "colors": split(args.colors), "prefix": args.prefix, "unit": args.unit,
            "max": args.max, "color": args.color or None, "duration": args.duration}
    try:
        [float(v) for v in spec["values"]]
    except ValueError:
        print("--values must be numbers, e.g. --values 12,48")
        return 2
    root = project_root()
    name = f"morph-{args.template}-{hfbuild.slug(args.title or args.label or 'clip')}"
    try:
        if args.video:
            video = args.video if args.video.exists() else root / "input" / args.video
            info = probe(video)
            s = min(1.0, 1920 / max(info.width, info.height))
            w, h = int(info.width * s) // 2 * 2, int(info.height * s) // 2 * 2
            pos = args.position
            if args.mode == "overlay" and pos == "auto":
                from layout import analyze
                lay = analyze(video, info)
                if lay.vertical:
                    pos = "top" if (lay.face and lay.face[1] > 0.35) else "bottom"
                else:
                    pos = lay.text_zone if lay.text_zone in ("left", "right") else "right"
            symbol = args.template in ("check", "cross")
            if args.mode == "overlay" and symbol:
                # a check / X floats on its own (no panel), compact, in the free zone
                side = min(w, h) * 0.36
                if h > w:
                    box = ((w - side) / 2, h * 0.08 if pos == "top" else h * 0.60, side, side)
                else:
                    box = (w * 0.08 if pos == "left" else w * 0.92 - side, (h - side) / 2, side, side)
                page, dur = build(spec, w, h, box, "transparent")
            else:
                page, dur = build(spec, w, h, chart_box(w, h, args.mode, pos),
                                  "glass" if args.mode == "overlay" else "dark")
            comp = hfbuild.new_composition(name, page)
            ext = "webm" if args.mode == "overlay" else "mp4"
            clip = hfbuild.render(comp, root / "work" / "morph" / f"{name}.{ext}", fps=hfbuild.video_fps(info),
                                  transparent=args.mode == "overlay")
            out = args.out or root / "output" / f"{video.stem}.mp4"
            if out.resolve() == video.resolve() or (out.exists() and not args.overwrite):
                print(f"{out} exists or is the source (use --out or --overwrite).")
                return 1
            hfbuild.overlay(video, [{"path": clip, "start": args.at}], out)
            moments = [args.at + 0.2, args.at + 0.8, args.at + 0.8 * dur] if symbol else \
                [args.at + f * dur for f in (0.15, 0.45, 0.8)]
            sheet = hfbuild.contact_sheet(out, moments, root / "work" / f"{video.stem}.morph-check.png")
            print(f"OK  {out}  ({args.template} at {fmt_time(args.at)} for {dur:.1f}s, {args.mode})")
        else:
            w, h = (int(x) for x in args.size.lower().split("x"))
            page, dur = build(spec, w, h, chart_box(w, h, "cutaway", "auto"),
                              "transparent" if args.transparent else "dark")
            comp = hfbuild.new_composition(name, page)
            out = args.out or root / "output" / f"{name}.{'webm' if args.transparent else 'mp4'}"
            if out.exists() and not args.overwrite:
                print(f"{out} already exists (use --overwrite or --out).")
                return 1
            hfbuild.render(comp, out, fps=30, transparent=args.transparent)
            sheet = hfbuild.contact_sheet(out, [f * dur for f in (0.12, 0.35, 0.6, 0.85)],
                                          root / "work" / f"{name}.morph-check.png", cols=4)
            print(f"OK  {out}  ({args.template}, {dur:.1f}s, {w}x{h})")
    except (SetupError, ValueError, RuntimeError) as e:
        print(f"FAILED: {e}")
        return 1
    print(f"Check frames: {sheet}")
    print(f"Composition (editable): {comp / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
