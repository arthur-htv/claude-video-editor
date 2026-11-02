# Automatic edit

The user wants a finished, engaging video without choosing effects themselves (`/video-editor:auto`, `/video-editor auto`, "auto edit", "do everything", "make it engaging"). You scan each video, decide which effects fit what is actually said, render them in the right order and report what you did. Don't stop to ask between steps: make the call, note it, and let the user adjust afterwards. The only things that still need the user are the director's plan in step 5 (one look before rendering; skip it when the user said to decide everything), paid or upload services (never used here), and the first-video check when there are many videos.

`PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. Run everything from the project folder. `S` = `.claude/skills/video-editor/scripts`, `K` = `.claude/skills/kinetic-text/scripts`, `M` = `.claude/skills/morph-shapes/scripts`, `C` = `.claude/skills/captions/scripts`, `X` = `.claude/skills/cut-mistakes/scripts`.

The kit's Node scripts (`X/*.mjs`), and any `ffmpeg` or `ffprobe` you type yourself, use the copy on PATH. The session hook puts the portable copy there; if `ffmpeg -version` fails in the shell, prefix those commands with `PATH="$PWD/tools/ffmpeg/bin:$PATH"`. The Python scripts find it on their own.

## The run file

Each video keeps its progress in `work/<name>.run.json`, so a new or compacted session picks up where the last one stopped. `<name>` is the source file's name without its extension. Read it before anything else:

```
PY S/run_state.py <name> next
```

It prints the first unfinished step, `V`, `W`, the profile, preset and theme, whether the director's plan is approved, and the user's notes. Carry on from that step with those values. `show` prints everything else: each step's file and note, and every graphic window. With no run file yet, start at step 1. If it warns that the source changed, start over with `init ... --overwrite`. Emptying `work/` deletes the run file too.

Once a step's file exists, mark the step, and fill its cell of the report row:

```
PY S/run_state.py <name> step 2 done --out work/<name>.mp4 --note "9 cuts"   # a video --out becomes V
PY S/run_state.py <name> step 6b skipped --note "no graphics"
PY S/run_state.py <name> set W work/<name>.words.json                         # also V, profile, preset, theme, notes
PY S/run_state.py <name> report "Dead air" "9 cuts (tight)"
```

The step ids are `1`, `2`, `3`, `4`, `4b`, `4c`, `4d`, `5`, `6`, `6b`, `7` and `8`. A step that stopped half way isn't marked, so the next session redoes it (add `--overwrite` to its renders). Keep the user's own words there too: `set notes "no captions; keep it natural"`.

## Which videos

The ones the user named, otherwise every video in `input/` without a finished copy in `output/`. With more than three, finish the first one, report it, and ask whether the result is right before doing the rest, because auto decisions are worth one look before they're repeated many times.

## 1. Profile the video

Probe it (`ffprobe`, see the skill's Good habits) and pick a profile. The profile sets every default below.

| Profile | When | Dead-air preset | Punch-ins | Captions | Kinetic text | Morph graphics (check / X count too) |
|---|---|---|---|---|---|---|
| **short** | taller than wide, or under 90 s | `tight` | on | the theme's style (step 7) | default density | at least 5 s apart |
| **medium** | wide, 90 s to 5 min | `normal` | on | the theme's style (step 7) | default density | at least 15 s apart |
| **long** | wide, over 5 min | `normal` | off | `clean` + `--srt` | `--min-gap 15` | at least 45 s apart |

The user's own words beat the table: "keep it natural" means `gentle` and no punch-ins, "no zooms" means no punch-ins, "no captions" means skip captions, "lots of energy" means `tight`. Never change the aspect ratio in auto mode. That's a separate request (reframe recipe or `short-form-edit`).

**Look before you add.** Videos downloaded from Instagram, TikTok or YouTube are often finished edits already. Grab frames across the source:

```
PY -c "import sys; from pathlib import Path as P; sys.path.insert(0, '.claude/skills/video-editor/scripts'); from hfbuild import contact_sheet; contact_sheet(P('input/<file>'), [1, 5, 10, 15, 20, 30, 40], P('work/<name>.source-check.png'))"
```

The times suit a clip of about 45 s; spread 6 to 8 times over the clip's own length. Then measure where the face is, which every graphic's placement uses:

```
PY -c "import sys; sys.path.insert(0, '.claude/skills/video-editor/scripts'); from layout import analyze; print(analyze(sys.argv[1]).note)" input/<file>
```

It prints, for example, `face found at x 0.35-0.62, y 0.14-0.30` (fractions of the frame).

Then adjust:
- **Burned-in captions:** skip step 7. They can't be removed, and a second set would stack on top.
- **Existing text effects, cards or B-roll:** skip kinetic text for words already on screen (usually all of them). Place morph graphics only over plain talking-head stretches, never on top of an existing card.
- **Report it:** say what you skipped and why. Offer the full treatment if the user has the raw recording.

Then start the run file:

```
PY S/run_state.py <name> init input/<file> --profile short --preset tight
PY S/run_state.py <name> step 1 done --out work/<name>.source-check.png --note "<what you'll skip and why>"
```

## 2. Cut dead air

```
PY S/cut_dead_air.py input/<file> --preset <preset> --output-dir work
```

This writes `work/<name>.mp4`. Mark it: `PY S/run_state.py <name> step 2 done --out work/<name>.mp4`. The run file now holds `V`, the current video, which changes after every step. If it removed more than 50%, or warned about music or constant noise, redo it with `gentle` and `--overwrite` (`set preset gentle`) and mention it in the report. A video with no speech (b-roll, music, screen recording without voice) stops here: deliver the dead-air cut, or the untouched copy, and say that speech-based effects were skipped.

## 3. Transcribe and read it

```
PY S/transcribe.py V --out work/<name>.srt --words --json work/<name>.transcript.json
```

Read `work/<name>.srt` in full. Every later decision comes from what the speaker actually says. `W` (word timings) is now `work/<name>.words.json`. Note names, brands and products for `--keywords`, and anything misheard ("claw" for "Claude") to fix in the plans. Record them: `set W work/<name>.words.json`, then `step 3 done --out work/<name>.srt --note "keywords: Claude, HyperFrames; claw = Claude"`, so a later session has the keywords and fixes.

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
node X/apply-cuts.mjs work/<name>.transcript.json --cuts work/<name>.approved-cuts.json --video work/<name>.mp4 --output work/<name>.clean.mp4 --out-dir work --apply
```

`--video` is always the dead-air cut, `work/<name>.mp4`, never `V`: the transcript's times are on that cut. When you run this line again later (step 4b, or a re-cut), `V` is a later pass, and cutting it would remove the wrong words without a warning.

The cuts are measured on the waveform, like the dead-air cuts:
- Each edge moves to the quietest frame start within 0.12 s of its word edge, and never into a kept word. The frame starts are read from the video file itself, so phone clips with a variable frame rate stay frame-exact too.
- When a dead-air cut sits in the same pause, the edge moves onto it however far away, so no sliver of a few frames is left between two jump cuts. This needs step 2's finished render: if a later dead-air run failed, run step 2's render again with `--overwrite` first (without it, step 2 skips and leaves the failed run's report).
- Every join gets an 8 ms fade, and the timings use the video's own length.

Read what it prints:
- **"no quiet point between the words at 0:01.2":** the words there run together, so that cut keeps its approved edges. Step 4b listens to it.
- **"approved cut merged with a neighbour or left out":** a left-out cut sat inside a word that is mostly kept. Widen it to the whole word, or drop it.
- **"note: reports/<name>.json could not be read":** run step 2 again with `--overwrite`, then this step.
- **"WARNING: the cut video is N ms longer/shorter than the kept pieces":** say so in the report: graphics timed from it may be off by that much.

Then mark it: `step 4 done --out work/<name>.clean.mp4` (now `V`) and `set W work/<name>.mistakes-transcript.json` (re-timed from the edges actually rendered). With nothing approved, skip the apply and mark `step 4 skipped --note "nothing approved"`.

## 4b. Re-listen to the joins

The cuts re-time the words by arithmetic, and nobody has heard the joins yet. Listen again before anything is timed on this cut:

```
PY S/relisten.py V --words W
```

It has the `large-v3` model hear about 1.5 s on each side of every join in `V` (the joins come from the saved cut lists), then the same places in the uncut video. Each join is then compared with how that speech sounded before the cut, and the sound right at each cut is measured. The windows that overlap are merged, so on a video cut every few seconds it hears most of both videos: a 48 s clip with 14 joins took about 7 minutes. Give it a 10-minute timeout or run it in the background. Every line gives the join's time and the cut that made it: `dead-air cut`, or `mistake cut 15.10-16.40` (seconds of `work/<name>.mp4`, the times `approved-cuts.json` uses).

- **Notes:** words the model heard differently after the cut, where the cut does not go through them (a new neighbour changes how a word is heard). Change nothing, and leave them out of the report.
- **Problems** (the command exits with an error):
  - **clipped:** the cut goes through a word. It is heard as a piece or as another word ("Honest" for "Honestly"), or the sound is still going at the cut. A sound line names the word from the model's word times, which can be one word off: go by the time and the cut.
  - **missing** or **changed:** a word the cut goes through is lost, or heard as a different word.
  - **added:** an extra word on real sound at the join. "Part of what this cut takes out is still there" means a mistake cut stopped short of a word `W` says it removes ("dollars" left after a cut repeat).
  - **unheard:** the model heard nothing around that join, so its words were not checked.

Settle every problem before going on, because everything after this is timed on this cut. Move each join's edge at most once:

- **At a mistake cut:** in `work/<name>.approved-cuts.json`, move that cut's edge so the word is kept whole or cut whole: out to the pause before or after it, using the word times in `work/<name>.transcript.json`. For a "still there" line, extend the cut over that word only if it is part of what you meant to cut, up to the pause before the next word `W` keeps, never into it. If it is a word you meant to keep, leave the cut. Apply the cuts again (step 4) and run this again.
- **At a dead-air cut, or still flagged after one move:** keep the cut as it is, and name the word and its time in the report.
- **unheard:** run this once more. If it stays, name that join in the report as not checked.

If it says the uncut video is gone (or you passed `--joins`), the heard words are compared with `W`, so a word `W` misheard shows up as **changed**. When the heard word fits the sentence, sounds like the written one ("three" for "free") and nothing else is flagged at that join, keep the cut and use the heard word in the plans and captions.

Then `step 4b done`, or `step 4b skipped --note "<why>"`.

## 4c. Voice level

Set the voice to -14 LUFS, the level the platforms play speech at. It is one fixed gain for the whole video, so nothing swells up in the pauses. A limiter keeps the peaks at or under -2 dBTP, which leaves room for the sounds in step 6b. A voice recorded on one channel is copied to both. Nothing is cut, so `W` stays the same, and the picture is copied, not re-encoded.

```
PY S/voice_level.py V --out work/<name>.v.mp4
```

Then `step 4c done --out work/<name>.v.mp4` (now `V`). Add `--overwrite` when re-running. It prints the level before and after, and corrects itself once if it missed. If it says MISSED, reaching -14 LUFS would have the limiter take more than 5 dB off the whole voice and flatten it (common with computer voices), so it stopped lower. Keep the file and put the level it reached in the report. "Quieter" or a podcast means `--target -16`.

## 4d. Punch-ins on the jump cuts

Every cut so far is a jump cut at the same framing. Editors hide jump cuts by changing the framing on the cut, so this pass switches between full and 112% at the joins, centred on the face. Run it for the short and medium profiles. Skip it for the long profile, when the user says "keep it natural" or "no zooms", or when nothing was cut.

```
PY S/punch_in.py V --name <name> --out work/<name>.p.mp4   # V = work/<name>.p.mp4
```

Run it on `V`, the voice-level video from 4c (`work/<name>.v.mp4`). It has the mistake cut's timing, and that is what the saved cut lists describe. If the lists don't fit the video, it stops and says why. This happens when it's run on the dead-air cut while a mistake list exists, when the mistake list was made on an older dead-air cut, or when the lengths don't match. If step 4 cut nothing this time but `work/<name>.mistakes-edl.json` is left from an earlier run, move that file out of `work/` and run the pass again.

Each switch goes on the frame where the picture really jumps, because on phone videos the lists drift a frame or two from the real cut. It starts at full framing and holds each framing at least 2 s, so a join close to the last switch keeps its framing. The picture is encoded once and the sound is copied. Every frame keeps its time, so the cut map still fits the punched video. It prints the face box at the tighter framing:

```
face at the punch-in: x 0.32-0.68, y 0.23-0.42
```

In step 5, keep cards and text off this box and off the step 1 box. If the face is too big for 112%, the script lowers the zoom for the whole video, and below 105% it makes no punch-ins. If it finds no face, it centres on the upper middle of the frame. It says so in each case.

Look at `work/<name>.punch-check.png`. Each pair is marked "before" and "after" a switch; more than six switches add `-2`, `-3` pages. The whole face must be in every frame. If it isn't, re-run with `--zoom 1.08 --overwrite`. `--zoom 1.0` copies the video unchanged. After a re-cut, run it again with `--overwrite`, because the joins have moved. `--overwrite` also replaces `work/<name>.punch.json` and the sheet. Without it the script refuses, so a trial run can't replace them. To turn punch-ins off on a re-run, use `--zoom 1.0 --overwrite` rather than skipping the step: it rewrites `work/<name>.punch.json`, which step 8 would otherwise still read.

Then `step 4d done --out work/<name>.p.mp4`, or `step 4d skipped --note "<why>"`.

## 5. Direct the graphics (the "which is which")

First save the cut the plans are about to be timed on, and the words on it:

```
PY S/retime.py <name> --save
```

It writes `work/<name>.cutmap.json`. Run it once, after the last change to the cut and before planning.

Read the `talking-head-recut` skill's SKILL.md: it is the director's pass. Go through the transcript and write the director's plan, `work/<name>.director.md`: one row per graphic, timed to the word it lands on. The plan covers every graphic in the video: the templates, morph graphics and kinetic text below, and the cards you design for the moments none of them fits (a stat, key points, a term, a payoff). Show the plan and wait for the user's OK or changes, then build it. Once the user says OK (or said to decide everything), record it: `PY S/run_state.py <name> approve-director`. Write each card's motion with the numbers in the `cut-the-curve` skill.

Decide in this order: templates and designed cards, then morph graphics, then kinetic text. Each later layer stays out of the earlier ones' windows. Designed cards go into `work/<name>.templates.json` as `"template": "card"` entries and count like templates.

**Templates** (`motion-templates` skill; read its SKILL.md and `references/templates.md` for the spec format), for the structure of what's said:

| The speaker... | Template |
|---|---|
| walks through a process, a how-to, or options (3+ steps, at least about 8 s of explaining) | `flowchart` when it branches or has 5+ steps: it covers the speaker for that stretch while the voice continues. Up to 4 steps in a row, and always with the `apple` theme unless the user asks for a diagram: a staged checklist card (`talking-head-recut`) that keeps the speaker in view |
| lists tips or rules ("3 things", "first... second...") | `steps` |
| contrasts two ways (wrong vs right, A vs B) | `compare` |
| opens with a promise or a title-like first sentence ("This is how to...") | `hook-title` over that sentence. In vertical video, check the face on the source sheet: if it's high, set `position` under the chin (about `0.40`) |
| says one line worth remembering | `quote` (at most one per video) |
| starts a new part (long videos) | `chapter` |
| names a term or tool to remember | `tag` |
| ends with "follow", "save this", "subscribe" | `cta` over that line, or a designed end card. Add a `handle` only if the user gave one or the speaker says it. |
| names the speaker, a guest or their role ("I'm Franco, founder of...") | `lower-third`, once per person, 3 to 5 s from the word the name starts on. `clean-bar` by default; `accent-underline`, `kicker-name` or `side-rule` for a lighter look |
| introduces the topic or a new part, and the video is calm or premium (Apple style) | `title-card`: `calm` or `lockup`; a cutaway of 2.5 to 4 s, or `"mode": "overlay"` to keep the speaker in view, dimmed |
| points at something visible in the frame ("this card", "look at this number") | `annotate`: a circle or underline drawn on the word. Find `x`, `y` on the source sheet; keep it off the face and `y` under 0.7 |

- **One theme per video:** `apple` when the user asks for Apple style, clean, premium, minimal or keynote; `blueprint` for explainers, how-tos, money and business; `midnight` for everything else; `paper` when the user wants light or calm. The user's words win. Designed cards use the same theme. Record it: `set theme <theme>`.
- **Limits:** short videos get at most one flowchart. Templates and designed cards follow the director's density and spacing in `talking-head-recut` (its "How many" and "Timing, to the word"). The profile table's spacing column is for morph graphics and check / X marks.
- **Spec:** write all templates into `work/<name>.templates.json`, with times from `W`, the speaker's own words shortened, and icons from the skill's list.
- **Windows:** record every template and card window in the run file, as `cutaway` or `overlay`. The cutaways are `flowchart`, `steps`, `compare`, `quote`, `chapter` and `title-card` unless set to overlay, and cards with `"mode": "cutaway"`. Nothing else may appear inside them. The kind is the template's name (`card` for a designed card):
  ```
  PY S/run_state.py <name> window add cutaway 4.2 26.6 flowchart "how to apply"
  PY S/run_state.py <name> window add overlay 0 2.4 hook-title
  ```
  Adding the same window again replaces it. Before re-planning, run `window clear` and add them again.

**Morph graphics**, only where the speaker says something chartable, and never inside a cutaway template's window:

| The speaker says | Template | Mode |
|---|---|---|
| two or more amounts compared (before/after, A vs B, "from 6 to 1") | `circle-to-bars` | cutaway |
| parts of a whole ("60% editing, 25% filming…") | `circle-to-donut` | cutaway |
| one value over 3+ points in time | `dot-to-line` | cutaway |
| one striking percentage or score ("87%", "9 out of 10" as `--values 9 --max 10`) | `ring-to-number` | overlay |
| a clear verdict on the right or wrong way ("do this", "never do that") | `check` / `cross` (at most 2 per video) | overlay |

- Every number comes from the speaker's own words, exactly. If a number might be misheard, or the sentence is a hypothetical, skip the graphic. A video with nothing chartable gets no morph graphics, which is a fine result.
- Keep graphics as far apart as the profile says. Never put two cutaways within 20 s of each other: make the second an overlay or drop it.
- `--at` is the start of the first number word minus 0.2 s. For `ring-to-number`, the count reaches its number about 1.9 s after `--at`, so start it 1.8 s before the number word, and give it at least 3 s so the number holds a moment before it fades. For check / cross, start 0.6 s before the word that carries the verdict ("not" in "do not spend money", "right" in "this is the right way"), so the mark lands on it.
- `--duration` runs to the end of the sentence, between 2.5 and 4 s. If the sentence runs longer, stop at 4 s: a cutaway that holds the screen longer loses the speaker. Never run into the next graphic.
- Record each graphic's window, `at` to `at + duration`, with the kind `morph`: `PY S/run_state.py <name> window add cutaway 2.9 5.9 morph "bars 6 -> 1"` (`overlay` for the ring and the check / X). Steps 6b and 7 read them from there.

**Kinetic text:**

```
PY K/find_emphasis.py V --words W --keywords "<names and key terms>" --skip "$(PY S/run_state.py <name> skip-string)" --out work/<name>.emphasis.json   # plus --min-gap 15 for the long profile
```

`skip-string` prints every template, card and morph window widened by 1 s on each side (`"0-3.2,3.2-27.6,9-14"`), so no moment lands inside one. The rule lives in `run_state.py`. `--out` gives the plan a name that doesn't change with `V`, so steps 6 and 6b find it. Then edit `work/<name>.emphasis.json`:
- Remove any moment repeating a number or words a graphic already shows.
- Fix misheard words. Keep 1 to 4 words, exactly as spoken.
- Keep only moments that carry the message.
- Record each moment you keep: `window add overlay <start> <end> kinetic "<words>"`.

**Text behind the speaker** (`text-behind` skill), decided together with kinetic text: at most 1 or 2 per short video, on the single biggest number or claim ("90 DAYS", "$10K", "FREE").
- Only when the head and shoulders are in frame with wall around the head and the speaker is still: no mic arm, held object or fast motion.
- Keep it out of every other graphic's window and at least 5 s from any kinetic-text moment, and drop that word from the kinetic plan. Record its window: `window add overlay <start> <end> behind "FREE"`. Captions step aside for it.
- Each moment of about 2 s costs 0.5 to 2.5 minutes of background removal. The first run downloads a free 168 MB cutout model once.
- Write its plan, `work/<name>.behind.json`. It is rendered as the first pass of step 6.

When the plans are written and every window is recorded: `step 5 done --out work/<name>.director.md`.

## 6. Render, one pass at a time

Each pass reads the previous file in `work/`. Skip a pass with nothing to add. Run text behind the speaker first (the first line), on the clean cut video, so its cutout of the person never includes another graphic.

```
PY .claude/skills/text-behind/scripts/build_behind.py V --plan work/<name>.behind.json --theme <theme> --out work/<name>.b.mp4   # V = work/<name>.b.mp4
PY K/build_kinetic.py V --plan work/<name>.emphasis.json --out work/<name>.k.mp4                       # V = work/<name>.k.mp4
PY M/build_morph.py --template circle-to-bars --title "Hours per video" --labels "Before,Now" --values "6,1" \
   --video V --at 2.9 --duration 3 --out work/<name>.m1.mp4                                            # V = work/<name>.m1.mp4
PY M/build_morph.py --template ring-to-number --values 87 --unit % --labels "of my editing done by AI" \
   --video V --at 8.2 --duration 3 --mode overlay --out work/<name>.m2.mp4                            # V = work/<name>.m2.mp4
```

Then the templates and designed cards, all in one pass (`T` = `.claude/skills/motion-templates/scripts`):

```
PY T/build_template.py work/<name>.templates.json --video V --theme blueprint --out work/<name>.t.mp4   # V = work/<name>.t.mp4
```

The examples are from a real test. Use the values from your own step 5. Each kinetic moment takes about 10 to 20 s to render and each graphic about 30 s, so run long videos in the background or with a 10-minute timeout. Add `--overwrite` when re-running. When the last pass is done, mark the step with that pass's file: `step 6 done --out work/<name>.t.mp4`.

## 6b. Sound effects

Put a sound on each graphic (`sound-effects` skill; `SFX` = `.claude/skills/sound-effects/scripts`). Skip it when there are no graphics or the user said no sounds.

```
PY SFX/suggest_sfx.py V --templates work/<name>.templates.json --emphasis work/<name>.emphasis.json --morph "$(PY S/run_state.py <name> morph-string)" --words W   # plus --per-minute 8 for the long profile
PY SFX/add_sfx.py V --plan work/<name>.sfx.json --out work/<name>.s.mp4                                                                                    # V = work/<name>.s.mp4
```

Leave out the flags for plans that don't exist. Read the printed cues and drop any without a clear cause on screen. Check the add_sfx lines: true peak OK, change outside the cues about 0.00 dB, every cue within 1 frame. Captions copy the audio, so the sounds carry through to `output/`. Then `step 6b done --out work/<name>.s.mp4`, or `step 6b skipped --note "<why>"`.

## 7. Captions last

```
PY C/make_captions.py V --words W --style <style> --hide-during "$(PY S/run_state.py <name> hide-string)" --plan-only
```

`hide-string` prints the morph windows, the windows of cutaway templates and cutaway cards **except the flowchart**, and the text-behind windows. The rule lives in `run_state.py`. Captions step aside while a graphic is on screen and come back right after. Otherwise they cover the chart. A caption that runs into a window is shortened to end at its edge rather than dropped.

The flowchart keeps its bottom fifth free so captions continue under it, as in the reference reels. When a flowchart is in the video, add `--position bottom` so the captions sit there for the whole video. `<style>` is `clean` for a long video. Otherwise it is the theme's own: the `captions` value in `.claude/skills/motion-templates/themes/<theme>.json`. With the `apple` theme, or a designed card over the speaker in any theme, also add `--position bottom`, so the captions sit under the cards (`talking-head-recut` keeps those cards above 0.72 of the height when captions sit at the bottom). Otherwise captions sit just under the chin, and a card between the chin and the captions covers them.

Review `work/<V-stem>.captions.json` (named after `V`, such as `<name>.s.captions.json`):
- fix misheard names and brands
- check that numbers read right ("87%", "1,000")
- read the lines just before and after each window, so nothing important got too short
- recolor anything colored without a reason

Then burn the final video. Pass the same `--hide-during` again, so the check sheet also shows the frames around each graphic:

```
PY C/make_captions.py V --from-plan work/<V-stem>.captions.json --hide-during "$(PY S/run_state.py <name> hide-string)" --out output/<name>.mp4   # plus --srt for long
```

Then `step 7 done --out output/<name>.mp4`.

## 8. Check, then report

**First the machine check.** It reads every plan and rendered clip. For each problem, it names the graphic and the time: a font that isn't bundled, a graphic over the face or over a caption, two graphics less than 0.5 s apart, a black flash at the start or end of a full-screen graphic, an overlay still empty at its first check, a graphic cut off at the frame's edge, or a rendered clip that can't be read.

```
PY S/qa_graphics.py <name>   # plus --platform reels, tiktok or shorts when the user says it's an ad on that app
```

It takes the morph windows, and their labels, from the run file. Without a run file, add `--morph "<morph windows>"`. The face box comes from `work/<name>.punch.json` when punch-ins ran. Otherwise it is measured again: add `--face x0,y0,x1,y1` with the numbers from step 1 to save that time. The check writes `work/<name>.qa.json` and ends with "All clear" or `FAIL` lines. Fix the pass each FAIL line names, render again from that pass (add `--overwrite`), and run the check again until it is clear. If it stops with a message instead (exit 2), the message names the damaged plan or the missing video: fix that first.

Read the `note` lines too, even after "All clear". They say what the check couldn't look at, for example a run-file window that no plan covers, a morph graphic with no clip from this edit, or morph clips with no windows. Render what's missing, or tell the user.

`--platform` uses the apps' published ad safe zones, the strictest case, and only on 9:16 video. On all three apps, captions at 78% of the height and anything lower than 65% fail it. Add it only when the user says the video is an ad on that app; "for TikTok" alone means an organic post, so leave it out. It checks overlays and captions, not full-screen graphics: look at their sheets for text in the bottom third.

**Then one fresh-eyes pass.** Once the check is clear, start one fresh subagent that hasn't seen the edit. Give it:
- the check sheets: `work/<name>*kinetic-check.png`, `work/<name>*morph-check.png` (each pass names its sheet after the file it read, so the sheet for `m1` is `<name>.k.morph-check.png`), `work/<name>.t.templates-check.png` (every template, each flowchart box and the recap), `work/<name>.punch-check.png` (the framing switches at the joins) and `work/<name>*.captions-check.png` (the final video, with the frames around every graphic; named after the video step 7 read, such as `<name>.s.captions-check.png`)
- the director's plan, `work/<name>.director.md`
- the check report, `work/<name>.qa.json`
- the captions plan, `work/<name>*.captions.json` (such as `<name>.s.captions.json`), and `W`, the word timings it was made from

Ask it to list defects only, each with the graphic and the time:
- text that is hard to read, or a graphic not on its word or not as the plan says
- a chart showing a wrong number
- anything over the face or mouth, or a face cut off by a punch-in
- a word in `W` missing from the captions plan. Words hidden on purpose are fine: during a full-screen graphic, a morph graphic (overlays too) or text behind the speaker, the windows `hide-string` prints. So is a caption left alone after a cutaway ("credit score"): it is what's being said.

The sheets can miss a moment, such as a kinetic word or a flowchart recap. It can grab a frame of anything they miss: `ffmpeg -ss <time> -i output/<file> -frames:v 1 work/<name>-<time>.png`.

Fix what it lists, render that pass again, and run `qa_graphics.py` again. The fresh look happens once: don't send the fixed video back to it. Don't hand over something nobody has looked at.

Report one row per video. `PY S/run_state.py <name> report` prints it from the cells filled along the way. Fill any empty cell first (`report Length "0:30.7 → 0:15.6"`), then `step 8 done`.

| Video | Length | Dead air | Mistakes | Voice | Punch-ins | Templates and cards | Kinetic text | Graphics | Sounds | Captions |
|---|---|---|---|---|---|---|---|---|---|---|
| talk.mov | 0:30.7 → 0:15.6 | 9 cuts (tight) | 1 repeat | -20.5 → -14.0 LUFS | 3 (112%) | none (no process or list) | "waiting too long" 0:06.9, "let Claude" 0:13.1 | bars 6 → 1 at 0:02.9, ring 87% at 0:08.2 | 8 (whoosh ×3, pop ×2, ticks ×2, 1 impact) | reel |

Then:
1. The path in `output/`.
2. One line offering changes: fewer or more graphics, another caption style, put back a cut, a different chart, no punch-ins, or tight / gentle pacing.

Each change re-runs only the passes from that point on, because every in-between file is still in `work/`. Mark each re-run step again as it finishes, so the run file keeps the new `V`.

### Changing the cut after the plans

Putting back a cut, cutting more, or tight / gentle pacing changes the cut every plan is timed on. Don't plan step 5 again: change the cut, then move the plans onto it. The director's plan stays approved.

Marking a step again takes the marks off every step after it (it prints "Later steps to do again: ..."), so `next` in a new session picks up the re-cut where it stopped. Step 5 is the one step you don't run again: mark it again once 4d is marked, as below, so a new session doesn't plan it.

1. Change the cut.
   - A mistake cut: edit `work/<name>.approved-cuts.json` (take a cut out, or add one) and run the apply line of step 4 again, with `--video work/<name>.mp4` (the dead-air cut, not `V`). Then mark step 4 and set `W` as step 4 says.
   - The pacing: run step 2 again with the other preset and `--overwrite` (without it, step 2 keeps the video it already made). If the video has mistake cuts, run steps 3 and 4 again too: their times belong to the old dead-air cut. With no mistake cuts, the line below moves `W` onto the new cut, so mark steps 3 and 4 again without running them: `step 3 done --note "words moved by retime.py"`, then `step 4 skipped --note "nothing approved"`.
2. Move every plan onto the new cut, straight away:

   ```
   PY S/retime.py <name> --words W --morph "$(PY S/run_state.py <name> morph-string)"
   ```

   Every time keeps its place on its word, using the words saved before step 5, so neither a new transcription nor a longer or shorter pause can shift anything. Where a tighter cut leaves less room before a word, a graphic starts as the word before ends. This covers the templates (with every box and item inside them), each card's start, end and check frames, kinetic text, text behind, captions, and the windows in the run file, so its `--skip`, `--hide-during` and `--morph` strings follow too. Each sound stays with its graphic. Read what it prints: items dropped because their words were cut, cards whose length changed, kinetic text that now runs over words put back, captions that lost words, and the new `--morph` string. Words that come back get captions in the same style. The originals stay as `work/*.pre-retime.json`. Add `--dry-run` to see the changes first. Don't run `--save` again: this keeps the saved cut current itself.

   A designed card's own motion is not moved: its `tl` times count from the card's start. For each card it says "is now ... long", open `work/cards/<id>.html` and add the change (new length minus old) to every `tl` time that lands after the cut you changed. Add the same to that card's cues in `work/<name>.sfx.json` (their `why` names the card), which stay timed from the card's start.
3. Run steps 4b to 4d on the new cut, marking each (if 4b changes the cut again, run the line above again). Then mark step 5 again: `step 5 done --note "plans moved by retime.py"`. Then render again from step 6 with the moved plans. Add `--overwrite` to every pass you re-run (`add_sfx.py` has no such flag: it replaces its output anyway). In step 6b, run only the `add_sfx.py` line: the sound plan has moved too. Morph graphics take their new `--at` and `--duration` from the printed windows. Captions burn with `--from-plan`: planning them again would lose the review. Check the sheets again.
4. Fill the report's cells again with the new length and times before `step 8 done`: `report Length "0:44.6 → 0:27.8"`, and `report Graphics`, `report "Kinetic text"` and `report "Templates and cards"` with the moved times. The re-cut doesn't change them.
