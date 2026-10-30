"""Lower third: a person's name and role (or a product and what it is) beside the speaker. An overlay.
Looks and motion adapted from HeyGen HyperFrames' lt-clean-bar, lt-accent-underline, lt-kicker-name and
lt-side-rule (Apache-2.0, see assets/registry/NOTICE.md), in the theme's colours and fonts.

{"template": "lower-third", "start": 3.0, "end": 7.5, "name": "Franco *Salvacion*", "title": "Founder, HighThrive",
 "style": "clean-bar"}

style: "clean-bar" (default: a panel with an accent tab, reads on any footage), "accent-underline" (no panel, an accent
rule draws under the name), "kicker-name" (an accent tag above the name; give "kicker"), "side-rule" (a vertical accent
bar). title = the role line under the name. at = when it starts (default: start). position: "bottom" (default, its bottom
edge just above the captions), "top", or the bottom edge as a fraction of the height.
"""
from __future__ import annotations

from tpl import Scene, esc, rich

STYLES = ("clean-bar", "accent-underline", "kicker-name", "side-rule")


def build(spec: dict, ctx) -> Scene:
    u, W, H, V = ctx.u, ctx.w, ctx.h, ctx.vertical
    style = spec.get("style", "clean-bar")
    if style not in STYLES:
        raise ValueError(f"lower-third: unknown style {style!r} (have: {', '.join(STYLES)})")
    if not spec.get("name"):
        raise ValueError('lower-third: give a "name"')
    if style == "kicker-name" and not spec.get("kicker"):
        raise ValueError('lower-third: the kicker-name style needs a "kicker" (a short tag such as "Episode 4")')
    name, role, kick = spec["name"], spec.get("title", ""), spec.get("kicker", "")
    a = ctx.t(spec.get("at"))
    k = min(1.0, (ctx.dur - a) / 2.4)               # short windows compress the motion instead of cutting it off
    E = ctx.dur - 0.55 * k                           # the exit starts here

    maxw = W * (0.86 if V else 0.6) - (u * 0.09 if style == "clean-bar" else u * 0.035 if style == "side-rule" else 0)
    fs_name = ctx.fit(name, maxw, 1, u * (0.08 if V else 0.066))
    fs_role = min(ctx.fit(role, maxw, 1, u * (0.036 if V else 0.028)), fs_name * 0.62) if role else 0
    name_d = f'<div class="lt-name disp" style="font-size:{fs_name}px">{rich(name)}</div>'
    role_d = f'<div class="lt-role" style="font-size:{fs_role}px">{rich(role)}</div>' if role else ""

    pos = spec.get("position", "bottom")
    if pos == "top":
        place = f"top:{H * 0.06:.0f}px"
    else:
        place = f"bottom:{H * (1 - float({'bottom': 0.70 if V else 0.78}.get(pos, pos))):.0f}px"
    place += f";left:{W * 0.07:.0f}px"

    ein = '"power3.out"'
    js = []
    if style == "clean-bar":
        body = f'<div class="ltb-card"><div class="ltb-tab"></div><div class="ltb-body">{name_d}{role_d}</div></div>'
        js += [f'tl.fromTo("#lt",{{clipPath:"inset(-40% 100% -40% -10%)"}},{{clipPath:"inset(-40% -10% -40% -10%)",'
               f'duration:{0.55 * k:.2f},ease:{ein}}},{a + 0.1 * k:.2f});',
               f'tl.fromTo(".ltb-tab",{{scaleY:0}},{{scaleY:1,duration:{0.45 * k:.2f},ease:"power2.out"}},{a + 0.28 * k:.2f});']
        rise = [(".lt-name", 0.34, ein), (".lt-role", 0.44, ein)]
        exit_ = [f'tl.to("#lt",{{y:{u * 0.017:.0f},opacity:0,duration:{0.35 * k:.2f},ease:"power2.in"}},{E:.2f});']
    elif style == "side-rule":
        body = f'<div class="lts-bar"></div><div class="lts-text">{name_d}{role_d}</div>'
        js.append(f'tl.fromTo(".lts-bar",{{scaleY:0}},{{scaleY:1,duration:{0.5 * k:.2f},ease:{ein}}},{a + 0.1 * k:.2f});')
        js += [f'tl.fromTo("{s}",{{x:{-u * 0.022:.0f},opacity:0}},{{x:0,opacity:1,duration:{0.5 * k:.2f},ease:{ein}}},'
               f'{a + t * k:.2f});' for s, t in ((".lt-name", 0.26), (".lt-role", 0.38))]
        rise = []
        exit_ = [f'tl.to(".lt-role",{{opacity:0,duration:{0.3 * k:.2f},ease:"power2.in"}},{E:.2f});',
                 f'tl.to(".lt-name",{{y:{-u * 0.013:.0f},opacity:0,duration:{0.32 * k:.2f},ease:"power2.in"}},{E + 0.05 * k:.2f});',
                 f'tl.to(".lts-bar",{{scaleY:0,duration:{0.32 * k:.2f},ease:"power2.in"}},{E + 0.07 * k:.2f});']
    else:                                            # accent-underline and kicker-name: no panel, a rule under the name
        kd = (f'<div class="ltk-wrap"><span class="ltk" style="font-size:{u * (0.03 if V else 0.022):.0f}px">{esc(kick)}</span>'
              f'</div>') if style == "kicker-name" else ""
        body = f'{kd}{name_d}<div class="ltu-rule"></div>{role_d}'
        t0 = 0.0
        if kd:
            js.append(f'tl.fromTo(".ltk",{{yPercent:-110}},{{yPercent:0,duration:{0.42 * k:.2f},ease:"{ctx.ease("back.out(2)")}"}},'
                      f'{a + 0.1 * k:.2f});')
            t0 = 0.22
        js.append(f'tl.fromTo(".ltu-rule",{{scaleX:0}},{{scaleX:1,duration:{0.5 * k:.2f},ease:"power4.out"}},{a + (0.3 + t0) * k:.2f});')
        rise = [(".lt-name", 0.1 + t0, f'"{ctx.ease("back.out(1.5)")}"' if kd else ein), (".lt-role", 0.46 + t0, ein)]
        exit_ = [f'tl.to(".lt-role",{{opacity:0,duration:{0.3 * k:.2f},ease:"power2.in"}},{E:.2f});',
                 f'tl.to(".ltu-rule",{{scaleX:0,duration:{0.3 * k:.2f},ease:"power2.in"}},{E + 0.05 * k:.2f});',
                 f'tl.to(".lt-name",{{y:{-u * 0.015:.0f},opacity:0,duration:{0.32 * k:.2f},ease:"power2.in"}},{E + 0.1 * k:.2f});']
        if kd:
            exit_.append(f'tl.to(".ltk",{{yPercent:-110,duration:{0.3 * k:.2f},ease:"power2.in"}},{E + 0.07 * k:.2f});')
    js += [f'tl.fromTo("{s}",{{y:{u * 0.024:.0f},opacity:0}},{{y:0,opacity:1,duration:{0.5 * k:.2f},ease:{e}}},'
           f'{a + t * k:.2f});' for s, t, e in rise if s == ".lt-name" or role]
    js += exit_

    css = """
.lt{position:absolute;display:flex;flex-direction:column;align-items:flex-start;gap:calc(var(--u)*.013)}
.lt-name{line-height:1.02;white-space:nowrap}
.lt-role{font-family:var(--font-body);line-height:1.2;white-space:nowrap;letter-spacing:.02em}
.lt-bare .lt-role{font-weight:600}
.lt-bare .lt-name,.lt-bare .lt-role{color:#fff;text-shadow:0 0 .05em rgba(0,0,0,.9),0 0 .12em rgba(0,0,0,.75),0 .05em .2em rgba(0,0,0,.6),0 0 .02em rgba(0,0,0,.95)}   /* kinetic-text's halo: reads on white clothing */
.ltu-rule{align-self:stretch;height:calc(var(--u)*.0056);background:var(--accent);border-radius:calc(var(--u)*.003);transform-origin:0 50%;
 box-shadow:0 0 calc(var(--u)*.012) rgba(0,0,0,.35)}
.ltk-wrap{overflow:hidden;padding-bottom:calc(var(--u)*.004)}
.ltk{display:inline-block;background:var(--accent);color:var(--on-accent);font-family:var(--font-body);font-weight:700;
 letter-spacing:.1em;text-transform:uppercase;padding:.3em .65em .26em;white-space:nowrap;border-radius:calc(var(--u)*.004)}
.ltb-card{display:flex;align-items:stretch;background:var(--panel);border:calc(var(--u)*.002) solid var(--line);
 border-radius:min(var(--radius),calc(var(--u)*.024));overflow:hidden;box-shadow:var(--glow),var(--shadow)}
.ltb-tab{width:calc(var(--u)*.011);flex-shrink:0;background:var(--accent);transform-origin:50% 0}
.ltb-body{display:flex;flex-direction:column;gap:calc(var(--u)*.008);padding:calc(var(--u)*.022) calc(var(--u)*.04) calc(var(--u)*.024) calc(var(--u)*.03)}
.ltb-body .lt-name{color:var(--text)}
.ltb-body .lt-role{color:var(--muted)}
.lt-side{flex-direction:row;align-items:stretch;gap:calc(var(--u)*.024)}
.lts-bar{width:calc(var(--u)*.0075);flex-shrink:0;background:var(--accent);border-radius:calc(var(--u)*.004);transform-origin:50% 0;
 box-shadow:0 0 calc(var(--u)*.012) rgba(0,0,0,.35)}
.lts-text{display:flex;flex-direction:column;justify-content:center;gap:calc(var(--u)*.011)}
"""
    cls = {"clean-bar": "lt", "side-rule": "lt lt-side lt-bare"}.get(style, "lt lt-bare")
    html = f'<div id="lt" class="{cls}" style="{place}">{body}</div>'
    return Scene(html=html, css=css, js=js, overlay=True, checks=[a + 0.4 * k, min(a + 1.3 * k, E - 0.05)])
