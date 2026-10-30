---
name: video-editor
description: Edit the user's videos in this folder. Raw footage is read from input/ and finished videos are written to output/. The main job is cutting dead air (silent pauses at the start, between sentences and at the end); it also trims, joins, reframes for TikTok/Reels/Shorts, adds captions, music, titles and other edits with FFmpeg, Python and HyperFrames. Use this skill whenever the user wants anything done to a video or recording, such as "edit my videos", "remove the silences / pauses / dead air", "make it tighter", "clean up this recording", "jump cuts", "trim the start", "add subtitles", "make a vertical version", or "process what's in input", even if they don't name a file or say "skill".
---

# Video editor

You are the editor. The user drops raw footage into `input/`; you deliver finished videos in `output/`. Unless they ask for something else, "edit my videos" means: cut the dead air out of every video in `input/`.

## The folder contract

| Folder | Holds | Rule |
|---|---|---|
| `input/` | the user's raw videos | Read only. Never edit, move, rename or delete anything here. It is often their only copy, and keeping it intact means any edit can be redone with different settings. |
| `output/` | finished videos | Only final results, named like the source (`talk.mov` becomes `output/talk.mp4`). |
| `work/` | scratch: intermediate files, reports | Use it for every in-between step so `output/` only ever holds finished work. Safe to clear. |

Run every command from the project folder (the one holding `input/` and `output/`).

## Step 0: make sure the tools are ready

The session-start hook prints a `[video-editor]` status line. If it said setup is incomplete, or you don't see one, check:

- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1 -Check`
- macOS / Linux: `bash setup.sh --check`

If something is missing, tell the user in one line what will be installed (portable copies inside this folder, nothing system-wide), then run the same command without the check flag. The first run takes a few minutes, so give it a 10-minute timeout or run it in the background. `README.md` has troubleshooting.

If the check script can't run (for example, the user declines the permission), confirm the two essentials directly instead: `tools/ffmpeg/bin/ffmpeg -version` (or `ffmpeg -version`) and `PY -c "import numpy"`. Dead-air cutting needs nothing else.

In the commands below, `PY` is the project's Python: `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS / Linux. `S` is `.claude/skills/video-editor/scripts`.

## Cutting dead air (the main job)

1. **See what's waiting.** List `input/`. If it's empty, ask the user to drop their videos there and stop. Videos that already have a finished copy in `output/` are skipped unless you pass `--overwrite`. Mention it if that applies.

2. **Preview the cuts.** This is fast and renders nothing:
   ```
   PY S/cut_dead_air.py --analyze
   ```
   For each file it prints the length before and after, how many cuts, the silence threshold it picked, and any warnings. Sanity-check before rendering:
   - Talking-head footage usually loses 5 to 35%. Much more than 50% is suspicious unless the recording really has long gaps.
   - A warning about quiet and loud parts being close together means background music or constant noise. Energy-based detection can't separate speech from music, so tell the user and either keep `gentle` or set a manual `--threshold` (a few dB above the noise floor it reports).

3. **Render.**
   ```
   PY S/cut_dead_air.py                      # every video in input/
   PY S/cut_dead_air.py input/talk.mov       # just one
   ```
   Rendering re-encodes the video so every cut is frame-accurate. It runs at roughly real-time speed or faster for 1080p, slower for 4K. Anything longer than a few minutes of footage should run in the background (or with a 10-minute timeout) so the command isn't cut off. The script prints progress every few seconds on long renders.

4. **Check the result.** The script verifies each output itself (length matches the plan, audio and video tracks present and in sync) and prints `OK` per file. A failed check leaves the file in `work/` and prints the reason; it never lands in `output/`. Details per video are in `work/reports/<name>.json` (every cut with timestamps).

5. **Report back** in this shape:

   | Video | Before | After | Removed |
   |---|---|---|---|
   | talk.mov | 10:32 | 8:02 | 2:30 (24%), 87 cuts |

   Then one line with the path(s) in `output/`, and one line offering adjustments: snappier (`tight`), more natural (`gentle`), or keep more air around words (`--padding 0.25`). Footage is something the user has to watch, so invite them to check the first one before you batch-process many.

