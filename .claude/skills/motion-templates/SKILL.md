---
name: motion-templates
description: A library of reusable motion-graphic templates for the videos in this folder, in swappable themes (blueprint, midnight, paper, apple). It includes a flowchart explainer that builds itself box by box while the speaker explains, with the camera following each step and zooming out to the whole map at the end. It also has numbered steps, a this-vs-that comparison, a quote card, a chapter card, a hook title, label tags that point at things, a save / follow end card, and ready-made pieces adapted from HeyGen's HyperFrames library: lower thirds (a clean name bar and three bare styles), calm Apple-like title cards, and hand-drawn circles and underlines. Use this whenever the user wants an explainer, a diagram or flowchart, a "how it works" or process visual, a list of steps or tips, a comparison, a quote, a chapter or section card, a title or hook card, a lower third or name bar ("put my name and title on screen", "who is speaking"), a title card or intro card, circling or underlining something in the frame, labels or callouts, a call to action or end card, templates, a consistent visual style or theme, or an edit "like this reel" with diagrams, even if they don't say "template".
---

# Motion templates

Folder contract as in the `video-editor` skill: read from `input/` or `work/`, keep in-between files in `work/`, deliver to `output/`.
- `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`.
- `T` = `.claude/skills/motion-templates/scripts`.

Each template is a HyperFrames scene filled from a short JSON spec. **Every field, with examples, is in `references/templates.md`.** Read it before writing a spec.

## Pick the template from what is said

| The speaker... | Template | How it sits |
|---|---|---|
| explains a process, a how-to, or options (3+ steps, maybe branches) | `flowchart` | full-screen cutaway; the voice keeps going, and the bottom fifth stays free for captions |
| lists tips or rules ("3 things...", "first... second...") | `steps` | cutaway, or a panel over the speaker |
| contrasts two ways (A vs B, wrong vs right, before vs after) | `compare` | cutaway |
| says one line worth remembering | `quote` | cutaway, or a panel |
| starts a new part of a longer video | `chapter` | short cutaway (1.5 to 2.5 s) |
| opens with a promise ("This is how to...") | `hook-title` | overlay at the top, first 2 to 3.5 s |
| names a term or tool to remember, or shows an object | `tag` | small overlay label, optionally pointing at the object |
| ends with "follow", "save this", "subscribe" | `cta` | overlay over the last 2 to 4 s |
| names themselves, a guest, or their role ("I'm Franco, founder of...") | `lower-third` | overlay above the captions, 3 to 5 s, once per person |
| introduces the topic or a new part, calmly (Apple-style, premium, a breather) | `title-card` | cutaway (2.5 to 4 s), or an overlay that dims the speaker |
| points at something in the frame ("this card", "look at this number") | `annotate` | hand-drawn circle or underline drawn on the word; `tag` when it needs a label with a pointer |
| anything none of these fits, designed by hand | `card` | overlay or cutaway; written by the `talking-head-recut` skill |

Numbers that compare or count belong to `morph-shapes` (bar charts, rings). Single emphasized words belong to `kinetic-text`. Templates are for structure: steps, options, contrasts and sections.

## Themes (one per video)

| Theme | Look | Good for | Captions to pair |
|---|---|---|---|
| `blueprint` (default) | dark navy graph paper, glowing blue lines, handwriting, hand-drawn icons | explainers, money, business, how-tos | `--style hand` |
| `midnight` | near-black, bold sans, teal accent | tech, polished talking heads (matches kinetic text and morph charts) | `--style reel` |
| `paper` | warm off-white paper, ink lines, serif headlines, orange accent | education, lifestyle, story-driven | `--style reel` |
| `apple` | black, Inter, one blue accent, dark glass panels, hairline borders | Apple-style, clean, premium, keynote, product and tech | `--style apple` |

The user's words choose the theme ("dark", "light", "like this reel"; "Apple", "clean" or "premium" means `apple`). Without a hint, use `blueprint` for explainers and `midnight` for everything else.

## Steps

