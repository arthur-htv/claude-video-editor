"""A line worth remembering, big, revealed word by word. A full-screen cutaway, or a panel with "mode": "overlay".

{"template": "quote", "start": 36.0, "end": 40.5, "text": "Failure is *not the end*.", "author": "Franco Salvacion",
 "mode": "cutaway"}

*stars* mark the words to color. mode "overlay" puts it in a panel; position "top" or "bottom" (default).
"""
from __future__ import annotations

import re

from tpl import Scene, esc


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    text = spec["text"]
    overlay = spec.get("mode", "cutaway") == "overlay"
    if overlay:
        bw = W * (0.9 if ctx.vertical else 0.6)
        by = H * (0.06 if spec.get("position") == "top" else (0.6 if ctx.vertical else 0.55))
    else:
        bw, by = W * (0.84 if ctx.vertical else 0.66), H * (0.24 if ctx.vertical else 0.2)
    fs = ctx.fit(text, bw - u * 0.08, 4 if not overlay else 3, u * (0.085 if not overlay else 0.055))
    words, acc = [], False
    for tok in re.split(r"(\s+)", text.strip()):
        if not tok or tok.isspace():
            words.append(" ")
            continue
        start, end = tok.startswith("*"), tok.rstrip(".,!?;:").endswith("*")
        acc = acc or start
        words.append(f'<span class="qw{" acc" if acc else ""}">{esc(tok.replace("*", ""))}</span>')
        acc = acc and not end
    author = spec.get("author", "")
    html = (f'<div class="quote {"panel" if overlay else ""}" style="left:{(W - bw) / 2:.0f}px;top:{by:.0f}px;width:{bw:.0f}px">'
            f'<div class="qmark disp" style="font-size:{fs * 2.2:.0f}px">&ldquo;</div>'
            f'<div class="qt disp" style="font-size:{fs}px">{"".join(words)}</div>'
            + (f'<div class="qa" style="font-size:{max(u * 0.03, fs * 0.42):.0f}px">&mdash; {esc(author)}</div>' if author else "")
            + "</div>")
    css = """
.quote{position:absolute;box-sizing:border-box;text-align:center;padding:calc(var(--u)*.04)}
.qmark{color:var(--accent);line-height:.6;height:.42em}
.qt{line-height:1.15}
.qw{display:inline-block;opacity:0}
.qa{margin-top:.8em;color:var(--muted);font-family:var(--font-body)}
"""
    a = ctx.t(spec.get("at"))
    n = sum(1 for w in words if w != " ")
    each = min(0.12, 1.4 / max(1, n))
    js = [f'tl.from(".qmark",{{opacity:0,scale:0.6,duration:0.35,ease:"{ctx.ease("back.out(2)")}"}},{a:.2f});',
          f'tl.fromTo(".qw",{{opacity:0,y:{u * 0.02:.0f}}},{{opacity:1,y:0,duration:0.3,stagger:{each:.3f},ease:"power2.out"}},'
          f'{a + 0.15:.2f});']
    if author:
        js.append(f'tl.from(".qa",{{opacity:0,duration:0.4}},{a + 0.3 + each * n:.2f});')
    if overlay:
        js.insert(0, f'tl.from(".quote",{{opacity:0,scale:0.95,duration:0.3}},{a:.2f});')
    js.append(f'tl.to(".quote",{{opacity:0,duration:0.25}},{ctx.dur - 0.27:.2f});')
    return Scene(html=html, css=css, js=js, overlay=overlay, checks=[min(a + 0.6 + each * n, ctx.dur - 0.3)])
