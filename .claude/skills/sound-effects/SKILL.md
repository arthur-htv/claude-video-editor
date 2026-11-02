---
name: sound-effects
description: Add free sound effects to a video's graphics so each one lands with the picture - a whoosh when a card or template enters, a pop when a pill, tag or count lands, a soft tick as a list line appears, one bass impact on the full-screen statement. It reads the graphics plans the edit already made, times each sound's peak one frame after its picture, sets levels against the speaker's voice, rotates takes and keeps it sparse, then mixes them in without changing the voice or re-encoding the picture. Free and local (21 Pixabay sounds that ship with HyperFrames). Use this whenever the user asks for sound effects, sfx, whooshes, pops, clicks, swooshes, "add sounds", "sound design", "make it punchier", "the graphics feel silent", or runs the automatic edit, even if they don't say "sound effects".
---

# Sound effects

Folder contract as in the `video-editor` skill: read from `input/` or `work/`, deliver to `output/`. `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. `SFX` = `.claude/skills/sound-effects/scripts`.

Graphics that appear without a sound feel unfinished, and the same whoosh on every card feels like a template. This skill puts a few exact sounds on the graphics already in the video: every sound has a cause on screen. It never generates or downloads anything. The only other sound-effect option in this folder, `motion-showreel/scripts/sfx.mjs`, calls ElevenLabs (paid, needs the user's OK); this one is free.

## When to use it

- After the graphics passes (templates, designed cards, morph charts, kinetic text), on talking-head videos. In `/video-editor:auto` it runs by default, after the graphics render and before captions.
- Skip it when the video has no graphics, when the user says "no sounds" / "keep it clean", or when the source already has sound design or music with hits on its graphics.

## Which sound for which motion

From `node_modules/hyperframes/dist/skills/media-use/audio/assets/sfx/manifest.json`. Peaks and levels were measured with FFmpeg (loudest 30 ms).

| Motion on screen | Sound (takes, rotated) | Level vs the voice | Peak in file |
|---|---|---|---|
| a card, template, flowchart box or chart enters | `whoosh-short` | -10 dB | 0.162 s |
| a pill, tag, sticker, chart shape or kinetic word pops in; a count lands on its number | `pop` | -9 dB | 0.131 s |
| a list line or item appears (steps, compare, a card's options, typewriter / highlight text) | `click-soft`, `key-press` | -12 dB | 0.063 s, 0.087 s |
| the save / follow button is tapped (a real tap on screen) | `click` | -10 dB | 0.063 s |
| the full-screen statement or payoff lands, **once per video** (the last one) | `impact-bass-1`, `impact-bass-2` | -6 dB | 0.087 s, 1.825 s |

Not used, and why:
- `whoosh.mp3` is byte for byte `whoosh-short.mp3`, and `click.mp3` is `click-soft.mp3`. Rotating between them would repeat the same sound, so a single-take sound comes back at 1.06x and then 0.94x speed instead (about a semitone up, then down).
- `riser` (10 s) and `whoosh-cinematic` (5.5 s) build for seconds under the voice. Also, the riser's loudest point is at 3.47 s, not at its end as the manifest says.
- `chime`, `notification`, `ping`, `sparkle`, `error`: synthesized tones and dings, which HeyGen's sound rules rule out.
- `glitch-1/2/3`: harsh, and wrong for a talking head. `typing`: a 1.5 s burst that runs under several words.

Any sound in the manifest can still go in a plan by hand.

## Timing

- **The peak lands one frame after its picture.** Light reaches the viewer before sound, so a sound one frame late feels right, and an early one feels wrong sooner than a late one. `at` in the plan is when the peak plays, and the mixer starts the file `peak offset / rate` earlier.
- **"Its picture" is the frame where the motion is 80% in.** That is what the eye reads as "it landed". For a card's GSAP line it comes from the ease: `power3.out` reaches 80% at 0.33 of its duration, `expo.out` at 0.23. A snapped count shows its last number once the tween passes N - 0.5 (for "10" that's 63% of a `power2.out` count, 0.5 s before the tween ends). Template entrances land about 0.13 s in, kinetic words 0.05 s before their spoken word, and morph charts 0.25 s after `--at`.
- Pure fades (opacity only) and `tl.to` lines get no sound, because nothing lands.

## Levels

These videos have a voice and usually no music, so levels are set against the **voice**: its loud syllables (the 90th percentile of 30 ms RMS while speaking). Each sound's loudest 30 ms sits 6 to 12 dB under them, by family.
- **Why under, not over:** HeyGen's rule puts hits 3 to 6 dB over a music bed, and that bed sits around 0.14 (-17 dB) under the voice. So the hits end up 11 to 14 dB under the voice. Their sfx engine's default (volume 0.35) is about -9 dB. Every word stays clear, and the hit still reads.
- **The impact goes louder (-6 dB):** most of its energy is under 150 Hz, which phone speakers barely play.
- **Ticks go quieter (-12 dB):** they are bright and sharp, so they cut through anyway.
- **In a cutaway, a cue on a spoken word plays 3 dB lower:** the face is off screen, so nobody can lip-read past a masked word. This needs `--words`.
- `--level +3` or `--level -3` moves everything. Map "punchier" or "louder sounds" to `+3`, and "subtle" to `-3`.

## Keeping it sparse

- **No stacking:** two hits less than 0.6 s apart become one, and the stronger family wins. The order of strength is impact, then whoosh, then pop, then tick and tap.
- **A cap per minute:** 15 by default, prorated under a minute (8 in a 33 s video). Use 8 for long videos. Each graphic's first hit is kept first, then the strongest of the rest, so a card's third tick never takes the only sound of another graphic. The printout names any graphic left without a sound ("No room left for a sound on ..."): raise `--per-minute`, or swap a cue by hand.
- **Rotation:** each family's takes rotate in time order, so no two cues in a row are identical.

## Commands

```
PY SFX/suggest_sfx.py V --templates work/<name>.templates.json [--emphasis work/<name>.emphasis.json] \
   [--morph "2.9-5.9,8.2-10.8"] [--words W] [--per-minute 15] [--level 0]      # writes work/<name>.sfx.json