1. **Work on the final cut** (dead air and mistakes already removed), with its word timings `W`: `work/<name>.words.json`, or the re-timed `mistakes-transcript.json`.
2. **Write `work/<name>.templates.json`**, a list of specs.
   - **Times:** seconds on the video's timeline, taken from `W`. Each element appears as its words are said (word start minus about 0.1 s).
   - **Text:** the speaker's own words, shortened to 2 to 6 words per box. Mark accent words with `*stars*`.
   - **Facts:** never invent facts or numbers that weren't said.
   - **Icons:** pick each box's icon from `assets/icons/` (the list is in the reference).
3. **Render** everything in one pass, one encode:
   ```
   PY T/build_template.py work/<name>.templates.json --video V --theme blueprint --out work/<name>.t.mp4
   ```
   Each template takes about 15 to 40 s to render (longer flowcharts take longer), so give long videos a 10-minute timeout.
4. **Look at `work/<name>.t.templates-check.png`.** Check that:
   - the text is readable and nothing is cut off
   - each box appears on its word
   - the flowchart recap at the end shows the whole map

   Fix the spec and re-run with `--overwrite`.
5. **Captions last** (`captions` skill), with the theme's caption style.
   - Pass the windows of cutaway templates **except `flowchart`** to `--hide-during`. The flowchart leaves the bottom free so captions continue under it, as in the reference reels.
   - Overlays at the top (hook title, top tags) need no hiding.

**Preview without a video:**
```
PY T/build_template.py spec.json --size 1080x1920
```
This writes `work/previews/tpl-*.mp4` (or a transparent `.webm`) and `work/*.check.png`; `output/` is only for finished videos. Use `--size 1920x1080` for wide video.

**Re-rendering is cheap:** a clip whose page, size and fps haven't changed since its last render is reused (the build prints "Reused"), so fixing one spec in a list re-renders only that one. Delete the clip in `work/templates/` or `work/previews/` to force a fresh render.

## Timing rules

- **Flowchart:** start about 0.3 s before the first step is said; end when the explanation ends. The speaker returns after it. The zoom-out recap plays by itself in the last 3 s, if there are about 3.4 s after the last box; otherwise end the flowchart a little later. A box follows only one box, so branches can't join again; show an "either way" outcome over the speaker after the flowchart.
- **Hook title:** from 0 to the end of the first sentence. In vertical video, check where the face is first: if `top` would cover the eyes, set `position` under the chin (about `0.40`). **cta:** the last 2 to 4 s.
- **No overlaps:** never put two cutaways at the same time. Never put kinetic text, morph graphics or tags inside a cutaway's window: the cutaway covers the speaker, and anything laid over it sits on the graphic.
- **Spacing:** keep templates spaced like other graphics (see the profile table in the video editor's `references/auto-edit.md`), measured as the gap from one graphic's end to the next one's start. A long flowchart counts as one graphic. The hook title and the cta are bookends at the very start and end, so they don't count toward spacing.

## Customizing

- **Tweak one render:** edit `work/hyperframes/tpl-*/index.html` and render again. The `morph-shapes` skill shows how to lay an edited clip back into the video.
- **New theme:** copy `themes/blueprint.json` and change the `vars`. A top-level `"pop"` ease (apple: `"power3.out"`) replaces every template's `back.out` bounce and slows the cta tap; leave it out for bouncy pop-ins. The fonts available are `'Montserrat XB'`, `'Abril Fatface'`, `'Architects Daughter'` and `'Inter'` (400, 600, 700; set `"weight"` in `vars`). To add a font, put the TTF in `video-editor/assets/fonts/` and add its `@font-face` to `FONT_CSS` in `hfbuild.py`.
- **New template:** add `scripts/templates/<name>.py` with `build(spec, ctx) -> Scene` and a JSON example in its docstring, then add the name to `TEMPLATES` in `build_template.py`. Write pop-in eases as `ctx.ease("back.out(1.6)")` so themes without bounce stay calm. `PY T/build_template.py --self-test` builds every template in every theme, vertical and wide.
- **More icons:** add Lucide SVGs (ISC license, lucide.dev) to `assets/icons/`.
