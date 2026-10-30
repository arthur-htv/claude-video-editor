"""End card: your handle plus a Save / Follow button that gets tapped. An overlay over the last seconds.

{"template": "cta", "start": 82.0, "end": 85.4, "handle": "@yourhandle", "text": "Save this", "icon": "bookmark", "y": 0.55}

icon: bookmark (save), user-plus (follow), bell, heart, share-2, send. y = the card's centre as a fraction of the height.
"""
from __future__ import annotations

from tpl import Scene, esc, icon


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    a = ctx.t(spec.get("at"))
    y = float(spec.get("y", 0.55)) * H
    handle = spec.get("handle", "")
    hpill = f'<div class="handle" style="font-size:{u * 0.034:.0f}px">{esc(handle)}</div>' if handle else ""
    html = (f'<div class="cta" style="left:{W / 2:.0f}px;top:{y:.0f}px">{hpill}'
            f'<div class="btn" style="font-size:{u * 0.05:.0f}px"><span class="bic">{icon(spec.get("icon", "bookmark"))}</span>'
            f'<span class="disp">{esc(spec.get("text", "Save this"))}</span></div></div>')
    css = """
.cta{position:absolute;display:flex;flex-direction:column;align-items:center;gap:calc(var(--u)*.022)}
.handle{background:var(--text);color:var(--bg);border-radius:999px;padding:.3em .8em .25em;font-family:var(--font-body);
 white-space:nowrap;box-shadow:var(--shadow)}
.btn{display:flex;align-items:center;gap:.45em;background:var(--panel);color:var(--text);border:calc(var(--u)*.005) solid var(--accent);
 border-radius:calc(var(--u)*.02);padding:.45em .9em .4em;box-shadow:var(--glow),var(--shadow);white-space:nowrap}
.bic{width:1.05em;height:1.05em;color:var(--accent);display:inline-flex}
.bic .ic{width:100%;height:100%;stroke-width:2.2}
"""
    accent = ctx.var("accent")
    js = ['tl.set(".cta",{xPercent:-50,yPercent:-50},0);']
    if handle:
        js.append(f'tl.from(".handle",{{opacity:0,y:{u * 0.03:.0f},duration:0.35,ease:"{ctx.ease("back.out(2)")}"}},{a:.2f});')
    js += [f'tl.from(".btn",{{opacity:0,scale:0.6,duration:0.4,ease:"{ctx.ease("back.out(2)")}"}},{a + 0.2:.2f});',
           f'tl.to(".btn",{{scale:0.92,duration:{0.3 if "pop" in ctx.theme else 0.12},yoyo:true,repeat:1,ease:"power1.inOut"}},{a + 1.0:.2f});',
           f'tl.to(".bic .ic",{{fill:"{accent}",duration:0.25}},{a + 1.05:.2f});',
           f'tl.to(".cta",{{opacity:0,duration:0.3}},{ctx.dur - 0.32:.2f});']
    return Scene(html=html, css=css, js=js, overlay=True, checks=[min(a + 1.4, ctx.dur - 0.4)])
