"""Title card: a calm, typographic title for an intro, a topic or a reveal. Full screen on the theme's background
("mode": "cutaway", default), or over the speaker with the footage dimmed behind it ("mode": "overlay").
Looks and motion adapted from HeyGen HyperFrames' titlecard-calm and titlecard-lockup (Apache-2.0, see
assets/registry/NOTICE.md), in the theme's colours and fonts.

{"template": "title-card", "start": 0.0, "end": 3.5, "title": "Business credit, *explained*", "kicker": "Part 1",
 "sub": "No personal guarantee", "style": "calm"}

style: "calm" (default: a small kicker over a big left-aligned headline that drifts upward) or "lockup" (centred: kicker,
headline, a hairline rule drawing left to right, a small label under it). sub = the line under the headline (the label
in lockup). at = when it starts (default: start). position: "center" (default) or the card's centre as a fraction of the
height.
"""
from __future__ import annotations

from tpl import Scene, esc, rich

STYLES = ("calm", "lockup")


def build(spec: dict, ctx) -> Scene:
    u, W, H, V = ctx.u, ctx.w, ctx.h, ctx.vertical
    style = spec.get("style", "calm")
    if style not in STYLES:
        raise ValueError(f"title-card: unknown style {style!r} (have: {', '.join(STYLES)})")
    if not spec.get("title"):
        raise ValueError('title-card: give a "title"')
    overlay = spec.get("mode", "cutaway") == "overlay"
    title, kick, sub = spec["title"], spec.get("kicker", ""), spec.get("sub", "")
    a = ctx.t(spec.get("at"))
    pos = spec.get("position", "center")
    y = H * float(0.46 if pos == "center" else pos)

    lock = style == "lockup"
    k = min(1.0, (ctx.dur - a) / (2.3 if lock else 1.75))   # short windows compress the motion instead of cutting it off
    out = (0.5 if lock else 0.55) * k
    bw = W * (0.84 if V or lock else 0.72)
    fs = ctx.fit(title, bw, 2 if lock else 3, u * ((0.13 if lock else 0.15) if V else (0.19 if lock else 0.16)))
    parts = []
    if kick:
        parts.append(f'<div class="tc-kick" style="font-size:{u * (0.028 if lock else 0.032):.0f}px">{esc(kick)}</div>')
    parts.append(f'<div class="tc-head disp" style="font-size:{fs}px">{rich(title)}</div>')
    if lock:
        parts.append('<div class="tc-rule"></div>')
    if sub:
        parts.append(f'<div class="tc-sub" style="font-size:{u * ((0.03 if V else 0.024) if lock else (0.04 if V else 0.032)):.0f}px">'
                     f'{rich(sub)}</div>')
    html = (('<div class="tc-scrim"></div>' if overlay else "")
            + f'<div class="tc {"tc-lock" if lock else "tc-calm"}" style="left:{(W - bw) / 2:.0f}px;top:{y:.0f}px;width:{bw:.0f}px">'
            + "".join(parts) + "</div>")

    js = ['tl.set(".tc",{yPercent:-50},0);']
    if overlay:
        js += [f'tl.fromTo(".tc-scrim",{{opacity:0}},{{opacity:0.78,duration:0.4,ease:"power2.out"}},{max(0.0, a - 0.1):.2f});',
               f'tl.to(".tc-scrim",{{opacity:0,duration:0.4,ease:"power2.in"}},{ctx.dur - 0.42:.2f});']
    if lock:
        if kick:
            js.append(f'tl.fromTo(".tc-kick",{{opacity:0,y:{u * 0.022:.0f}}},{{opacity:1,y:0,duration:{0.45 * k:.2f},'
                      f'ease:"power2.out"}},{a:.2f});')
        js += [f'tl.fromTo(".tc-head",{{opacity:0,scale:0.96}},{{opacity:1,scale:1,duration:{0.85 * k:.2f},ease:"power3.out"}},'
               f'{a + 0.25 * k:.2f});',
               f'tl.fromTo(".tc-rule",{{scaleX:0}},{{scaleX:1,duration:{0.55 * k:.2f},ease:"power2.out"}},{a + 0.9 * k:.2f});']
        if sub:
            js.append(f'tl.fromTo(".tc-sub",{{opacity:0,y:{u * 0.018:.0f}}},{{opacity:1,y:0,duration:{0.5 * k:.2f},'
                      f'ease:"power2.out"}},{a + 1.3 * k:.2f});')
        js.append(f'tl.to(".tc",{{opacity:0,duration:{out:.2f},ease:"power2.in"}},{ctx.dur - out:.2f});')
        settled = a + 1.8 * k
    else:
        if kick:
            js.append(f'tl.fromTo(".tc-kick",{{opacity:0,y:{u * 0.022:.0f}}},{{opacity:1,y:0,duration:{0.5 * k:.2f},'
                      f'ease:"power2.out"}},{a:.2f});')
        js.append(f'tl.fromTo(".tc-head",{{opacity:0,y:{u * 0.032:.0f}}},{{opacity:1,y:0,duration:{0.72 * k:.2f},'
                  f'ease:"power3.out"}},{a + 0.28 * k:.2f});')
        if sub:
            js.append(f'tl.fromTo(".tc-sub",{{opacity:0,y:{u * 0.02:.0f}}},{{opacity:1,y:0,duration:{0.6 * k:.2f},'
                      f'ease:"power2.out"}},{a + 0.5 * k:.2f});')
        hold = ctx.dur - out - (a + 1.2 * k)
        if hold > 0:                                       # the lockup drifts barely upward while it holds
            js.append(f'tl.to(".tc",{{y:{-u * 0.0065:.1f},duration:{hold:.2f},ease:"sine.inOut"}},{a + 1.2 * k:.2f});')
        js.append(f'tl.to(".tc",{{opacity:0,y:{-u * 0.021:.0f},duration:{out:.2f},ease:"power2.in"}},{ctx.dur - out:.2f});')
        settled = a + 1.2 * k
    css = """
.tc-scrim{position:absolute;inset:0;background:var(--bg)}
.tc{position:absolute;display:flex;flex-direction:column}
.tc-calm{align-items:flex-start;gap:calc(var(--u)*.04)}
.tc-lock{align-items:center;text-align:center}
.tc-kick{font-family:var(--font-body);font-weight:600;line-height:1;text-transform:uppercase;letter-spacing:.18em;color:var(--muted)}
.tc-head{color:var(--text);line-height:1.02;text-wrap:balance}
.tc-calm .tc-head{line-height:.98}
.tc-sub{font-family:var(--font-body);line-height:1.3;color:var(--muted);text-wrap:balance}
.tc-lock .tc-kick{letter-spacing:.3em;text-indent:.3em;margin-bottom:calc(var(--u)*.034);
 color:color-mix(in srgb,var(--text) 62%,var(--bg))}
.tc-rule{width:min(100%,calc(var(--u)*.62));height:max(2px,calc(var(--u)*.003));margin-top:calc(var(--u)*.04);transform-origin:0 50%;
 background:color-mix(in srgb,var(--accent) 60%,var(--text));opacity:.75}
.tc-lock .tc-sub{margin-top:calc(var(--u)*.032);font-weight:600;text-transform:uppercase;letter-spacing:.3em;text-indent:.3em;
 color:color-mix(in srgb,var(--text) 62%,var(--bg))}
"""
    return Scene(html=html, css=css, js=js, overlay=overlay,
                 checks=[a + 0.45 * k, min(settled + 0.2, ctx.dur - out - 0.05)])
