---
name: captions
description: Burn readable, on-brand captions into a video in this folder. Default is the reel look from the editing playbook (1-3 words at a time, ALL CAPS Montserrat ExtraBold in a dark box with a thin light edge, colored keywords, placed below the face, never over the mouth); also a one-word "minimal" look and a sentence "clean" subtitle look, plus .srt files. Use this whenever the user asks for captions, subtitles, "words on screen", "text like TikTok/Reels", "make it readable without sound", or burned-in / open captions, even if they don't say "captions".
---

# Captions

Raw footage is in `input/`, finished videos go to `output/`, scratch goes to `work/` (same contract as the `video-editor` skill). `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS / Linux). `C` = `.claude/skills/captions/scripts`.

## Steps

1. **Caption the final cut, not the raw file.** Captions follow the timing of the video they're burned into, so cut dead air (and any other timing edits) first, into `work/`. Captioning the raw file and then cutting would leave every caption at the wrong time.
2. **Plan:**
   ```
   PY C/make_captions.py work/talk.mp4 --plan-only
   ```
   It transcribes locally (free, nothing uploaded), splits the words into short chunks at natural breaks, colors about a third of them by meaning, finds the face and picks a spot below it. The plan is `work/talk.captions.json`. If a `work/<name>.words.json` already exists, pass it with `--words` to skip transcribing again.
3. **Review the plan before burning.** This is where quality comes from:
   - Fix misheard words, names and brands (speech-to-text often mangles names, e.g. "Claude" heard as "claw").
   - Color should carry meaning: red = the wrong way or a loss, teal = the keyword or number, green = the action or payoff. Aim for 25-45% of chunks. Recolor anything where the color has no reason.
   - Never invent words the speaker didn't say.
4. **Burn:**
   ```
   PY C/make_captions.py work/talk.mp4 --from-plan work/talk.captions.json
   ```
   It writes `output/talk.mp4` and `work/talk.captions-check.png` (six frames). **Look at the check frames.** Confirm the captions are readable, sit below the mouth, and don't cover anything important.

## Options

| Need | Flag |
|---|---|
| One word at a time, smaller (raw-reel look) | `--style minimal` |
| Sentence subtitles for long-form / YouTube | `--style clean` |
| Also a subtitle file to upload | `--srt` |
| Move them | `--position top` / `middle` / `bottom` / `0.7` (fraction of the height) |
| Bigger or smaller | `--scale 1.2` |
| No colors or no serif accents | `--no-color`, `--no-serif` |
| Different output name / replace | `--out output/x.mp4`, `--overwrite` |

## Why the defaults look like this

From `docs/EDITING-PLAYBOOK.md`, measured on top-performing reels:
- 1-3 words, hard swaps, shown 2 frames before the word, so viewers read it as it's said.
- Every caption sits in the same dark box with a thin light edge. That reads on black, white and footage alike, and mixing boxed and bare captions looks cheap.
- Never white on a light background, and never over the mouth or chin, especially in the first second.

For animated, word-by-word karaoke captions or captions inside a HyperFrames composition, see the `hyperframes` skill's `references/captions.md`. This script covers the fast, reliable burned-in case.
