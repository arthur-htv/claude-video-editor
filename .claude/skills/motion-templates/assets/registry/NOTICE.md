# HyperFrames registry items adapted here

Three templates in `scripts/templates/` take their look and motion from items in HeyGen's HyperFrames registry
(github.com/heygen-com/hyperframes, commit `359b6c8a38`, `registry/`). The items are Apache-2.0, Copyright HeyGen;
the license is in `LICENSE-hyperframes.txt` next to this file. No registry file is copied verbatim; nothing
third-party (fonts, Three.js, other libraries) was taken from them.

| Template | Registry items | What was kept | What changed |
|---|---|---|---|
| `lower-third` | `blocks/lt-clean-bar`, `blocks/lt-accent-underline`, `blocks/lt-kicker-name`, `blocks/lt-side-rule` | layout of each look; entrance and exit order, timings and eases | rewritten in Python; colours and fonts come from the theme (no Oswald, Archivo Black, League Gothic or mono fonts); sizes scale with the frame; text fits one line; placed above the caption band; bounce eases follow the theme; timings compress for short windows |
| `title-card` | `components/titlecard-calm`, `components/titlecard-lockup` | the kicker / headline / drift of calm; the kicker / settle / hairline rule / label of lockup; their envelopes | rewritten in Python; theme colours and fonts; an overlay mode that dims the footage; headline fit and wrap; always exits with a fade |
| `annotate` | `components/hw-callout-circle`, `components/hw-underline` | `hwHash`, the wobbled ellipse and the squiggle underline maths, draw-on timing, the stepped "boil" jitter | ported to Python; the circle overshoots its start; the boil is baked into the timeline as steps (no onUpdate callback) and is off in themes without bounce; no scribble fill, connector, stroke textures or Caveat font; labels use the theme font |
