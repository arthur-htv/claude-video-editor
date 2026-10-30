"""A card Claude designs for one moment (the talking-head-recut skill): an HTML fragment with its own
<style> and a <script> of GSAP lines on `tl`, timed in seconds from the card's start. Over the speaker
("mode": "overlay", default) or full screen ("mode": "cutaway").

{"template": "card", "start": 12.0, "end": 16.0, "mode": "overlay",
 "html": "<div class=\\"lt panel\\"><div class=\\"k\\">Viewers who stay</div><div class=\\"n disp\\">87%</div></div><style>.lt{position:absolute;left:7%;right:7%;bottom:27%;padding:calc(var(--u)*.05)}.k{color:var(--muted);font-size:calc(var(--u)*.036)}.n{color:var(--accent);font-size:calc(var(--u)*.17);line-height:1}</style><script>tl.fromTo('.lt',{opacity:0,y:40},{opacity:1,y:0,duration:0.6,ease:'expo.out'},0.2);</script>"}

"file" (a path from the project folder, such as work/cards/c01.html) replaces "html". "checks" lists video
times for the check frames. A 0.35 s fade-out at the end is added for you. Write [[icon:name]] for a
bundled line icon (assets/icons/name.svg); it takes the text colour and sizes with the text (1em).
"""
from __future__ import annotations

import re
from pathlib import Path

from tpl import Scene, icon
from vtools import project_root

ICON = re.compile(r"\[\[icon:([\w-]+)\]\]")
STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
WEB = re.compile(r"""(src|href)\s*=\s*["']?\s*(https?:)?//|url\(\s*["']?\s*(https?:)?//|@import""", re.I)


def build(spec: dict, ctx) -> Scene:
    if spec.get("file"):
        path = Path(spec["file"])
        frag = (path if path.is_absolute() else project_root() / path).read_text(encoding="utf-8")
    elif spec.get("html"):
        frag = spec["html"]
    else:
        raise ValueError('card: give "file" (an HTML fragment) or "html"')
    if WEB.search(frag):
        raise ValueError("card: keep it self-contained, with no web links (fonts and icons come bundled)")
    css = "#card .ic{width:1em;height:1em;vertical-align:-0.12em}\n" + "\n".join(STYLE.findall(frag))
    js = [s.strip() for s in SCRIPT.findall(frag) if s.strip()]
    html = ICON.sub(lambda m: icon(m.group(1)), SCRIPT.sub("", STYLE.sub("", frag))).strip()
    if not html:
        raise ValueError("card: the fragment has no visible HTML")
    js.append(f'tl.to("#card",{{opacity:0,duration:0.35,ease:"power2.in"}},{max(0.0, ctx.dur - 0.37):.2f});')
    checks = [ctx.t(t) for t in spec.get("checks") or []] or [min(1.0, ctx.dur * 0.3), ctx.dur * 0.6]
    return Scene(html=f'<div id="card">{html}</div>', css=css, js=js,
                 overlay=spec.get("mode", "overlay") != "cutaway", checks=checks)
