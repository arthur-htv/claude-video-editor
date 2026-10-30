---
name: text-behind
description: Put one big word or short number BEHIND the speaker, with the person cut out and layered in front of it (text behind me, word behind the speaker, depth text, behind-the-head title, magazine-cover title, parallax title, "like MrBeast / Ali Abdaal style big word behind me"). Runs fully locally (HyperFrames remove-background with a free u2net model, no upload). Use this whenever the user asks for text behind them, a word behind their head, depth or 3D text, a cutout title, or the "big word behind the person" look, even if they don't say "text-behind". Background removal is slow, so it's for a few seconds at a time, about 1-2 moments per short video.
---

# Text behind the speaker

Folder contract as in the `video-editor` skill: read from `input/` or `work/`, deliver to `output/`. `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. `T` = `.claude/skills/text-behind/scripts`.

One big word sits behind the person: the head and shoulders cover part of it, and the rest reads around them. It is the "embed" from HeyGen's caption model: a scarce, earned peak, not a caption style.

## When to use it

- A single word or a short number said with weight: "90 DAYS", "$10K", "NEVER", "FREE".
- Head and shoulders in frame, with some background around the head (wall, sky, room).
- The person is mostly still for those 2-3 seconds.
- At most one per beat and never two on screen together: about 1-2 in a short video, one per section in a long one.

## When not to

The matte model (u2net_human_seg, 320 px) is soft and runs per frame. It loses mic arms, lets rigs near the body leak in, and flickers on anything that moves fast. In these cases the cutout edge visibly flickers or the word shows through the person, so pick another moment or use `kinetic-text`:

- mic arms, headphones with cables, held objects (phone, cup, product)
- fast head or hand motion, walking, camera moves
- busy or flyaway hair against a busy background
- no wall left above or beside the head (the word can only ride very high, and less depth shows)

## Steps

1. **Work on the final cut** (dead air and retakes already removed), so the times match.
2. **Pick the moment.** Take the word time from `work/<name>.words.json` (or `kinetic-text`'s `find_emphasis.py`). `--at` is when the word is said; the word rises 0.15 s before it and lands on it.
3. **Build:**
   ```
   PY T/build_behind.py work/talk.mp4 --at 28.28 --end 28.9 --text "90 DAYS" --theme apple --out work/talk.b.mp4
   ```
   Several moments in one run (one encode) from a plan like kinetic-text's:
   ```
   PY T/build_behind.py work/talk.mp4 --plan work/talk.behind.json --theme midnight
   ```
   `{"moments": [{"start": 28.28, "end": 28.9, "text": "90 DAYS"}, {"start": 61.2, "end": 61.6, "text": "FREE", "color": "accent"}]}`. Optional per moment: `duration` (seconds on screen, default about 2 s from the spoken length) and `color`. `--only 1` builds one moment of a plan.
4. **Look at** `work/<out-stem>.behind-check.png` (landed, middle, before the exit) and the printed coverage line. Then open a couple of frames yourself. Check that the word is clearly behind the head, readable, and that the cutout edge is clean. If the person's outline flickers, drop the moment.

`PY T/build_behind.py --self-test` checks the timing and placement maths.

## What the script decides

- **Is there a speaker?** It looks for a face in the window before the slow step. The matte model "finds" people in anything (it cut out colour bars in a test), so with no face it stops with a message. It also stops if a moment falls outside the video, or two moments would be on screen together. It warns when the outline jumps around (flicker).
- **Font and colour** from the theme (`blueprint`, `midnight`, `paper`, `apple`), the same look as `motion-templates`. The colour is the theme's text colour unless it would vanish into what's behind the word. Then it switches to the accent, then to the theme background colour (black for `apple` on a light wall). `--color accent` (or `#hex`, or a colour name) overrides it.
- **Size and place:** the word spans about 86% of a vertical frame (62% of a wide one), capped in height. It starts centred on the face, with its middle at the top of the face box. Then it moves up, down and sideways, and shrinks, measured on the matte over every frame it is on screen:
  - The goal is that the person covers **30-55%** of the word. Under about 15% it floats; over about 65% it is eaten.
  - **No letter may be more than half hidden.** Readable beats the goal. When the head sits in the middle of a short word, the script takes the most-covered placement that keeps every letter readable (often 15-25%: the word rides high, with the hair over the bottom of the middle letters, like a magazine cover) and prints `(shallow: every letter kept readable)`. If even that is impossible, it warns: use a shorter word or another moment.
- **Check:** after rendering, the real word is measured against the matte again and printed (`covered 17%-17%`).
- **Motion:** it rises from behind the shoulders (expo.out, 0.3 s), pushes in 3% while it holds, and fades up and out in 0.25 s.
- **Clean edges:** the person layer is the source video's own pixels, with the matte as alpha, so there is no colour shift or doubled edge.
  - The matte gets a levels curve (0.3-0.8). Its soft fringe would otherwise pull a glow of wall pixels over the word around the hair.
  - The audio is copied untouched, and everything is one encode.
  - The window is cut frame-exact, so the person layer lines up with the frame under it.
- **Colour per pixel:** the colour switches if more than 15% of the visible word would sit on pixels it can't be seen against. A white word whose bottom runs over a white shirt the matte missed counts.

## Cost and timing

- First run only: HyperFrames downloads `u2net_human_seg.onnx` (176 MB, free, from the rembg GitHub release) into `~/.cache/hyperframes/background-removal/models`. It also installs `onnxruntime-node` (about 214 MB) into `~/.cache/hyperframes/optional`. That took about 3 minutes here. Nothing is uploaded, and later runs work offline.
- Background removal is the slow step. It runs at about 2 fps at 1080p on an idle CPU, which is about 15 s per second of screen time. On a busy machine it was measured at 0.4-0.8 fps, up to about 75 s per second of screen time.
  - A 2 s moment (2.3 s with handles, 68 frames) took 2.5 minutes here, and a 1.5 s one took 1.5 minutes, both under load.
  - The word render takes 15-80 s, and the final encode takes under a minute for a short video.
- The cutout is cached per window in `work/behind/`. Re-running with a different word, theme or colour skips the slow step.

## In `/video-editor:auto` and with other effects

It is a moment, like kinetic text, and goes in the same step (step 3 of the order: templates and cards first, then charts, then kinetic text and text-behind kept clear of all of them).

- At most 1-2 per short video, at the biggest number or claim. Never in a window where another graphic, card or kinetic word is on screen, and at least a beat (about 5 s) from any kinetic-text moment.
- A word picked for text-behind is not also a kinetic-text word: drop it from the kinetic plan.
- Captions go on afterwards (`captions --hide-during` with this window) so they don't sit over the big word.
- Each pass reads from `work/` and writes the next file; only the last pass goes to `output/`.
