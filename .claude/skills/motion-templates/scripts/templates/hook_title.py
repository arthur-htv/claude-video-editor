"""Hook title: the video's promise as a big title card over the first seconds, with an optional pill under it.
An overlay at the top, so the speaker stays visible.

{"template": "hook-title", "start": 0.0, "end": 2.6, "title": "How to pull *cash* off a credit card",
 "sub": "Step by step · part 2", "position": "top"}

position: "top" (default), "center", or the top edge as a fraction of the height (0.1).
"""
from __future__ import annotations

from tpl import Scene, esc, rich


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    bw = W * (0.88 if ctx.vertical else 0.56)
    pos = spec.get("position", "top")
    y = H * float({"top": 0.055, "center": 0.36}.get(pos, pos))
    title, sub = spec["title"], spec.get("sub", "")
    fs = ctx.fit(title, bw - u * 0.1, 2, u * (0.078 if ctx.vertical else 0.07))
    pill = f'<div class="pill hook-sub" style="font-size:{u * 0.03:.0f}px">{esc(sub)}</div>' if sub else ""
    html = (f'<div class="hook" style="left:{(W - bw) / 2:.0f}px;top:{y:.0f}px;width:{bw:.0f}px">'
            f'<div class="hook-box"><div class="hook-t disp" style="font-size:{fs}px">{rich(title)}</div></div>{pill}</div>')
    css = """
.hook{position:absolute;text-align:center}
.hook-box{background:var(--panel);border:calc(var(--u)*.006) solid var(--hook-edge,var(--text));border-radius:calc(var(--u)*.026);
 padding:.32em .5em .62em;box-shadow:var(--shadow)}
.hook-t{line-height:1.12;color:var(--text)}
.hook-sub{position:absolute;left:50%;bottom:0}
"""
    a = ctx.t(spec.get("at"))
    js = [f'tl.from(".hook-box",{{y:{-u * 0.05:.0f},opacity:0,scale:0.92,duration:0.45,ease:"{ctx.ease("back.out(1.7)")}"}},{a:.2f});']
    if sub:
        js += ['tl.set(".hook-sub",{xPercent:-50,yPercent:50},0);',
               f'tl.from(".hook-sub",{{scale:0,duration:0.35,ease:"{ctx.ease("back.out(2.2)")}"}},{a + 0.25:.2f});']
    js.append(f'tl.to(".hook",{{opacity:0,y:{-u * 0.03:.0f},duration:0.3,ease:"power2.in"}},{ctx.dur - 0.32:.2f});')
    return Scene(html=html, css=css, js=js, overlay=True, checks=[min(a + 0.9, ctx.dur - 0.4)])
