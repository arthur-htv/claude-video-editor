"""Flowchart explainer: a diagram that builds itself while the speaker explains, the camera gliding to each new
box, then a zoom-out recap of the whole map. A full-screen cutaway; the bottom fifth stays clear for captions.

{"template": "flowchart", "start": 9.6, "end": 85.0, "title": "Turning credit into cash",
 "nodes": [
  {"id": "approved", "icon": "credit-card", "text": "Approved", "sub": "$50,000 limit", "at": 10.6},
  {"id": "split", "after": "approved", "branch": "Option 1", "icon": "shopping-cart",
   "text": "Split the payment at checkout", "sub": "Best Buy · Micro Center", "at": 17.2, "sticker": "$2,500"},
  {"id": "refund", "after": "split", "text": "Refund goes to", "choice": ["Debit", "Credit"], "pick": 0,
   "pick_at": 42.0, "sub": "You keep the points", "at": 40.1},
  {"id": "bfm", "after": "approved", "branch": "Option 2", "icon": "globe", "text": "Sign up on *Buy For Me*", "at": 55.0}],
 "recap": true}
"""
from __future__ import annotations

from hfbuild import js as J
from tpl import Scene, esc, icon, rich


def layout(nodes: list[dict]) -> dict[str, tuple[float, int]]:
    """(column, row) for every node: children stack under their parent, branches spread into columns,
    and a parent sits centred over its children."""
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids):
        raise ValueError("flowchart node ids must be unique")
    kids: dict[str, list[str]] = {i: [] for i in ids}
    roots = []
    for n in nodes:
        a = n.get("after")
        if a is None:
            roots.append(n["id"])
        elif a not in kids:
            raise ValueError(f"node {n['id']!r}: after={a!r} is not a node id")
        else:
            kids[a].append(n["id"])
    pos: dict[str, tuple[float, int]] = {}
    slot = [0]

    def place(i: str, depth: int) -> None:
        if not kids[i]:
            pos[i] = (float(slot[0]), depth)
            slot[0] += 1
            return
        for c in kids[i]:
            place(c, depth + 1)
        pos[i] = ((pos[kids[i][0]][0] + pos[kids[i][-1]][0]) / 2, depth)

    for r in roots:
        place(r, 0)
    if len(pos) != len(ids):
        raise ValueError("some flowchart nodes point at each other in a loop")
    return pos


