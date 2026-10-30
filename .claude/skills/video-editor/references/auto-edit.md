# Automatic edit

The user wants a finished, engaging video without choosing effects themselves (`/video-editor:auto`, `/video-editor auto`, "auto edit", "do everything", "make it engaging"). You scan each video, decide which effects fit what is actually said, render them in the right order and report what you did. Don't stop to ask between steps: make the call, note it, and let the user adjust afterwards. The only things that still need the user are paid or upload services (never used here) and the first-video check when there are many videos.

`PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. Run everything from the project folder. `S` = `.claude/skills/video-editor/scripts`, `K` = `.claude/skills/kinetic-text/scripts`, `M` = `.claude/skills/morph-shapes/scripts`, `C` = `.claude/skills/captions/scripts`, `X` = `.claude/skills/cut-mistakes/scripts`.

The kit's Node scripts (`X/*.mjs`) call `ffmpeg` from PATH. The session hook puts the portable copy there; if `ffmpeg -version` fails in the shell, prefix those commands with `PATH="$PWD/tools/ffmpeg/bin:$PATH"`.

## Which videos

The ones the user named, otherwise every video in `input/` without a finished copy in `output/`. With more than three, finish the first one, report it, and ask whether the result is right before doing the rest, because auto decisions are worth one look before they're repeated many times.

## 1. Profile the video

Probe it (`ffprobe`, see the skill's Good habits) and pick a profile. The profile sets every default below.

| Profile | When | Dead-air preset | Captions | Kinetic text | Morph graphics (check / X count too) |
|---|---|---|---|---|---|
| **short** | taller than wide, or under 90 s | `tight` | `reel` | default density | at least 5 s apart |
| **medium** | wide, 90 s to 5 min | `normal` | `reel` | default density | at least 15 s apart |
| **long** | wide, over 5 min | `normal` | `clean` + `--srt` | `--min-gap 15` | at least 45 s apart |

The user's own words beat the table: "keep it natural" means `gentle`, "no captions" means skip captions, "lots of energy" means `tight`. Never change the aspect ratio in auto mode. That's a separate request (reframe recipe or `short-form-edit`).

## 2. Cut dead air

```
PY S/cut_dead_air.py input/<file> --preset <preset> --output-dir work
```

This writes `work/<name>.mp4`. From here on, `V` is the current video and changes after every step. If it removed more than 50%, or warned about music or constant noise, redo it with `gentle` and mention it in the report. A video with no speech (b-roll, music, screen recording without voice) stops here: deliver the dead-air cut, or the untouched copy, and say that speech-based effects were skipped.

## 3. Transcribe and read it

```
PY S/transcribe.py V --out work/<name>.srt --words --json work/<name>.transcript.json
```

Read `work/<name>.srt` in full. Every later decision comes from what the speaker actually says. `W` (word timings) is now `work/<name>.words.json`. Note names, brands and products for `--keywords`, and anything misheard ("claw" for "Claude") to fix in the plans.

## 4. Mistakes (retakes, repeats, stutters)

```
node X/find-cut-candidates.mjs work/<name>.transcript.json --out-dir work
```

Read `work/<name>.cut-candidates.md` and decide each one:

- **Cut:** `repeat` with high confidence (a phrase said twice in a row), and a stutter ("the the", "I- I") unless it's deliberate emphasis ("never, never").
- **Cut:** a `retake` or `false_start` when the removed text is clearly an abandoned or redone version of what is kept.
- **Also cut** obvious flubs you saw in the transcript that the finder missed ("sorry, let me say that again" up to the restart). Take the times from `W`.
- **Keep** anything you're unsure about. A missed flub is better than a cut sentence.

If anything is approved, write `work/<name>.approved-cuts.json` as `{"cuts": [{"start": 5.98, "end": 7.30, "reason": "repeated phrase"}]}` and apply it:

```
node X/apply-cuts.mjs work/<name>.transcript.json --cuts work/<name>.approved-cuts.json --video V --output work/<name>.clean.mp4 --out-dir work --apply
```

Then `V = work/<name>.clean.mp4` and `W = work/<name>.mistakes-transcript.json` (already re-timed). With nothing approved, skip the apply.

## 5. Decide the graphics (the "which is which")

Decide the morph graphics first, because kinetic text has to stay out of their way.

**Morph graphics**, only where the speaker says something chartable:

| The speaker says | Template | Mode |
|---|---|---|
| two or more amounts compared (before/after, A vs B, "from 6 to 1") | `circle-to-bars` | cutaway |
| parts of a whole ("60% editing, 25% filming…") | `circle-to-donut` | cutaway |
| one value over 3+ points in time | `dot-to-line` | cutaway |
| one striking percentage or score ("87%", "9 out of 10" as `--values 9 --max 10`) | `ring-to-number` | overlay |
| a clear verdict on the right or wrong way ("do this", "never do that") | `check` / `cross` (at most 2 per video) | overlay |

- Every number comes from the speaker's own words, exactly. If a number might be misheard, or the sentence is a hypothetical, skip the graphic. A video with nothing chartable gets no morph graphics, which is a fine result.
- Keep graphics as far apart as the profile says. Never put two cutaways within 20 s of each other: make the second an overlay or drop it.
- `--at` is the start of the first number word minus 0.2 s. For check / cross, start 0.6 s before the word that carries the verdict ("not" in "do not spend money", "right" in "this is the right way"), so the mark lands on it.
- `--duration` runs to the end of the sentence, between 2.5 and 4 s. If the sentence runs longer, stop at 4 s: a cutaway that holds the screen longer loses the speaker. Never run into the next graphic.
- Write the window `at` to `at + duration` for each graphic. Steps 6 and 7 use these windows.

**Kinetic text:**

```
PY K/find_emphasis.py V --words W --keywords "<names and key terms>"   # plus --min-gap 15 for the long profile
```

Then edit `work/<V-stem>.emphasis.json`:
- Remove any moment within 1 s of a morph window, and any moment repeating a number a graphic already shows.
- Fix misheard words. Keep 1 to 4 words, exactly as spoken.
- Keep only moments that carry the message.

## 6. Render, one pass at a time

Each pass reads the previous file in `work/`. Skip a pass with nothing to add.

```
PY K/build_kinetic.py V --plan work/<V-stem>.emphasis.json --out work/<name>.k.mp4                     # V = work/<name>.k.mp4
PY M/build_morph.py --template circle-to-bars --title "Hours per video" --labels "Before,Now" --values "6,1" \
   --video V --at 2.9 --duration 3 --out work/<name>.m1.mp4                                            # V = work/<name>.m1.mp4
PY M/build_morph.py --template ring-to-number --values 87 --unit % --labels "of my editing done by AI" \
   --video V --at 8.2 --duration 2.6 --mode overlay --out work/<name>.m2.mp4                          # V = work/<name>.m2.mp4
```

The examples are from a real test. Use the values from your own step 5. Each kinetic moment takes about 10 to 20 s to render and each graphic about 30 s, so run long videos in the background or with a 10-minute timeout. Add `--overwrite` when re-running.

## 7. Captions last

```
PY C/make_captions.py V --words W --style <reel|clean> --hide-during "2.9-5.9,8.2-10.8" --plan-only
```

`--hide-during` takes the morph windows: captions step aside while a graphic is on screen and come back right after. Otherwise they cover the chart. A caption that runs into a window is shortened to end at its edge rather than dropped.

Review `work/<V-stem>.captions.json`:
- fix misheard names and brands
- check that numbers read right ("87%", "1,000")
- read the lines just before and after each window, so nothing important got too short
- recolor anything colored without a reason

Then burn the final video. Pass the same `--hide-during` again, so the check sheet also shows the frames around each graphic:

```
PY C/make_captions.py V --from-plan work/<V-stem>.captions.json --hide-during "2.9-5.9,8.2-10.8" --out output/<name>.mp4   # plus --srt for long
```

## 8. Check, then report

Look at the check frames:
- `work/*kinetic-check.png` and `work/*morph-check.png`. Each pass names its sheet after the file it read, so the sheet for `m1` is called `<name>.k.morph-check.png`.
- `work/<V-stem>.captions-check.png`, which shows the final video and includes the frames around every graphic.

Make sure that:
- text is readable, nothing covers the face or mouth, and no two graphics overlap
- charts show the right numbers

Fix and re-render the pass that's wrong. Don't hand over something you haven't looked at.

Report one row per video:

| Video | Length | Dead air | Mistakes | Kinetic text | Graphics | Captions |
|---|---|---|---|---|---|---|
| talk.mov | 0:30.7 → 0:15.6 | 9 cuts (tight) | 1 repeat | "waiting too long" 0:06.9, "let Claude" 0:13.1 | bars 6 → 1 at 0:02.9, ring 87% at 0:08.2 | reel |

Then:
1. The path in `output/`.
2. One line offering changes: fewer or more graphics, another caption style, put back a cut, a different chart, or tight / gentle pacing.

Each change re-runs only the passes from that point on, because every in-between file is still in `work/`.
