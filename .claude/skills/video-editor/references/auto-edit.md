# Automatic edit

The user wants a finished, engaging video without choosing effects themselves (`/video-editor:auto`, `/video-editor auto`, "auto edit", "do everything", "make it engaging"). You scan each video, decide which effects fit what is actually said, render them in the right order and report what you did. Don't stop to ask between steps: make the call, note it, and let the user adjust afterwards. The only things that still need the user are the director's plan in step 5 (one look before rendering; skip it when the user said to decide everything), paid or upload services (never used here), and the first-video check when there are many videos.

`PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. Run everything from the project folder. `S` = `.claude/skills/video-editor/scripts`, `K` = `.claude/skills/kinetic-text/scripts`, `M` = `.claude/skills/morph-shapes/scripts`, `C` = `.claude/skills/captions/scripts`, `X` = `.claude/skills/cut-mistakes/scripts`.

The kit's Node scripts (`X/*.mjs`), and any `ffmpeg` or `ffprobe` you type yourself, use the copy on PATH. The session hook puts the portable copy there; if `ffmpeg -version` fails in the shell, prefix those commands with `PATH="$PWD/tools/ffmpeg/bin:$PATH"`. The Python scripts find it on their own.

## Which videos

The ones the user named, otherwise every video in `input/` without a finished copy in `output/`. With more than three, finish the first one, report it, and ask whether the result is right before doing the rest, because auto decisions are worth one look before they're repeated many times.

## 1. Profile the video

Probe it (`ffprobe`, see the skill's Good habits) and pick a profile. The profile sets every default below.

| Profile | When | Dead-air preset | Captions | Kinetic text | Morph graphics (check / X count too) |
|---|---|---|---|---|---|
| **short** | taller than wide, or under 90 s | `tight` | `reel` (`hand` with blueprint, `apple` with apple) | default density | at least 5 s apart |
| **medium** | wide, 90 s to 5 min | `normal` | `reel` (`hand` with blueprint, `apple` with apple) | default density | at least 15 s apart |
| **long** | wide, over 5 min | `normal` | `clean` + `--srt` | `--min-gap 15` | at least 45 s apart |

The user's own words beat the table: "keep it natural" means `gentle`, "no captions" means skip captions, "lots of energy" means `tight`. Never change the aspect ratio in auto mode. That's a separate request (reframe recipe or `short-form-edit`).

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

## 5. Direct the graphics (the "which is which")

Read the `talking-head-recut` skill's SKILL.md: it is the director's pass. Go through the transcript and write the director's plan, `work/<name>.director.md`: one row per graphic, timed to the word it lands on. The plan covers every graphic in the video: the templates, morph graphics and kinetic text below, and the cards you design for the moments none of them fits (a stat, key points, a term, a payoff). Show the plan and wait for the user's OK or changes, then build it. Write each card's motion with the numbers in the `cut-the-curve` skill.

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

- **One theme per video:** `apple` when the user asks for Apple style, clean, premium, minimal or keynote; `blueprint` for explainers, how-tos, money and business; `midnight` for everything else; `paper` when the user wants light or calm. The user's words win. Designed cards use the same theme.
- **Limits:** short videos get at most one flowchart. Templates and designed cards follow the director's density in `talking-head-recut` (about one graphic per 6 to 8 s in a short video, at least 0.5 s from one graphic's end to the next one's start). The profile table's spacing column is for morph graphics and check / X marks.
- **Spec:** write all templates into `work/<name>.templates.json`, with times from `W`, the speaker's own words shortened, and icons from the skill's list.
- **Windows:** note every template and card window `start` to `end`. Mark the cutaway ones (`flowchart`, `steps`, `compare`, `quote`, `chapter` and `title-card` unless set to overlay, and cards with `"mode": "cutaway"`), because nothing else may appear inside them.

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
- `--at` is the start of the first number word minus 0.2 s. For check / cross, start 0.6 s before the word that carries the verdict ("not" in "do not spend money", "right" in "this is the right way"), so the mark lands on it.
- `--duration` runs to the end of the sentence, between 2.5 and 4 s. If the sentence runs longer, stop at 4 s: a cutaway that holds the screen longer loses the speaker. Never run into the next graphic.
- Write the window `at` to `at + duration` for each graphic. Steps 6 and 7 use these windows.

**Kinetic text:**

```
PY K/find_emphasis.py V --words W --keywords "<names and key terms>" --skip "<windows>"   # plus --min-gap 15 for the long profile
```

`--skip` takes every template window and every morph window widened by 1 s on each side (`"0-3.2,3.2-27.6,9-14"`), so no moment lands inside one. Then edit `work/<V-stem>.emphasis.json`:
- Remove any moment repeating a number or words a graphic already shows.
- Fix misheard words. Keep 1 to 4 words, exactly as spoken.
- Keep only moments that carry the message.

**Text behind the speaker** (`text-behind` skill), decided together with kinetic text: at most 1 or 2 per short video, on the single biggest number or claim ("90 DAYS", "$10K", "FREE").
- Only when the head and shoulders are in frame with wall around the head and the speaker is still: no mic arm, held object or fast motion.
- Keep it out of every other graphic's window and at least 5 s from any kinetic-text moment, and drop that word from the kinetic plan. Pass its window to captions `--hide-during`.
- Each moment of about 2 s costs 0.5 to 2.5 minutes of background removal. The first run downloads a free 168 MB cutout model once.

```
PY .claude/skills/text-behind/scripts/build_behind.py V --plan work/<name>.behind.json --theme <theme> --out work/<name>.b.mp4   # V = work/<name>.b.mp4
```

## 6. Render, one pass at a time

Each pass reads the previous file in `work/`. Skip a pass with nothing to add. Run text behind the speaker first, on the clean cut video, so its cutout of the person never includes another graphic (its command is in step 5).

```
PY K/build_kinetic.py V --plan work/<V-stem>.emphasis.json --out work/<name>.k.mp4                     # V = work/<name>.k.mp4
PY M/build_morph.py --template circle-to-bars --title "Hours per video" --labels "Before,Now" --values "6,1" \
   --video V --at 2.9 --duration 3 --out work/<name>.m1.mp4                                            # V = work/<name>.m1.mp4
PY M/build_morph.py --template ring-to-number --values 87 --unit % --labels "of my editing done by AI" \
   --video V --at 8.2 --duration 2.6 --mode overlay --out work/<name>.m2.mp4                          # V = work/<name>.m2.mp4
```

Then the templates and designed cards, all in one pass (`T` = `.claude/skills/motion-templates/scripts`):

```
PY T/build_template.py work/<name>.templates.json --video V --theme blueprint --out work/<name>.t.mp4   # V = work/<name>.t.mp4
```

The examples are from a real test. Use the values from your own step 5. Each kinetic moment takes about 10 to 20 s to render and each graphic about 30 s, so run long videos in the background or with a 10-minute timeout. Add `--overwrite` when re-running.

## 6b. Sound effects

Put a sound on each graphic (`sound-effects` skill; `SFX` = `.claude/skills/sound-effects/scripts`). Skip it when there are no graphics or the user said no sounds.

```
PY SFX/suggest_sfx.py V --templates work/<name>.templates.json --emphasis work/<V-stem>.emphasis.json --morph "<morph windows>" --words W   # plus --per-minute 8 for the long profile
PY SFX/add_sfx.py V --plan work/<name>.sfx.json --out work/<name>.s.mp4                                                                    # V = work/<name>.s.mp4
```

Leave out the flags for plans that don't exist. Read the printed cues and drop any without a clear cause on screen. Check the add_sfx lines: true peak OK, change outside the cues about 0.00 dB, every cue within 1 frame. Captions copy the audio, so the sounds carry through to `output/`.

## 7. Captions last

```
PY C/make_captions.py V --words W --style <reel|clean> --hide-during "2.9-5.9,8.2-10.8" --plan-only
```

`--hide-during` takes the morph windows and the windows of cutaway templates and cutaway cards **except the flowchart**: captions step aside while a graphic is on screen and come back right after. Otherwise they cover the chart. A caption that runs into a window is shortened to end at its edge rather than dropped.

The flowchart keeps its bottom fifth free so captions continue under it, as in the reference reels. When a flowchart is in the video, add `--position bottom` so the captions sit there for the whole video. With the `blueprint` theme, use `--style hand`: handwriting with the spoken word lit up in blue. With the `apple` theme, use `--style apple --position bottom`: clean semibold sans with the spoken word lit up in blue, under the cards.

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
- `work/<name>.t.templates-check.png`: every template, including each flowchart box and the recap.
- `work/<V-stem>.captions-check.png`, which shows the final video and includes the frames around every graphic.

Make sure that:
- text is readable, nothing covers the face or mouth, and no two graphics overlap
- charts show the right numbers
- every spoken word is in the captions plan (`work/<V-stem>.captions.json`), apart from words hidden on purpose during a full-screen graphic. A caption left alone after a cutaway ("credit score") is fine: it is what's being said

The sheets can miss a moment, such as a kinetic word or a flowchart recap. Grab a frame of anything they miss: `ffmpeg -ss <time> -i output/<file> -frames:v 1 work/<name>-<time>.png`.

Fix and re-render the pass that's wrong. Don't hand over something you haven't looked at.

Report one row per video:

| Video | Length | Dead air | Mistakes | Templates and cards | Kinetic text | Graphics | Sounds | Captions |
|---|---|---|---|---|---|---|---|---|
| talk.mov | 0:30.7 → 0:15.6 | 9 cuts (tight) | 1 repeat | none (no process or list) | "waiting too long" 0:06.9, "let Claude" 0:13.1 | bars 6 → 1 at 0:02.9, ring 87% at 0:08.2 | 8 (whoosh ×3, pop ×2, ticks ×2, 1 impact) | reel |

Then:
1. The path in `output/`.
2. One line offering changes: fewer or more graphics, another caption style, put back a cut, a different chart, or tight / gentle pacing.

Each change re-runs only the passes from that point on, because every in-between file is still in `work/`.
