"""Label tags: short labels that pop on when a term is said, optionally with a line pointing at something
in the frame (the card in the speaker's hand, a screen). An overlay.

{"template": "tag", "start": 8.0, "end": 12.0, "tags": [
  {"text": "Manufactured spending", "at": 8.3, "until": 10.6, "x": 0.5, "y": 0.06},
  {"text": "Business credit card", "at": 9.1, "x": 0.72, "y": 0.66, "point": [0.45, 0.6], "style": "box"}]}

x, y = the tag's centre as fractions of the frame; point = [x, y] the line points at; style "pill" (default) or
"box"; until = when it leaves (default 2.5 s after it appears, or the end).
"""
from __future__ import annotations

from tpl import Scene, esc


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    tags = spec.get("tags") or []
    if not tags:
        raise ValueError("tag: give at least one entry in \"tags\"")
    html, lines, js, checks = [], [], [], []
    for k, t in enumerate(tags):
        a = ctx.t(t.get("at"))
        b = ctx.t(t.get("until"), default=ctx.start + min(ctx.dur, a + 2.5))
        x, y = float(t.get("x", 0.5)) * W, float(t.get("y", 0.07)) * H
        cls = "tagbox" if t.get("style") == "box" else "pill"
        html.append(f'<div class="tag {cls}" id="g{k}" style="left:{x:.0f}px;top:{y:.0f}px;font-size:{u * 0.034:.0f}px">'
                    f'{esc(t["text"])}</div>')
        js.append(f'tl.set("#g{k}",{{xPercent:-50,yPercent:-50}},0);')
        js.append(f'tl.fromTo("#g{k}",{{opacity:0,scale:0.7}},{{opacity:1,scale:1,duration:0.35,ease:"{ctx.ease("back.out(2)")}"}},{a:.2f});')
        if t.get("point"):
            px, py = float(t["point"][0]) * W, float(t["point"][1]) * H
            lines.append(f'<path id="p{k}" class="ptr" d="M{x:.1f},{y:.1f} L{px:.1f},{py:.1f}"/>'
                         f'<circle id="d{k}" class="dot" cx="{px:.1f}" cy="{py:.1f}" r="{u * 0.011:.1f}"/>')
            js.append(f'tl.fromTo("#p{k}",{{drawSVG:"0%"}},{{drawSVG:"100%",duration:0.35,ease:"power2.out"}},{a + 0.15:.2f});')
            js.append(f'tl.fromTo("#d{k}",{{opacity:0,scale:0,transformOrigin:"50% 50%"}},{{opacity:1,scale:1,duration:0.25}},'
                      f'{a + 0.45:.2f});')
            js.append(f'tl.to("#p{k},#d{k}",{{opacity:0,duration:0.25}},{max(a, b - 0.25):.2f});')
        js.append(f'tl.to("#g{k}",{{opacity:0,scale:0.9,duration:0.25,ease:"power2.in"}},{max(a, b - 0.25):.2f});')
        checks.append(min(a + 0.8, b - 0.1))
    svg = f'<svg class="ptrs" width="{W}" height="{H}">{"".join(lines)}</svg>' if lines else ""
    css = """
.ptrs{position:absolute;left:0;top:0;overflow:visible}
.ptr{fill:none;stroke:var(--text);stroke-width:calc(var(--u)*.004);stroke-linecap:round;filter:drop-shadow(0 0 3px rgba(0,0,0,.7))}
.dot{fill:var(--accent);stroke:var(--text);stroke-width:calc(var(--u)*.003)}
.tag{position:absolute;box-shadow:var(--shadow)}
.tagbox{display:inline-block;background:var(--panel);color:var(--text);border:calc(var(--u)*.003) solid var(--text);
 border-radius:calc(var(--u)*.01);padding:.25em .6em .2em;font-family:var(--font-display);text-transform:var(--case);white-space:nowrap}
"""
    return Scene(html=svg + "".join(html), css=css, js=js, overlay=True, checks=checks)
