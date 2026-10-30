"""Two columns side by side: this vs that, the wrong way vs the right way. A full-screen cutaway.

{"template": "compare", "start": 40.0, "end": 50.0, "title": "Where should the refund go?",
 "left": {"title": "Credit card", "tone": "bad", "icon": "credit-card", "at": 40.3,
          "items": [{"text": "Charge gets reversed", "at": 41.5}, {"text": "You lose the points", "at": 43.0}]},
 "right": {"title": "Debit card", "tone": "good", "icon": "landmark", "at": 44.5,
           "items": [{"text": "Cash lands in your bank", "at": 45.5}, {"text": "You keep the points", "at": 47.0}]},
 "vs": "vs"}

tone: "good" (green ticks), "bad" (red crosses) or "neutral" (dots). A column's "at" defaults to just before its first item.
"""
from __future__ import annotations

from tpl import Scene, esc, icon, rich

MARK = {"good": "check", "bad": "x"}


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    cols = [spec.get("left") or {}, spec.get("right") or {}]
    if not all(c.get("title") for c in cols):
        raise ValueError("compare: give \"left\" and \"right\", each with a \"title\"")
    gap = W * (0.06 if ctx.vertical else 0.05)
    cw = (W * (0.9 if ctx.vertical else 0.7) - gap) / 2
    x0 = (W - 2 * cw - gap) / 2
    title = spec.get("title", "")
    area_top, area_bot = (H * 0.08, H * 0.74) if ctx.vertical else (H * 0.06, H * 0.94)   # keep the caption zone free
    fs_title = ctx.fit(title, W * 0.86, 2, u * 0.065) if title else 0
    title_h = fs_title * 2.8 if title else 0
    n_items = max(len(c.get("items") or []) for c in cols) or 1
    head_h = (u * 0.15 if any(c.get("icon") for c in cols) else 0) + u * 0.13
    rh = min(u * 0.17, (area_bot - area_top - title_h - head_h - u * 0.07) / n_items)
    y0 = area_top + max(0.0, (area_bot - area_top - title_h - head_h - u * 0.07 - rh * n_items) / 2)
    top = y0 + title_h
    texts = [it.get("text", "") for c in cols for it in (c.get("items") or [])] or ["x"]
    fs = ctx.fit(max(texts, key=len), cw - u * 0.13, 3, min(u * 0.05, rh * 0.3))
    html, js, checks = [], [], []
    if title:
        html.append(f'<div class="ctitle disp" style="left:{W * 0.07:.0f}px;top:{y0:.0f}px;width:{W * 0.86:.0f}px;'
                    f'font-size:{fs_title}px">{rich(title)}</div>')
        js.append(f'tl.from(".ctitle",{{opacity:0,y:{-u * 0.02:.0f},duration:0.45}},0.1);')
    for c, col in enumerate(cols):
        tone = col.get("tone", "neutral")
        items = col.get("items") or []
        first = ctx.t(items[0]["at"]) if items and items[0].get("at") is not None else 0.3 + c * 0.6
        a = ctx.t(col.get("at"), default=ctx.start + max(0.0, first - 0.5))
        x = x0 + c * (cw + gap)
        ic = f'<div class="tile chi">{icon(col["icon"])}</div>' if col.get("icon") else ""
        rows = []
        for k, it in enumerate(items):
            mark = icon(MARK[tone]) if tone in MARK else '<span class="bullet"></span>'
            rows.append(f'<div class="crow" id="c{c}i{k}" style="min-height:{rh * 0.8:.0f}px"><span class="cm {tone}">{mark}</span>'
                        f'<span class="ctx disp" style="font-size:{fs}px">{rich(it.get("text", ""))}</span></div>')
            ia = ctx.t(it.get("at"), default=ctx.start + a + 0.5 + k * 0.6)
            js.append(f'tl.fromTo("#c{c}i{k}",{{opacity:0,y:{u * 0.02:.0f}}},{{opacity:1,y:0,duration:0.35,ease:"{ctx.ease("back.out(1.6)")}"}},'
                      f'{ia:.2f});')
            checks.append(min(ia + 0.6, ctx.dur - 0.1))
        html.append(f'<div class="ccol panel" id="col{c}" style="left:{x:.0f}px;top:{top:.0f}px;width:{cw:.0f}px">'
                    f'<div class="chead">{ic}<div class="cht disp {tone}" style="font-size:'
                    f'{ctx.fit(col["title"], cw * 0.8, 1, u * 0.05)}px">{esc(col["title"])}</div></div>{"".join(rows)}</div>')
        js.insert(0, f'tl.fromTo("#col{c}",{{opacity:0,y:{u * 0.04:.0f}}},{{opacity:1,y:0,duration:0.45,ease:"{ctx.ease("back.out(1.4)")}"}},'
                     f'{a:.2f});')
    if spec.get("vs"):
        html.append(f'<div class="vs pill" style="left:{W / 2:.0f}px;top:{top + u * 0.1:.0f}px;font-size:{u * 0.035:.0f}px">'
                    f'{esc(spec["vs"])}</div>')
        js.append('tl.set(".vs",{xPercent:-50,yPercent:-50},0);')
        js.append(f'tl.from(".vs",{{scale:0,duration:0.3,ease:"{ctx.ease("back.out(2.4)")}"}},'
                  f'{ctx.t(cols[1].get("at"), default=ctx.start + 0.9):.2f});')
    js.append(f'tl.to(".ctitle,.ccol,.vs",{{opacity:0,duration:0.25}},{ctx.dur - 0.27:.2f});')
    css = """
.ctitle{position:absolute;text-align:center;line-height:1.12}
.ccol{position:absolute;box-sizing:border-box;padding:calc(var(--u)*.035) calc(var(--u)*.03);display:flex;flex-direction:column}
.chead{display:flex;flex-direction:column;align-items:center;gap:calc(var(--u)*.018);margin-bottom:calc(var(--u)*.025);
 padding-bottom:calc(var(--u)*.02);border-bottom:calc(var(--u)*.003) solid var(--line)}
.chi{width:calc(var(--u)*.13);height:calc(var(--u)*.13)}
.cht{line-height:1.1}
.crow{display:flex;align-items:center;gap:calc(var(--u)*.022);padding:calc(var(--u)*.012) 0}
.cm{flex:0 0 auto;width:calc(var(--u)*.055);height:calc(var(--u)*.055);display:inline-flex}
.cm .ic{width:100%;height:100%;stroke-width:3}
.bullet{width:40%;height:40%;margin:30%;border-radius:50%;background:var(--accent)}
.ctx{line-height:1.15}
.vs{position:absolute}
"""
    return Scene(html="".join(html), css=css, js=js, checks=checks or [ctx.dur * 0.6])
