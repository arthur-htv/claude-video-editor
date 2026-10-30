---
name: kinetic-text
description: Add kinetic typography to a talking video only where it matters - the words the speaker emphasizes (louder, slower, after a pause), numbers, names and key claims - with five styles (pop, slam for numbers, typewriter "kinetic typing", highlight marker, stack) placed away from the face and spaced out so the video never gets cluttered. Use this whenever the user asks for kinetic text, animated text, text pops, emphasis words, highlights, "make the key points pop", typing effect, or on-screen keywords, even if they don't say "kinetic".
---

# Kinetic text

Folder contract as in the `video-editor` skill: read from `input/` or `work/`, deliver to `output/`. `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. `K` = `.claude/skills/kinetic-text/scripts`.

The point is restraint. Text on every sentence is noise. A few well-timed moments make the viewer feel the emphasis the speaker put in. Default: about one moment per 12 seconds, at least 5 seconds apart, never two on screen at once.

## Steps

1. **Work on the final cut** (dead air already removed), so the times match.
2. **Find the moments:**
   ```
   PY K/find_emphasis.py work/talk.mp4 --keywords "Claude, 10x"
   ```
   It scores every word by delivery (louder than the speaker's own running level, stretched out, a pause before it) and by content (numbers, money, absolutes like "never", names, contrasts, the user's keywords). It writes the strongest, spaced-out picks to `work/talk.emphasis.json` and prints them with the reasons. Pass `--words work/talk.words.json` if a transcript exists, `--max N` and `--min-gap S` to tune density.
3. **Edit the plan.** You and the user decide. The detector proposes, judgment picks:
   - Keep moments that carry the message. Drop filler ones. If the user named moments ("pop 'ten times faster' at 0:32"), add them.
   - Keep the text short (1-4 words) and exactly as spoken, apart from capitalization or a symbol ("10x").
   - Choose a style per moment: `pop` (one strong word), `slam` (a number or price), `typewriter` (a name, tool or phrase, the "kinetic typing" look), `highlight` (a key phrase; optional `"key": ["word"]` to mark only some words), `stack` (2-3 punchy words). Set `color` by meaning: red = problem or loss, teal = keyword, green = payoff, yellow = attention. Optionally set `position` (`top`, `center`, `lower`, `left`, `right`, `y=0.3`).
4. **Preview one or two**, then build all:
   ```
   PY K/build_kinetic.py work/talk.mp4 --plan work/talk.emphasis.json --only 1,2 --out work/kt-preview.mp4
   PY K/build_kinetic.py work/talk.mp4 --plan work/talk.emphasis.json
   ```
   Each moment renders as a short transparent HyperFrames clip (about 10-20 s each), timed 0.15 s before the word, then everything is laid over the video in one encode. The audio is untouched. **Look at** `work/talk.kinetic-check.png`: is the text readable, off the face, and not cramped?

## Placement and combining

- Placement comes from the face position. In wide video the text goes to the side away from the face. In vertical video it goes under the chin and above the captions, or above the head when there's room.
- With captions: do kinetic text first, then captions on top (`captions` skill, `--from-plan` with the final video). Captions sit low and kinetic text sits higher. If both are needed in the same spot, move one with `position`.
- With music or morph graphics: each step is a pass from `work/` into the next file, and only the last pass goes to `output/`.

The motion follows `MOTION_PHILOSOPHY.md`: one idea per beat, the visual lands just ahead of the word, `back.out` / `expo.out` entries, quick exits, and every timeline fills its slot so there are no black flashes. For a fully custom kinetic sequence (a hook title, a 15-second promo), build a HyperFrames composition with the `hyperframes` and `gsap` skills instead.