### Presets and tuning

| Preset | Cuts pauses longer than | Air kept next to speech | Feel |
|---|---|---|---|
| `gentle` | 1.0 s | 0.30 s | natural; only long dead air goes |
| `normal` (default) | 0.6 s | 0.15 s | tidy, still conversational |
| `tight` | 0.35 s | 0.10 s | fast social-media jump cuts |

Fine-tune with `--min-silence SEC`, `--padding SEC` and `--threshold DB`, e.g. `--preset tight --padding 0.12`. Map the user's words onto these. "Too choppy" or "words cut off" means more padding or `gentle`. "Still slow" or "more energy" means `tight`. Re-run with `--overwrite` to replace a finished file. Other flags: `--suffix _cut` (keeps both versions), `--output-dir work` (for chaining), `--crf` (quality, default 18), `--speed` (encoder preset, default `fast`), `--json`.

What the script handles on its own, so you don't need to: the threshold adapts to each recording's own noise floor (quiet room or noisy room); word endings and quiet consonant releases are kept; tiny clicks don't count as speech; every join gets a few ms of audio fade so there are no pops; iPhone HDR footage stays HDR (HEVC 10-bit); odd frame sizes are fixed; audio-only files (`.mp3`, `.wav`, `.m4a`) come out in their own format; files without an audio track are skipped with a reason.

## Dedicated skills for bigger jobs

Hand off to these when the request matches. They follow the same input / work / output contract:
- **`captions`**: burned-in reel captions (playbook style), minimal one-word captions, or clean subtitles plus `.srt`.
- **`kinetic-text`**: kinetic typography only on the emphasized words, numbers and names, spaced out so it never clutters.
- **`morph-shapes`**: a circle that becomes a bar chart, donut, line chart, check / X, or counting ring. Use it as a cutaway or overlay at the moment the speaker says the number.
- **Herk Edit Kit:** `edit-video` (full edit), `short-form-edit` (reels), `cut-mistakes` (retakes and stutters), `video-storytelling`, `style-library`, `motion-showreel`, and the others listed in `CLAUDE.md`. `docs/EDITING-PLAYBOOK.md` explains how they're used together.

A typical full edit chains them: cut dead air → mistakes → kinetic text / morph graphics → captions last. Each step writes to `work/`, and only the last one writes to `output/`.

## Other edits

When the request goes beyond dead air, read the matching reference first:

- **Trim, join, reframe to 9:16, resize, compress, speed up, loudness, background music, logo, fades, GIFs, thumbnails, scene detection, Premiere/Resolve timeline export:** `references/editing-recipes.md` (tested FFmpeg commands that follow this folder's input/work/output layout).
- **Captions / subtitles:** `PY S/transcribe.py <video>` writes `output/<name>.srt` with short caption lines (local speech-to-text; the model downloads once). Burn them in or attach them with the recipes in `references/editing-recipes.md`.
- **Animated titles, intros, outros, lower thirds, kinetic text, motion graphics:** `references/hyperframes.md` (HyperFrames renders HTML to video).

**Chaining several edits** (e.g. cut dead air, make it vertical, add captions): each intermediate step writes to `work/`, and only the last step writes to `output/`. For example: `PY S/cut_dead_air.py input/talk.mov --output-dir work`, then reframe `work/talk.mp4` into `work/talk_vertical.mp4`, then caption that into `output/talk.mp4`. This keeps half-finished files out of `output/`, where the user would mistake them for the deliverable.

## Good habits

- Probe before you edit anything unusual: `ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate -of compact <file>`. FFmpeg and ffprobe live in `tools/ffmpeg/bin/` when setup installed them.
- You can't hear audio, but you can look at frames. To check a cut or a caption, grab a frame (`ffmpeg -ss 12 -i output/x.mp4 -frames:v 1 work/check.png`) and view it.
- Use relative paths inside FFmpeg filters (`subtitles=work/talk.srt`). Windows drive letters such as `C:` break filter arguments.
- If a tool is reported missing mid-task, run the setup check from Step 0 rather than installing things another way. Keeping every tool inside this folder is what lets the folder work the same on any machine.
