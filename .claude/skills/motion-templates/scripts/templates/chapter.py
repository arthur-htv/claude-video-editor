"""Section card between parts of a video: a label pill, a big title and an optional icon. A short full-screen cutaway
(1.5 to 2.5 s).

{"template": "chapter", "start": 54.6, "end": 56.6, "label": "Option 2", "title": "Buy For Me", "icon": "globe"}
"""
from __future__ import annotations

from tpl import Scene, esc, icon, rich


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    title = spec["title"]
    ic = f'<div class="tile chic">{icon(spec["icon"])}</div>' if spec.get("icon") else ""
    label = f'<div class="pill chl" style="font-size:{u * 0.04:.0f}px">{esc(spec["label"])}</div>' if spec.get("label") else ""
    html = (f'<div class="chap" style="top:{H * 0.42:.0f}px">{ic}{label}'
            f'<div class="cht2 disp" style="font-size:{ctx.fit(title, W * 0.84, 2, u * 0.11)}px">{rich(title)}</div></div>')
    css = """
.chap{position:absolute;left:0;width:100%;display:flex;flex-direction:column;align-items:center;gap:calc(var(--u)*.035);text-align:center}
.chic{width:calc(var(--u)*.2);height:calc(var(--u)*.2)}
.cht2{line-height:1.08;width:84%}
"""
    a = ctx.t(spec.get("at"))
    js = ['tl.set(".chap",{yPercent:-50},0);']
    if ic:
        js.append(f'tl.from(".chic",{{scale:0,rotation:-12,duration:0.4,ease:"{ctx.ease("back.out(2)")}"}},{a + 0.05:.2f});')
    if label:
        js.append(f'tl.from(".chl",{{opacity:0,y:{u * 0.02:.0f},duration:0.3}},{a + 0.15:.2f});')
    js += [f'tl.from(".cht2",{{opacity:0,scale:0.9,duration:0.45,ease:"{ctx.ease("back.out(1.6)")}"}},{a + 0.25:.2f});',
           f'tl.to(".chap",{{opacity:0,scale:1.04,duration:0.25,ease:"power2.in"}},{ctx.dur - 0.27:.2f});']
    return Scene(html=html, css=css, js=js, checks=[min(a + 0.9, ctx.dur - 0.35)])
