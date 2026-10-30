---
name: morph-shapes
description: Engaging morphing-shape motion graphics for videos in this folder - a circle that splits and grows into a bar chart, a disk that hollows into a donut chart, a dot that draws a line chart, a circle that morphs into a check mark or an X, a progress ring that counts up to a number, and an abstract shape sequence (circle, square, triangle, star). Renders standalone clips or drops them into a video as a full-screen cutaway or a glass overlay beside the speaker. Use this whenever the user wants morphing shapes, animated charts or stats, "show this number visually", before/after comparisons, checkmark/X moments, data graphics, or something to add engagement to a talking video.
---

# Morph shapes

Folder contract as in the `video-editor` skill. `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. `M` = `.claude/skills/morph-shapes/scripts/build_morph.py`.

## Pick the template from what is being said

| The speaker says... | Template | Example |
|---|---|---|
| a comparison: before/after, A vs B, two periods | `circle-to-bars` | `--labels "Before,After" --values "6,1" --title "Hours per edit"` |
| parts of a whole, a split, "most of my time goes to" | `circle-to-donut` | `--labels "Editing,Filming,Planning" --values "60,25,15"` |
| a trend: one value over 3+ points in time, "it kept climbing" | `dot-to-line` | `--labels "Jan,Feb,Mar,Apr" --values "1.2,2.5,4.1,7.8" --unit k` |
| yes, done, the right way | `check` | `--label "Approved"` |
| no, wrong, the mistake | `cross` | `--label "Not this"` |
| one striking percentage or score | `ring-to-number` | `--values 87 --unit % --labels "of edits done by AI"` |
| a transition or abstract beat | `shape-sequence` | `--colors "teal,yellow,purple,green"` |

**Numbers must come from the user or from the speaker's own words. Never invent or "round up" data** to make a chart look better. A chart that misstates a claim is worse than no chart.

## Steps

1. **Standalone preview first** (fast, nothing else touched):
   ```
   PY M --template circle-to-bars --title "Hours per edit" --labels "Before,After" --values "6,1"
   ```
   It writes `output/morph-<template>-<title>.mp4` (dark "black is the canvas" background with a faint grid) and `work/morph-...-check.png`. **Look at the check frames.** Add `--size 1080x1920` for vertical, or `--transparent` for a WebM with an alpha channel to use in another editor.
2. **Into the video** at the moment the speaker says it:
   ```
   PY M --template circle-to-bars --labels "Before,After" --values "6,1" --video work/talk.mp4 --at 12.4
   ```
   - `--mode cutaway` (default): the graphic fills the screen for `--duration` seconds (default 4) while the voice continues, like a B-roll shot. This is the clearest option for charts.
   - `--mode overlay`: a dark glass panel beside the speaker. The side is chosen away from the face; in vertical video it goes above or below the face.

   Find `--at` from the transcript (`work/<name>.words.json`). For charts, use the start of the word that introduces the number, minus about 0.2 s. A `check` or `cross` is complete about 0.75 s after `--at`, so start it about 0.6 s before the word that carries the verdict ("not" in "do not spend", "right" in "the right way"). As an overlay it floats on its own, compact, without a panel; its label sits in a dark box so it reads on any background. A cutaway runs to the end of the sentence it illustrates, between 2.5 and 4 s.
3. Check `work/<name>.morph-check.png`, then continue the chain (captions last) or deliver.

## Customizing

Every render leaves an editable HyperFrames composition in `work/hyperframes/morph-*/index.html`. For a bespoke morph (your logo becoming a chart, an icon becoming another), copy that file, change the SVG shapes or paths, and render it with `PY .claude/skills/video-editor/scripts/hf.py render <dir> -o work/x.mp4`.

To put an edited graphic back into the video, render it and lay it over in one step. `True` makes a transparent overlay; use `False` and `.mp4` for a full-screen cutaway:

```
PY -c "import sys; from pathlib import Path as P; sys.path.insert(0, '.claude/skills/video-editor/scripts'); import hfbuild as h; c = h.render(P('work/hyperframes/morph-cross-x'), P('work/x.webm'), 30, True); h.overlay(P('work/talk.k.mp4'), [{'path': c, 'start': 9.96}], P('work/talk.m2.mp4'))"
```
- MorphSVG and DrawSVG are loaded locally from `node_modules/gsap`.
- Follow the `gsap` and `hyperframes` skills and `MOTION_PHILOSOPHY.md`: animate transforms and attributes, keep everything deterministic, and end every timeline with the slot-filling `tl.to({}, {duration}, 0)`.
