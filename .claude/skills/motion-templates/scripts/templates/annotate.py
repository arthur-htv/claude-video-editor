"""Hand-drawn marks over the footage: a wobbly circle around something in the frame (the card in the speaker's hand,
a number on a screen) or a squiggle under it, drawn on as it is mentioned, with an optional label. An overlay.
Look and motion adapted from HeyGen HyperFrames' hw-callout-circle and hw-underline (Apache-2.0, see
assets/registry/NOTICE.md): the same wobble maths, drawn in the theme's accent colour.

{"template": "annotate", "start": 5.0, "end": 9.0, "marks": [
  {"shape": "circle", "x": 0.5, "y": 0.55, "w": 0.42, "h": 0.14, "at": 5.2, "label": "The *card*"},
  {"shape": "underline", "x": 0.5, "y": 0.66, "w": 0.5, "at": 6.4, "until": 8.8}]}

x, y = the centre of the thing being marked; w, h = its size (fractions of the frame's width and height; an underline
only needs w). until = when the mark leaves (default: the end). label = a short line under the mark (above it when the
mark sits in the lower half). The lines "boil" (a light hand-drawn jitter), except in themes without bounce (apple).
"""
from __future__ import annotations

import math

from tpl import Scene, rich

SHAPES = ("circle", "underline")


def _hash(n: float, seed: int) -> float:
    """hwHash from the registry: a deterministic value in -1..1."""
    x = math.sin(n * 127.1 + seed * 311.7) * 43758.5453
    return (x - math.floor(x)) * 2 - 1


def circle_path(cx: float, cy: float, rx: float, ry: float, seed: int) -> str:
    """hwWobbleEllipse, left open with a 10% overshoot so the pen stroke overlaps its start like a real one."""
    n, pts = 14, []
    for i in range(17):
        ang, wr = -2.3 + i / n * 2 * math.pi, 1 + _hash(i * 13 + 5, seed) * 0.03 + 0.06 * i / n
        pts.append((cx + math.cos(ang) * rx * wr, cy + math.sin(ang) * ry * wr))
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for p, q in zip(pts[1:-1], pts[2:]):
        d += f" Q{p[0]:.1f} {p[1]:.1f} {(p[0] + q[0]) / 2:.1f} {(p[1] + q[1]) / 2:.1f}"
    return d


def underline_path(x0: float, y: float, w: float, s: float, seed: int) -> str:
    """hwMarkPath "underline": a squiggle, scaled by s (1.0 = a 1080 px short side)."""
    def wob(i, r=5):
        return _hash(i, seed) * r * s
    segs = max(5, round(w / (95 * s)))
    d = f"M{x0 + 2 * s:.1f} {y + wob(0, 4):.1f}"
    for i in range(1, segs + 1):
        x = x0 + w / segs * i
        d += (f" Q{x - w / segs / 2 + wob(i * 4 + 1, 9):.1f} {y + (-1 if i % 2 else 1) * (9 * s + wob(i * 4 + 2, 4)):.1f}"
              f" {x:.1f} {y + wob(i * 4 + 3, 4):.1f}")
    return d


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    marks = spec.get("marks") or []
    if not marks:
        raise ValueError('annotate: give at least one entry in "marks"')
    s, calm = u / 1080, "pop" in ctx.theme
    paths, labels, js, checks = [], [], [], []
    for k, m in enumerate(marks):
        shape = m.get("shape", "circle")
        if shape not in SHAPES:
            raise ValueError(f"annotate: unknown shape {shape!r} (have: {', '.join(SHAPES)})")
        a = ctx.t(m.get("at"))
        b = ctx.t(m.get("until"), default=ctx.end)
        cx, cy = float(m.get("x", 0.5)) * W, float(m.get("y", 0.5)) * H
        w = float(m.get("w", 0.3)) * W
        if shape == "circle":
            rh = float(m.get("h", 0.1)) * H / 2
            d, draw, edge = circle_path(cx, cy, w / 2, rh, k + 4), 0.7, rh
        else:
            d, draw, edge = underline_path(cx - w / 2, cy, w, s, k + 4), 0.55, u * 0.012
        draw = min(draw, max(0.25, (b - a) * 0.4))
        paths.append(f'<g id="m{k}"><path id="mp{k}" class="mk" d="{d}"/></g>')
        js += [f'tl.set("#m{k}",{{svgOrigin:"{cx:.0f} {cy:.0f}"}},0);',
               f'tl.fromTo("#mp{k}",{{drawSVG:"0%"}},{{drawSVG:"100%",duration:{draw:.2f},ease:"power2.inOut"}},{a:.2f});']
        if not calm:                                   # boil: a new jitter pose every 0.1 s, baked in so seeking is exact
            for i in range(int((b - a) / 0.1)):
                js.append(f'tl.set("#m{k}",{{x:{_hash(i * 3, k + 5) * 1.6 * s:.2f},y:{_hash(i * 3 + 1, k + 5) * 1.6 * s:.2f},'
                          f'rotation:{_hash(i * 3 + 2, k + 5) * 0.5:.2f}}},{a + i * 0.1:.2f});')
        out = [f"#m{k}"]
        if m.get("label"):
            below = cy < H * 0.5
            ly = cy + edge + u * 0.03 if below else cy - edge - u * 0.03
            labels.append(f'<div class="mlab disp" id="ml{k}" style="left:{cx:.0f}px;top:{ly:.0f}px;'
                          f'font-size:{ctx.fit(m["label"], W * 0.8, 1, u * 0.05)}px">{rich(m["label"])}</div>')
            js += [f'tl.set("#ml{k}",{{xPercent:-50,yPercent:{0 if below else -100}}},0);',
                   f'tl.fromTo("#ml{k}",{{opacity:0,y:{u * 0.02 * (-1 if below else 1):.0f}}},{{opacity:1,y:0,duration:0.35,'
                   f'ease:"{ctx.ease("back.out(2)")}"}},{min(a + draw * 0.8, b):.2f});']
            out.append(f"#ml{k}")
        js.append(f'tl.to("{",".join(out)}",{{opacity:0,duration:0.3,ease:"power2.in"}},{max(a, b - 0.3):.2f});')
        checks.append(min(a + draw + 0.45, max(a, b - 0.1)))
    css = """
.marks{position:absolute;left:0;top:0;overflow:visible}
.mk{fill:none;stroke:var(--accent);stroke-width:calc(var(--u)*.0075);stroke-linecap:round;stroke-linejoin:round;
 filter:drop-shadow(0 0 calc(var(--u)*.004) rgba(0,0,0,.55))}
.mlab{position:absolute;white-space:nowrap;color:#fff;line-height:1.1;
 text-shadow:0 0 .05em rgba(0,0,0,.9),0 0 .12em rgba(0,0,0,.75),0 .05em .2em rgba(0,0,0,.6),0 0 .02em rgba(0,0,0,.95)}
"""
    svg = f'<svg class="marks" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{"".join(paths)}</svg>'
    return Scene(html=svg + "".join(labels), css=css, js=js, overlay=True, checks=checks)