def build(spec: dict, ctx) -> Scene:
    u, W, H = ctx.u, ctx.w, ctx.h
    nodes = spec.get("nodes") or []
    if not nodes:
        raise ValueError("a flowchart needs at least one node")
    pos = layout(nodes)
    nw, tile, pad = u * 0.62, u * 0.19, u * 0.035
    fs_t, fs_s = u * 0.042, u * 0.031
    nh = pad + tile + u * 0.03 + 2 * 1.18 * fs_t + 1.3 * fs_s + pad          # one height for every box
    col, row = nw * 1.16, nh + u * 0.17
    title = spec.get("title")
    top = u * 0.2 if title else 0.0
    box = {n["id"]: (pos[n["id"]][0] * col, top + pos[n["id"]][1] * row) for n in nodes}
    maxx = max(x for x, _ in box.values()) + nw
    maxy = max(y for _, y in box.values()) + nh
    at = {n["id"]: ctx.t(n["at"]) for n in nodes}
    order = sorted(nodes, key=lambda n: at[n["id"]])
    idx = {n["id"]: k for k, n in enumerate(nodes)}
    accent = ctx.var("accent")

    s_focus = min((0.72 * W if ctx.vertical else 0.40 * W) / nw, 0.46 * H / nh)

    def cam(cx: float, cy: float, s: float, ty: float = 0.43) -> dict:
        return {"x": round(W / 2 - s * cx, 1), "y": round(H * ty - s * cy, 1), "scale": round(s, 4)}

    def focus(i: str) -> dict:
        x, y = box[i]
        return cam(x + nw / 2, y + nh / 2, s_focus)

    def nudge(a: dict, b: dict, t0: float, d: float) -> list[str]:
        """Slow-fast-slow camera glide (cut-the-curve nudge curve): 10% / 75% / 100% of the way at 20% / 38% / 100% of the time."""
        def mid(f: float) -> str:
            return J({k: round(a[k] + (b[k] - a[k]) * f, 4) for k in b})
        return [f'tl.to("#world",{{...{mid(0.10)},duration:{d * 0.20:.3f},ease:"power3.in"}},{t0:.3f});',
                f'tl.to("#world",{{...{mid(0.75)},duration:{d * 0.18:.3f},ease:"none"}},{t0 + d * 0.20:.3f});',
                f'tl.to("#world",{{...{J(b)},duration:{d * 0.62:.3f},ease:"power4.out"}},{t0 + d * 0.38:.3f});']

    html = [f'<div id="world" style="width:{maxx:.0f}px;height:{maxy:.0f}px">']
    if title:
        roots = [box[n["id"]][0] + nw / 2 for n in nodes if n.get("after") is None]
        cx, tw = sum(roots) / len(roots), nw * 1.5
        html.append(f'<div class="ftitle disp" style="left:{cx - tw / 2:.0f}px;top:{u * 0.02:.0f}px;width:{tw:.0f}px;'
                    f'font-size:{ctx.fit(title, tw, 1, u * 0.05)}px">{rich(title)}</div>')
    edges = []
    for n in nodes:
        if n.get("after"):
            k = idx[n["id"]]
            px, py = box[n["after"]]
            cx_, cy_ = box[n["id"]]
            x1, y1 = px + nw / 2, py + nh
            x2, y2 = cx_ + nw / 2, cy_ - (u * 0.026 if n.get("branch") else u * 0.004)
            d = (f"M{x1:.1f},{y1:.1f} V{y2:.1f}" if abs(x1 - x2) < 1 else
                 f"M{x1:.1f},{y1:.1f} V{y1 + (y2 - y1) * 0.42:.1f} H{x2:.1f} V{y2:.1f}")
            edges.append(f'<path id="e{k}" class="edge" d="{d}"/>')
            if not n.get("branch"):
                a = u * 0.016
                edges.append(f'<path id="a{k}" class="edge" d="M{x2 - a:.1f},{y2 - a:.1f} L{x2:.1f},{y2:.1f} '
                             f'L{x2 + a:.1f},{y2 - a:.1f}"/>')
    html.append(f'<svg class="edges" width="{maxx:.0f}" height="{maxy:.0f}">{"".join(edges)}</svg>')

    for k, n in enumerate(nodes):
        x, y = box[n["id"]]
        inner = []
        if n.get("branch"):
            inner.append(f'<div class="pill branch" style="font-size:{u * 0.028:.0f}px">{esc(n["branch"])}</div>')
        if n.get("choice"):
            opts = [str(o) for o in n["choice"]]
            gap = u * 0.03
            ow = (nw - 2 * pad - gap * (len(opts) - 1)) / len(opts)
            cells = []
            for j, o in enumerate(opts):
                tick = (f'<svg class="tick" viewBox="0 0 24 24"><path id="t{k}" d="M4 12.5l5 5L20 6"/></svg>'
                        if j == n.get("pick") else "")
                cells.append(f'<div class="opt" id="o{k}_{j}" style="width:{ow:.0f}px;height:{tile * 0.66:.0f}px">'
                             f'<div class="cb">{tick}</div><div class="ol disp" style="font-size:'
                             f'{ctx.fit(o, ow * 0.9, 1, u * 0.03)}px">{esc(o)}</div></div>')
            inner.append(f'<div class="choices" style="height:{tile:.0f}px">{"".join(cells)}</div>')
        elif n.get("icon"):
            inner.append(f'<div class="tile" style="width:{tile:.0f}px;height:{tile:.0f}px">{icon(n["icon"])}</div>')
        inner.append(f'<div class="nt disp" style="font-size:{ctx.fit(n.get("text", ""), nw - 2 * pad, 2, fs_t)}px">'
                     f'{rich(n.get("text", ""))}</div>')
        if n.get("sub"):
            inner.append(f'<div class="ns" style="font-size:{ctx.fit(n["sub"], nw - 2 * pad, 1, fs_s)}px">'
                         f'{rich(n["sub"])}</div>')
        if n.get("sticker"):
            inner.append(f'<div class="pill sticker" id="s{k}" style="font-size:{u * 0.032:.0f}px">'
                         f'{esc(n["sticker"])}</div>')
        html.append(f'<div class="node panel" id="n{k}" style="left:{x:.0f}px;top:{y:.0f}px;width:{nw:.0f}px;'
                    f'height:{nh:.0f}px">{"".join(inner)}</div>')
    html.append("</div>")

    css = """
#world{position:absolute;left:0;top:0;transform-origin:0 0}
.edges{position:absolute;left:0;top:0;overflow:visible}
.edge{fill:none;stroke:var(--line);stroke-width:calc(var(--u)*.0045);stroke-linecap:round;stroke-linejoin:round;filter:var(--edge-filter)}
.node{position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;
 gap:calc(var(--u)*.02);padding:0 calc(var(--u)*.035);text-align:center;opacity:0}
.nt{line-height:1.12}
.ns{color:var(--accent);line-height:1.1;font-family:var(--font-display);text-transform:var(--case)}
.branch{position:absolute;left:50%;top:0;transform:translate(-50%,-50%)}
.sticker{position:absolute;right:calc(var(--u)*-.03);top:calc(var(--u)*-.035)}
.choices{display:flex;gap:calc(var(--u)*.03);align-items:center;justify-content:center}
.opt{box-sizing:border-box;border:calc(var(--u)*.004) solid var(--line);border-radius:calc(var(--u)*.012);background:var(--tile);
 display:flex;flex-direction:column;align-items:center;justify-content:center;gap:calc(var(--u)*.014)}
.cb{width:calc(var(--u)*.055);height:calc(var(--u)*.055);border:calc(var(--u)*.004) solid var(--text);border-radius:calc(var(--u)*.008);position:relative}
.tick{position:absolute;left:-20%;top:-35%;width:150%;height:150%;overflow:visible}
.tick path{fill:none;stroke:var(--accent);stroke-width:3.4;stroke-linecap:round;stroke-linejoin:round}
.ftitle{position:absolute;text-align:center;line-height:1.1;padding-bottom:.25em;border-bottom:calc(var(--u)*.003) solid var(--line)}
"""
    js = [f'tl.set("#world",{J({**focus(order[0]["id"]), "transformOrigin": "0 0"})},0);']
    if title:
        js.append(f'tl.from(".ftitle",{{opacity:0,y:{-u * 0.02:.0f},duration:0.5,ease:"power2.out"}},0.1);')
    checks, prev_end, seen = [], 0.0, order[0]["id"]
    for n in order:
        i, k, a = n["id"], idx[n["id"]], at[n["id"]]
        if n is not order[0]:                     # glide to the new box without overlapping camera moves
            ms = max(a - 0.45, prev_end)
            md = max(0.3, min(0.8, a + 0.35 - ms))
            js += nudge(focus(seen), focus(i), ms, md)
            prev_end, seen = ms + md, i
        if n.get("after"):
            js.append(f'tl.fromTo("#e{k}",{{drawSVG:"0%"}},{{drawSVG:"100%",duration:0.35,ease:"power1.inOut"}},'
                      f'{max(0.0, a - 0.3):.2f});')
            if not n.get("branch"):
                js.append(f'tl.fromTo("#a{k}",{{opacity:0}},{{opacity:1,duration:0.25}},{a:.2f});')
        js.append(f'tl.fromTo("#n{k}",{{opacity:0,scale:0.92,y:{u * 0.02:.0f}}},{{opacity:1,scale:1,y:0,duration:0.45,'
                  f'ease:"{ctx.ease("back.out(1.6)")}"}},{a:.2f});')
        if n.get("sticker"):
            js.append(f'tl.set("#s{k}",{{rotation:-8}},0);')
            js.append(f'tl.fromTo("#s{k}",{{scale:0}},{{scale:1,duration:0.35,ease:"{ctx.ease("back.out(2.4)")}"}},'
                      f'{min(ctx.dur, a + 0.6):.2f});')
        if n.get("choice") and n.get("pick") is not None:
            p = ctx.t(n.get("pick_at"), default=ctx.start + min(ctx.dur, a + 1.2))
            js.append(f'tl.fromTo("#t{k}",{{drawSVG:"0%"}},{{drawSVG:"100%",duration:0.35,ease:"power2.out"}},{p:.2f});')
            js.append(f'tl.to("#o{k}_{int(n["pick"])}",{{borderColor:"{accent}",duration:0.25}},{p:.2f});')
        checks.append(min(ctx.dur - 0.4, a + 0.8))

    # Recap: the last box stays in focus READ s, the zoom-out takes ZOOM s, the whole map holds HOLD s before the fade.
    READ, ZOOM, HOLD, FADE = 1.2, 1.1, 0.8, 0.27
    recap = spec.get("recap", True)
    if recap:
        latest = ctx.dur - FADE - HOLD - ZOOM
        if recap is True:
            r = max(max(at.values()) + READ, ctx.dur - 3.0, prev_end)
        else:
            r = max(ctx.t(recap), prev_end)
            if r > latest:
                raise ValueError(f"flowchart: the recap needs {ZOOM + HOLD + FADE:.1f} s before the end; "
                                 f"set it by {ctx.start + latest:.2f} or move \"end\" later")
        if r <= latest:
            s = min(0.9 * W / maxx, 0.62 * H / maxy, s_focus)
            js.append(f'tl.to("#world",{{...{J(cam(maxx / 2, maxy / 2, s, 0.40))},duration:{ZOOM},ease:"power3.inOut"}},'
                      f'{r:.2f});')
            checks.append(min(ctx.dur - FADE - 0.1, r + ZOOM + 0.3))
    js.append(f'tl.to("#world",{{opacity:0,duration:0.25}},{ctx.dur - 0.27:.2f});')
    step = max(1, len(checks) // 8)
    picks = checks[::step][:8]
    return Scene(html="".join(html), css=css, js=js, checks=picks + [c for c in checks[-1:] if c not in picks])
