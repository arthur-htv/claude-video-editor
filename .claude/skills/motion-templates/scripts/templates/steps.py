"""Numbered steps or tips that appear one by one as they are said; earlier ones dim so the newest stands out.
A full-screen cutaway, or a panel over the speaker with "mode": "overlay".

{"template": "steps", "start": 20.0, "end": 31.0, "title": "3 rules for *business credit*",
 "items": [{"text": "Pay the full balance every month", "at": 21.0},
           {"text": "Keep usage under 30%", "at": 24.5, "icon": "percent"},
           {"text": "Never miss a payment", "at": 28.0}],
 "mode": "cutaway"}

mode: "cutaway" (default) or "overlay". position (overlay only): vertical video "top" or "bottom" (default),
wide video "left" or "right" (default). An item's icon replaces its number.
"""
from __future__ import annotations

from tpl import Scene, icon, rich


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    items = spec.get("items") or []
    if not 1 <= len(items) <= 8:
        raise ValueError("steps: give 1 to 8 items")
    overlay = spec.get("mode", "cutaway") == "overlay"
    pos = spec.get("position")
    if overlay and ctx.vertical:
        bx, bw, by, bh = W * 0.05, W * 0.9, (H * 0.05 if pos == "top" else H * 0.56), H * 0.36
    elif overlay:
        bx, bw, by, bh = (W * 0.05 if pos == "left" else W * 0.53), W * 0.42, H * 0.12, H * 0.76
    elif ctx.vertical:
        bx, bw, by, bh = W * 0.08, W * 0.84, H * 0.12, H * 0.62
    else:
        bx, bw, by, bh = W * 0.2, W * 0.6, H * 0.1, H * 0.8
    pad = u * (0.04 if overlay else 0.0)
    title = spec.get("title", "")
    fs_title = ctx.fit(title, bw - 2 * pad, 2, u * (0.05 if overlay else 0.075)) if title else 0
    head = fs_title * 2.6 if title else 0
    rh = min(u * (0.13 if overlay else 0.21), (bh - 2 * pad - head) / len(items))
    if not overlay:                                   # centre the list in its area instead of hugging the top
        by += max(0.0, (bh - head - rh * len(items)) / 2)
    badge = rh * 0.62
    longest = max((it.get("text", "") for it in items), key=len)
    fs = ctx.fit(longest, bw - 2 * pad - badge * 1.4, 2, min(u * 0.056, rh * 0.34))
    rows = []
    for k, it in enumerate(items):
        mark = (f'<div class="sb tile">{icon(it["icon"])}</div>' if it.get("icon") else f'<div class="sb num disp">{k + 1}</div>')
        rows.append(f'<div class="srow" id="r{k}" style="min-height:{rh:.0f}px">{mark}'
                    f'<div class="stx disp" style="font-size:{fs}px">{rich(it.get("text", ""))}</div></div>')
    html = (f'<div class="steps {"panel" if overlay else ""}" style="left:{bx:.0f}px;top:{by:.0f}px;width:{bw:.0f}px;'
            f'padding:{pad:.0f}px;--b:{badge:.0f}px">'
            + (f'<div class="stitle disp" style="font-size:{fs_title}px">{rich(title)}</div>' if title else "")
            + "".join(rows) + "</div>")
    css = """
.steps{position:absolute;box-sizing:border-box}
.stitle{text-align:center;line-height:1.12;margin-bottom:.55em}
.srow{display:flex;align-items:center;gap:calc(var(--b)*.4);opacity:0}
.sb{flex:0 0 var(--b);width:var(--b);height:var(--b);display:flex;align-items:center;justify-content:center}
.num{border-radius:50%;background:var(--accent);color:var(--on-accent);font-size:calc(var(--b)*.55);line-height:1;box-shadow:var(--glow)}
.stx{line-height:1.15}
"""
    js = []
    if title:
        js.append(f'tl.from(".stitle",{{opacity:0,y:{-u * 0.02:.0f},duration:0.45,ease:"power2.out"}},0.1);')
    checks = []
    for k, it in enumerate(items):
        a = ctx.t(it.get("at"), default=ctx.start + 0.4 + k * 0.6)
        js.append(f'tl.fromTo("#r{k}",{{opacity:0,x:{-u * 0.04:.0f}}},{{opacity:1,x:0,duration:0.4,ease:"{ctx.ease("back.out(1.6)")}"}},{a:.2f});')
        if k:
            js.append(f'tl.to("{",".join(f"#r{j}" for j in range(k))}",{{opacity:0.45,duration:0.3}},{a:.2f});')
        checks.append(min(a + 0.7, ctx.dur - 0.1))
    if overlay:
        js.append('tl.from(".steps",{opacity:0,scale:0.95,duration:0.35,ease:"power2.out"},0);')
    js.append(f'tl.to(".steps",{{opacity:0,duration:0.25}},{ctx.dur - 0.27:.2f});')
    return Scene(html=html, css=css, js=js, overlay=overlay, checks=checks)
