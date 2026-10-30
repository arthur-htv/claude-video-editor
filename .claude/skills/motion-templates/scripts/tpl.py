"""Shared pieces for the motion templates: themes, icons, text fitting, timing and the page skeleton.

Every module in templates/ has build(spec, ctx) -> Scene. The Scene holds the template's HTML, CSS and
GSAP lines; page() wraps it into a HyperFrames composition with the theme's colors, fonts and background.
"""
from __future__ import annotations

import html as _html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL.parent / "video-editor" / "scripts"))
import hfbuild  # noqa: E402

THEMES = SKILL / "themes"
ICONS = SKILL / "assets" / "icons"


@dataclass
class Scene:
    html: str
    css: str = ""
    js: list[str] = field(default_factory=list)
    overlay: bool = False                                  # True: transparent WebM over the speaker
    checks: list[float] = field(default_factory=list)      # clip times worth a look in the check sheet


@dataclass
class Ctx:
    w: int
    h: int
    theme: dict
    start: float
    end: float

    @property
    def u(self) -> float:            # every size scales with the short side
        return float(min(self.w, self.h))

    @property
    def vertical(self) -> bool:
        return self.h > self.w

    @property
    def dur(self) -> float:
        return round(self.end - self.start, 3)

    def t(self, at, default: float | None = None) -> float:
        """A time on the video's timeline -> seconds into this clip (checked against the clip window)."""
        at = self.start if at is None and default is None else (default if at is None else at)
        r = float(at) - self.start
        if r < -0.01 or r > self.dur + 0.01:
            raise ValueError(f"time {at} is outside this template's window {self.start}-{self.end}")
        return round(min(max(0.0, r), self.dur), 3)

    def var(self, name: str) -> str:
        return self.theme["vars"][name]

    def ease(self, bounce: str) -> str:
        """A pop-in ease: the template's own back.out(...) bounce, or the theme's "pop" ease (apple: no bounce)."""
        return self.theme.get("pop", bounce)

    def fit(self, text, width: float, lines: int, max_px: float) -> float:
        """fit() with this theme's letter width: all-caps handwriting runs wider than mixed case."""
        return fit(text, width, lines, max_px, 0.7 if self.theme["vars"].get("case") == "uppercase" else 0.58)


def load_theme(name: str) -> dict:
    p = THEMES / f"{name}.json"
    if not p.is_file():
        have = ", ".join(sorted(x.stem for x in THEMES.glob("*.json")))
        raise ValueError(f"unknown theme {name!r} (have: {have})")
    return json.loads(p.read_text(encoding="utf-8"))


def icon(name: str) -> str:
    """A Lucide line icon, inline; its stroke follows the CSS color (currentColor)."""
    p = ICONS / f"{name}.svg"
    if not p.is_file():
        raise ValueError(f"unknown icon {name!r}: use a file name (without .svg) from {ICONS}")
    svg = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
    svg = re.sub(r'\sclass="[^"]*"', ' class="ic"', svg, count=1)
    return re.sub(r'\s(width|height)="24"', "", svg)


def esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def rich(s) -> str:
    """Escape text; words wrapped in *stars* get the accent color."""
    return re.sub(r"\*(.+?)\*", r'<span class="acc">\1</span>', esc(s))


def fit(text, width: float, lines: int, max_px: float, per_char: float = 0.58) -> float:
    """Font size (px) so the text fills at most `lines` lines of `width` px. per_char = average glyph width in em;
    0.85 leaves room for word wrapping."""
    n = max(1, len(re.sub(r"\*", "", str(text or ""))))
    return round(min(max_px, width * lines * 0.85 / (n * per_char)), 1)


BASE_CSS = """
.bg{position:absolute;inset:0;background-color:var(--bg)}
.grid{position:absolute;inset:0;background-image:
 linear-gradient(var(--grid-major) 1px,transparent 1px),linear-gradient(90deg,var(--grid-major) 1px,transparent 1px),
 linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
 background-size:calc(var(--u)*.2) calc(var(--u)*.2),calc(var(--u)*.2) calc(var(--u)*.2),
 calc(var(--u)*.04) calc(var(--u)*.04),calc(var(--u)*.04) calc(var(--u)*.04)}
.vig{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,transparent 50%,var(--vignette) 100%)}
.disp{font-family:var(--font-display);text-transform:var(--case);letter-spacing:var(--tracking);font-weight:var(--weight,400)}
.panel{background:var(--panel);border:calc(var(--u)*.004) solid var(--line);border-radius:var(--radius);box-shadow:var(--glow)}
.pill{display:inline-block;background:var(--accent);color:var(--on-accent);border-radius:calc(var(--u)*.012);
 padding:.22em .6em .18em;font-family:var(--font-display);text-transform:var(--case);white-space:nowrap;line-height:1.1}
.tile{background:var(--tile);color:var(--ink);border-radius:calc(var(--u)*.012);display:flex;align-items:center;justify-content:center}
.ic{width:62%;height:62%;stroke-width:1.5;overflow:visible}
.acc{color:var(--accent)}
.good{color:var(--good)}
.bad{color:var(--bad)}
"""

# A light wobble that makes line icons look hand-drawn (themes with "sketch": true).
SKETCH = ('<svg width="0" height="0" style="position:absolute"><filter id="sketch" x="-5%" y="-5%" width="110%" '
          'height="110%"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7"/>'
          '<feDisplacementMap in="SourceGraphic" scale="4"/></filter></svg>')


def page(ctx: Ctx, scene: Scene) -> str:
    th, dur = ctx.theme, ctx.dur
    css_vars = ";".join(f"--{k}:{v}" for k, v in th["vars"].items())
    backdrop = "" if scene.overlay else ('<div class="bg"></div>' + ('<div class="grid"></div>' if th.get("grid") else "")
                                         + ('<div class="vig"></div>' if th.get("vignette") else ""))
    sketch = th.get("sketch")
    return f"""<!doctype html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width={ctx.w}, height={ctx.h}">
{hfbuild.scripts_html()}
<style>{hfbuild.FONT_CSS}
:root{{{css_vars};--u:{ctx.u:.0f}px}}
html,body{{margin:0;width:{ctx.w}px;height:{ctx.h}px;overflow:hidden;background:{'transparent' if scene.overlay else 'var(--bg)'}}}
#root{{position:relative;width:{ctx.w}px;height:{ctx.h}px;font-family:var(--font-body);color:var(--text)}}
#stage{{position:absolute;inset:0}}
{BASE_CSS}{'.tile .ic{filter:url(#sketch)}' if sketch else ''}
{scene.css}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{ctx.w}" data-height="{ctx.h}">
  <div id="stage" class="clip" data-start="0" data-duration="{dur}" data-track-index="0">
    {SKETCH if sketch else ''}{backdrop}
    {scene.html}
  </div>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(scene.js)}
tl.to({{}}, {{ duration: {dur} }}, 0);
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
"""