PY SFX/add_sfx.py V --plan work/<name>.sfx.json --out work/<name>.s.mp4 [--hf-check]  # V = work/<name>.s.mp4
```

`suggest_sfx.py` prints each cue with its reason. Edit the plan freely: each cue is `{"at", "sound", "gain_db", "why"}`, plus an optional `"rate"`. You can drop a cue, move `at`, or change `gain_db`.

`add_sfx.py` mixes every cue in one FFmpeg pass. Each cue is delayed to the sample (`adelay`), set to its gain, and summed with `amix normalize=0`, so the voice keeps its exact level. The picture is copied (`-c:v copy`). Then it measures, and writes `work/<name>.s.sfx-report.json`:
- loudness and true peak before and after
- where each cue's peak really landed, in frames, found by subtracting the source from the result
- how much the audio changed outside the cues (it should be about 0.00 dB, which is codec noise)
- If the mix would peak over -1 dBTP (or over the source's own peak, if that is higher), it lowers every cue and mixes again until it fits.

`--hf-check` also runs `npx hyperframes audio <out> --json --quality local` (through `hf.py`). It runs only on this machine. Never use `--quality best`: it uploads to HeyGen and may bill.

You can't hear the result, so report it as measured, not heard: the cue table, the loudness before and after, and the timing check. Offer the user "louder / quieter / fewer sounds / drop one".

## In `/video-editor:auto`

The step goes after the templates-and-cards render and before captions:
- **No extra encode either way.** Captions only change the picture and copy the audio (`-c:a copy`), and this step copies the picture.
- **Captions stay last.** They remain the only step that writes to `output/`.
- **The times are final.** The graphics plans it reads are already settled when this step runs.

## Licence

The sounds come from Pixabay, under the Pixabay Content License (`CREDITS.md` next to them). They are free to use, commercial or not, with no attribution, and can be modified. They may be passed on only inside a derivative work, such as a finished video. Passing on the files themselves, unchanged, is not allowed.

So this skill reads them from `node_modules` at run time, and `npm install` in the setup fetches them with HyperFrames. **Never copy the mp3s into this repo** or any folder that gets shared. Videos made with them can be published freely. If `node_modules` is missing, both scripts stop and point to the setup.
