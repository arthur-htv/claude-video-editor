# Claude Video Editor

Turn Claude Code into your video editor. Drop raw videos into `input/`, ask Claude to edit them, and collect the finished videos from `output/`.

Out of the box it **cuts the dead air** (the silent pauses at the start, between sentences and at the end of a recording). It can also trim, join, make vertical versions for TikTok / Reels / Shorts, add captions, background music, logos, animated titles and more.

Everything runs on your own computer with free tools. Your videos are never uploaded anywhere.

---

## Quick start

1. **Get the folder:** clone it from GitHub or download it as a ZIP and unzip it.
2. **Open the folder in Claude Code** and trust it when asked.
3. **Say "set up this folder".** Claude reads this guide and installs the tools (one time, a few minutes).
4. **Put your raw videos in `input/`.**
5. **Say "edit my videos".** The finished videos appear in `output/`.

The rest of this guide explains each step in detail.

---

## Step-by-step guide

### Step 1: Get the folder

- **With git:** `git clone https://github.com/arthur-htv/claude-video-editor.git`
- **Without git:** on the GitHub page click **Code > Download ZIP**, then unzip it somewhere easy to find, such as `Documents/claude-video-editor`.

Keep the folder name free of special characters. Spaces are fine. On Windows, keep the path short (for example `Documents\claude-video-editor`), because Windows limits file paths to 260 characters and the Python libraries are nested deeply.

### Step 2: Open it in Claude Code

- **VS Code:** File > Open Folder, choose `claude-video-editor`, then open the Claude Code panel.
- **Terminal:** `cd claude-video-editor`, then `claude`.

When Claude Code asks whether you trust this folder, choose **Yes**. That lets the folder's start-up check run. Every time a session starts, it tells Claude whether the tools are installed and how many videos are waiting in `input/`.

Open this folder itself, not a folder above it. The setup check, the instructions for Claude (`CLAUDE.md`) and the `video-editor` skill all live inside it.

### Step 3: Install the tools (one time)

**Easiest:** tell Claude "set up this folder". It reads this guide, tells you what it will install, and runs the setup for you.

**Or run the setup yourself:**

| Your computer | How to run the setup |
|---|---|
| Windows | Double-click `setup.cmd`, or in PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1` |
| macOS / Linux | In a terminal inside the folder: `bash setup.sh` |

What the setup does:

| Tool | What it's for | Where it comes from |
|---|---|---|
| FFmpeg + ffprobe | cutting, encoding, every video operation | already on your computer, otherwise a portable copy in `tools/ffmpeg` |
| Node.js 22 or newer | runs HyperFrames | already on your computer, otherwise a portable copy in `tools/node` |
| Python 3.12 | runs the editing scripts | already on your computer, otherwise a portable copy in `tools/python` (installed with `uv`, a small Python installer, in `tools/uv`) |
| Python environment `.venv` | this folder's own Python libraries | created in `.venv/` |
| Python libraries | numpy, moviepy, faster-whisper (captions), scenedetect, opencv, auto-editor | installed into `.venv/` from `requirements.txt` |
| HyperFrames | animated titles and motion graphics from HTML | installed into `node_modules/` from `package.json`, plus the headless Chrome it renders with (in your user cache) |

Good to know:

- **Nothing is installed system-wide and no admin rights are needed.** Whatever is missing goes inside this folder.
- Every download is checked against its published checksum before it is used.
- The first run downloads about 1 GB and takes 3 to 5 minutes. Running the setup again is safe and quick: finished steps are skipped.
- Disk space: plan for about 5 GB. The first time you make captions, the speech model adds about 0.5 GB, and the first automatic edit adds the larger re-listen model, about 3 GB (both in `tools/models/`). `tools/uv-cache/` is only a download cache: deleting it frees space and doesn't break anything.
- **Check what's installed** without changing anything: `setup.ps1 -Check` (Windows) or `bash setup.sh --check` (macOS / Linux).
- Want everything self-contained even though your computer already has some of these tools? Add `-ForcePortable` (Windows) or `--force-portable` (macOS / Linux).

### Step 4: Add your raw videos

Copy (don't move) your recordings into `input/`. Supported: `.mp4 .mov .m4v .mkv .avi .webm .mts .wmv` and more. Audio files work too: `.mp3 .wav .m4a .flac`.

Files in `input/` are never changed, moved or deleted. They stay your originals, so you can always redo an edit with different settings.

### Step 5: Ask Claude to edit

Just say what you want. For example:

- "edit my videos" (cuts the dead air out of everything in `input/`)
- "remove the pauses from talk.mov"
- "make it tighter, it's for TikTok"
- "only cut the long pauses, keep it natural"

Claude uses the `video-editor` skill. You can also call it directly by typing `/video-editor`. It previews the cuts first, renders, checks every result (length, audio and video in sync) and then reports back with a short table like this:

| Video | Before | After | Removed |
|---|---|---|---|
| talk.mov | 10:32 | 8:02 | 2:30 (24%), 87 cuts |

Long videos take a while: rendering runs at roughly real-time speed or faster for 1080p, slower for 4K.

**Let Claude pick the effects (automatic edit).** Type `/video-editor:auto` (or say "auto edit", "do everything", "make it engaging"). For each video, Claude:

1. cuts the dead air
2. transcribes it and reads what you say
3. cuts repeated phrases and retakes, then listens to every cut again to make sure no word was clipped
4. sets your voice to the level the apps play speech at
5. punches in on the jump cuts (short and medium videos)
6. turns the numbers you mention into morphing charts (bar chart for a comparison, counting ring for a percentage, check / X for a verdict)
7. adds templates where they fit:
   - a flowchart explainer that builds itself while you walk through a process
   - numbered steps for tips
   - a comparison for this vs that
   - a hook title at the start
   - a save / follow card at the end
8. puts kinetic text on the words you stress
9. adds captions last, keeping them off the graphics

It then runs a graphics check (fonts, face, captions, spacing), has a fresh pair of eyes look at the check frames once, and reports what it added and where. If a session ends half way, say "continue the edit": Claude picks up from the last finished step. Add notes after the command, e.g. `/video-editor:auto talk.mov no captions` or `/video-editor:auto keywords: Claude, 10x`.

How much it adds depends on the video:
- **Vertical or under 90 s:** tight cuts, punch-ins on the cuts, and captions in the theme's style.
- **Long horizontal videos:** fewer graphics, plus clean subtitles and an `.srt` file.

It never invents a number: no numbers spoken means no charts.

**Or just name the effects.** One keyword is enough, and Claude runs them in the right order:
- "captions"
- "highlights" or "pop" for kinetic text
- "chart the numbers"
- "remove the retakes"
- "captions and highlights"

Each step takes time. On a 30-second test clip, rendering took about 2 minutes, and the whole automatic edit (with Claude reading, deciding and checking frames) took about 8 minutes.

### Step 6: Get your finished videos

Finished videos are in `output/`, with the same name as the original (`input/talk.mov` becomes `output/talk.mp4`). They are H.264 MP4 files that play and upload everywhere. iPhone HDR footage stays HDR (HEVC 10-bit).

Videos that already have a finished copy in `output/` are skipped next time. Ask Claude to "redo it" to replace one.

The `work/` folder holds scratch files and a report per video (`work/reports/<name>.json`, listing every cut with timestamps). You can empty it at any time.

### Step 7: Adjust the result

Watch the first video, then tell Claude what to change:

| You say | Claude uses | Effect |
|---|---|---|
| "keep it natural", "too choppy" | `gentle` | cuts only pauses longer than 1 second, keeps 0.3 s of air |
| (default) | `normal` | cuts pauses longer than 0.6 s, keeps 0.15 s of air |
| "tighter", "snappier", "for TikTok" | `tight` | cuts pauses longer than 0.35 s, keeps 0.1 s of air |
| "words are getting cut off" | more padding | keeps more air around every word |
| "gentler punch-ins", "no zooms" | punch-ins at 108%, or none | the framing changes less on each cut, or not at all |
| "put that cut back", "cut that part too", "make it tighter" after the graphics | the re-cut, then `retime.py` | the graphics, sounds and captions move with the cut and stay on their words |

The silence level adapts to each recording, so quiet rooms and noisy rooms both work. One limit: background music under the voice makes pauses hard to detect (music is never silent). Claude warns you when it sees that.

### Step 8: More edits

Combine requests freely. Claude does each step in `work/` and puts only the final file in `output/`.

- "add captions" (local speech-to-text, burned into the video or as an `.srt` file)
- "make a vertical 9:16 version for Reels"
- "add music.mp3 from input as background music, quieter when I talk"
- "put my logo.png in the top-right corner"
- "make a 3-second animated intro that says Episode 12 and put it at the start"
- "speed it up 1.2x", "make the volume consistent", "compress it for WhatsApp"
- "make a GIF of the first 3 seconds", "grab a thumbnail at 0:05"
- "export a Premiere timeline instead so I can fine-tune the cuts myself"

---

## All the skills, and when each one is used

Claude picks the right skill from what you ask. You can also call one by name (type `/` plus the name, e.g. `/captions`).

| Skill | Use it for | Try saying |
|---|---|---|
| `/video-editor:auto` | The automatic edit: scans each video and adds what fits (dead-air cut, retake cuts, voice level, punch-ins on the cuts, morph charts, kinetic text, captions), then checks the graphics | "auto edit", "do everything", "make it engaging" |
| `video-editor` | Cutting dead air, plus everyday edits: trim, join, vertical, music, logo, compress. Also turns single keywords ("captions", "highlights", "chart") into the right skills. | "edit my videos", "make it tighter" |
| `captions` | Burned-in captions in the playbook's reel style (1-3 words, dark box, colored keywords, never over the mouth), one-word captions, or clean subtitles + `.srt` | "add captions", "subtitles for YouTube" |
| `kinetic-text` | Animated text only on the words you stress, numbers and names (pop, slam, typewriter, highlight, stack), spaced out so there's no clutter | "make the key points pop", "add kinetic typing on the important words" |
| `morph-shapes` | A circle that becomes a bar chart, donut, line chart, check / X, or counting ring | "show 6 hours vs 1 hour as a chart at 0:12", "add a checkmark when I say approved" |
| `motion-templates` | A template library in 4 themes: **blueprint** (dark graph paper, glowing blue, handwriting), **midnight** (black, bold, teal), **paper** (light, serif) and **apple** (black, Inter, blue accent, glass panels). It has 12 templates: a flowchart explainer (boxes appear as you explain, the camera follows, then zooms out to the whole map), steps, compare, quote, chapter, hook title, label tags, a save / follow end card, `card` for cards designed by hand, and three adapted from HeyGen's free HyperFrames library: lower thirds (a clean name bar and three bare styles), calm Apple-like title cards, and hand-drawn circles and underlines. | "make a flowchart of the steps", "add a hook title and a save card", "put my name and title on screen", "circle the card in my hand", "use the paper theme" |
| `talking-head-recut` | The director's pass. Claude reads what you say, plans a graphic for each moment worth one (a stat, key points, a term, a payoff, a full-screen statement), timed to the word, shows you the plan, then designs each card and renders it over your untouched video. Apple-style look built in. It is the graphics step of `/video-editor:auto`. Adapted from HeyGen's retired HyperFrames skill of the same name. | "direct the edit", "Apple-style clean graphics", "design cards for the key points", "the templates look generic" |
| `text-behind` | One big word or number placed behind you, with you cut out in front of it. Runs locally (HyperFrames background removal, free model). Slow, so 1 or 2 short moments per video. | "put 90 DAYS behind me", "text behind my head" |
| `cut-the-curve` | Exact timing and easing numbers for every animation (card entrances, hook titles, pop-up words, camera moves, payoffs), so "Apple-smooth" looks the same everywhere. Adapted from HeyGen's HyperFrames skill of the same name. | "make it smoother", "too bouncy", "feels cheap", "Apple-like motion" |
| `sound-effects` | Free sound effects on your graphics: a whoosh when a card enters, a pop when a number lands, a soft click per list line, one bass hit on the big statement. Each lands one frame after its picture, sits under your voice, and never repeats the exact same take. Uses the free Pixabay sounds that come with HyperFrames; nothing is uploaded. | "add sound effects", "make it punchier", "add whooshes" |
| `edit-video` | Herk Edit Kit: the full talking-head edit (transcript, silences, mistakes, story, motion graphics, verified render) | "use edit-video on input/raw.mp4" |
| `short-form-edit` | Herk Edit Kit: reels, Shorts and short ads with a hook, captions, B-roll and sound | "turn input/raw.mp4 into a 9:16 reel" |
| `cut-silences`, `cut-mistakes` | Herk Edit Kit: transcript-driven silence cuts, then a reviewed list of retakes, stutters and false starts | "remove my retakes and stutters" |
| `video-storytelling`, `hyperframes-video-beats` | Herk Edit Kit: the visual story arc, glass cards, paper takeovers, callbacks | "plan the motion graphics for this video" |
| `style-library` | Herk Edit Kit: 406 ready-made motion-graphic cards in two styles (Vox-like explainer, Kallaway-like) | "use a stat card from the style library" |
| `motion-showreel`, `make-a-video`, `website-to-hyperframes` | Herk Edit Kit: showreels cut to music, videos from a brief, videos from a website | "make a 15-second showreel" |
| `hyperframes`, `hyperframes-cli`, `hyperframes-registry`, `gsap` | Rules and commands for HTML-to-video animation (used by the skills above) | (used automatically) |

How Nate's videos are edited with these skills (the order, the numbers, the caption and B-roll rules, the lessons) is in **[docs/EDITING-PLAYBOOK.md](docs/EDITING-PLAYBOOK.md)**. The motion vocabulary is in **[MOTION_PHILOSOPHY.md](MOTION_PHILOSOPHY.md)**, the card library rules in **[style-library/GUIDE.md](style-library/GUIDE.md)**, and the kit's own workspace guide in **[AGENTS.md](AGENTS.md)**. Step-by-step kit workflows: [docs/WORKFLOW.md](docs/WORKFLOW.md), [docs/SHORT-FORM.md](docs/SHORT-FORM.md), [docs/PROMPTS.md](docs/PROMPTS.md).

### A full edit, in order

`/video-editor:auto` does all of this by itself. To steer each step yourself:

1. "Cut the dead air" (`video-editor`), or for a reel "use short-form-edit".
2. "Show me the retakes and stutters to cut" (`cut-mistakes`). You approve each cut. Then "re-listen to the cuts" (`video-editor`): every join is heard again, so no word is clipped.
3. "Even out the volume" (`video-editor`): your voice goes to -14 LUFS.
4. "Punch in on the jump cuts" (`video-editor`): the framing switches between full and 112% at each cut.
5. "Make a flowchart of the steps" or "add a hook title" (`motion-templates`), "make the key points pop" (`kinetic-text`), and "show the numbers as charts" (`morph-shapes`).
6. "Add captions" (`captions`). Captions go last, so they match the final timing.
7. "Check the graphics" (`video-editor`): fonts, face, captions and spacing.

Each step saves to `work/`; only the finished video lands in `output/`.

### The Herk Edit Kit

The kit's skills, tools, style library and docs were copied from [github.com/nateherkai/herk-edit-kit](https://github.com/nateherkai/herk-edit-kit) (MIT, by Nate Herk; the bundled HyperFrames skills are Apache-2.0 by HeyGen). Licenses and notices are in `licenses/`. Changes made for this folder:

- **Transcription is local and free.** The kit defaults to ElevenLabs, a paid upload. Here `transcribe.py --json` produces the transcript format the kit tools read. ElevenLabs, Kie.ai and other paid services still work if you add your key to `.env` (copy `.env.example`), and Claude asks before any paid call or upload.
- **HyperFrames runs with telemetry off,** and without installing extra skills into your user profile.
- **Small safety fixes:**
  - The music and sound tools read only this folder's `.env`, not one in a parent folder.
  - The silence cutter refuses to write over its source.
  - The ElevenLabs helper keeps its temporary audio in the system temp folder.
  - The review server shares only the project's assets folder.
- **Not copied:**
  - the example videos (111 MB)
  - the 12 teaching projects (284 MB) and the legacy `short-form-video` skill that maintains them
  - the AI Automation Society brand files, which aren't licensed for reuse
  - the Codex copy of the skills

Kit workflows keep each edit in `video-projects/<name>/` (created with `npm run new-video -- <name>`). Raw footage still comes from `input/`, and the finished video is copied to `output/`. Library cards load GSAP and Google Fonts from the internet, so rendering them needs a connection.

## Using the tools without Claude

Run these from the project folder. The project's Python is `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` on macOS / Linux (written as `python` below).

```
python .claude/skills/video-editor/scripts/cut_dead_air.py                 # all videos in input/
python .claude/skills/video-editor/scripts/cut_dead_air.py --analyze       # preview only
python .claude/skills/video-editor/scripts/cut_dead_air.py --preset tight input/talk.mov
python .claude/skills/video-editor/scripts/cut_dead_air.py --help          # every option
python .claude/skills/video-editor/scripts/transcribe.py output/talk.mp4   # captions -> output/talk.srt
python .claude/skills/video-editor/scripts/relisten.py work/talk.clean.mp4 --words work/talk.mistakes-transcript.json   # re-hear every join
python .claude/skills/video-editor/scripts/voice_level.py work/talk.mp4 --out output/talk.mp4   # voice to -14 LUFS, peaks at or under -2 dBTP (add --overwrite to redo)
python .claude/skills/video-editor/scripts/punch_in.py work/talk.mp4 --name talk   # punch-ins on the jump cuts -> work/talk.p.mp4
python .claude/skills/video-editor/scripts/qa_graphics.py talk   # check the graphics: fonts, face, captions, spacing (add --platform reels only for an ad on that app)
python .claude/skills/video-editor/scripts/hf.py doctor                    # HyperFrames health check
python .claude/skills/captions/scripts/make_captions.py work/talk.mp4      # reel captions -> output/talk.mp4
python .claude/skills/kinetic-text/scripts/find_emphasis.py work/talk.mp4  # pick emphasis moments
python .claude/skills/kinetic-text/scripts/build_kinetic.py work/talk.mp4 --plan work/talk.emphasis.json
python .claude/skills/morph-shapes/scripts/build_morph.py --template circle-to-bars --labels "Before,After" --values "6,1"
npm test                                                                    # Herk Edit Kit self-tests
```

FFmpeg is in `tools/ffmpeg/bin/` when the setup installed it. The FFmpeg commands Claude uses are in `.claude/skills/video-editor/references/editing-recipes.md`.

---

## What's in the folder

```
claude-video-editor/
├── input/                 your raw videos (never changed)
├── output/                finished videos
├── work/                  scratch files, reports and each edit's run file (safe to empty)
├── README.md              this guide
├── CLAUDE.md              instructions Claude reads at the start of every session
├── AGENTS.md, MOTION_PHILOSOPHY.md   Herk Edit Kit workspace guide and motion rules
├── docs/                  EDITING-PLAYBOOK.md and the other Herk Edit Kit guides
├── style-library/         406 motion-graphic cards (GUIDE.md explains them)
├── style-templates/       two whole-scene templates
├── scripts/               Herk Edit Kit tools (preflight, beat sync, EDL review, ...)
├── examples/, tests/      small fixtures and the kit's self-tests (npm test)
├── licenses/              licenses and notices for the bundled kit, fonts are in the skill folder
├── setup.ps1, setup.cmd   setup for Windows
├── setup.sh               setup for macOS / Linux
├── requirements.txt       Python libraries
├── package.json           Node.js tools (HyperFrames, GSAP) and kit commands
├── .env.example           optional API keys for paid services (copy to .env)
├── .claude/
│   ├── settings.json      runs the start-up check
│   ├── hooks/session-start.sh
│   ├── commands/video-editor/auto.md   the /video-editor:auto command
│   └── skills/
│       ├── video-editor/  dead air, everyday edits, keyword map and the automatic edit (references/auto-edit.md)
│       ├── captions/, kinetic-text/, morph-shapes/
│       ├── motion-templates/  12 templates (incl. hand-designed cards, lower thirds and title cards), 4 themes, 157 Lucide icons (ISC)
│       ├── talking-head-recut/  the director's pass: plan, approve, design cards (adapted from HyperFrames)
│       ├── text-behind/       one big word behind the speaker, with a local cutout
│       ├── cut-the-curve/     exact motion timing and easing (adapted from HyperFrames)
│       ├── sound-effects/     free sound effects timed to the graphics (sounds read from node_modules)
│       └── edit-video/, short-form-edit/, cut-silences/, cut-mistakes/, ... (Herk Edit Kit)
├── video-projects/        Herk Edit Kit working folders (created when used)
├── tools/                 portable programs (created by setup)
├── .venv/                 Python environment (created by setup)
└── node_modules/          HyperFrames (created by setup)
```

## How it works

- **`CLAUDE.md`** is read by Claude at the start of every session. It says: read this README, make sure the tools are installed, then use the `video-editor` skill.
- **The start-up check** (`.claude/hooks/session-start.sh`) runs when a session starts. It tells Claude whether setup is complete and how many videos are waiting, and puts this folder's tools (`ffmpeg`, `python`, `hyperframes`) first on Claude's command path. It never installs anything by itself.
- **The `video-editor` skill** (`.claude/skills/video-editor/`) holds the editing know-how: the input / output rules, the dead-air workflow, tested FFmpeg recipes and HyperFrames notes. It travels with the folder, so anyone who clones it gets the same skill. It only shows up when Claude Code is opened in this folder.
- **The dead-air cutter** measures loudness every 10 ms, sets the silence level from each recording's own noise floor, keeps the quiet starts and endings of words, and renders frame-accurate cuts with tiny audio fades so the joins don't pop. Every result is checked before it is moved to `output/`.

## Sharing it on GitHub

This folder is public at https://github.com/arthur-htv/claude-video-editor.

**License:** the setup, the `video-editor`, `captions`, `kinetic-text` and `morph-shapes` skills and this guide are MIT (see `LICENSE`). The bundled Herk Edit Kit, HyperFrames skills and fonts keep their own licenses, listed in `licenses/` and the skill folders. Parts adapted from HeyGen's HyperFrames (Apache-2.0) carry a NOTICE in their folder: `talking-head-recut`, `cut-the-curve`, `text-behind`, the hyperframes skills, and the registry looks in `motion-templates/assets/registry/`. The sound effects stay in `node_modules` and are never committed: their Pixabay license allows them in your videos but not shared on their own.

The `.gitignore` already keeps the big and personal things out of git: `tools/`, `.venv/`, `node_modules/`, `work/`, `video-projects/`, `.env`, and the contents of `input/` and `output/`. Only the setup scripts, the guides, the skills and the style library get shared, about 2.5 MB. Anyone who clones the folder runs the setup once (Step 3) and has the same editor.

Before you push changes, run `git status` and check that no video, API key or `.env` file is listed.

## Troubleshooting

| Problem | Fix |
|---|---|
| Windows: "running scripts is disabled on this system" | Use `setup.cmd`, or the full command `powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1`. |
| The setup stopped with a download error | Usually a network hiccup or a firewall. Run the setup again; finished steps are skipped. |
| "checksum mismatch" | The download was damaged. Run the setup again. If it keeps happening, your network may be altering downloads (some company proxies do). |
| `text-behind` fails on its first run | The first run downloads a free cutout model (168 MB) and a runtime (214 MB) into `~/.cache/hyperframes`, which needs internet once (about 3 minutes). Check the connection and run it again. Nothing is uploaded. |
| "sound effects not found" | They come with HyperFrames in `node_modules`. Run the setup again. |
| Antivirus removed `ffmpeg.exe` | Allow the `tools` folder in your antivirus, then run the setup again. |
| Windows: "Importing the numpy C-extensions failed" or other DLL load errors | The folder sits too deep: Windows has a 260-character path limit and some library files are nested deeply. Move the folder somewhere short, such as `Documents\claude-video-editor`, and run the setup again. |
| Linux: setup asks for `curl` or `xz` | `sudo apt install curl xz-utils` (Debian / Ubuntu), then run the setup again. |
| Linux: "Scene detection is unavailable" | Scene detection is optional. To enable it: `sudo apt install libgl1 libglib2.0-0`. Everything else works without it. |
| Claude doesn't mention the setup status at the start | The start-up check needs the folder to be trusted, and on Windows it needs Git for Windows (which Claude Code uses anyway). Without it, Claude still follows `CLAUDE.md`; you can also say "check the setup". |
| You moved or renamed the folder | Run the setup again. It notices the Python environment points to the old place and rebuilds it. |
| Words are cut off | Ask for "more natural" (`gentle`) or "more padding". |
| Hardly anything was cut | The video may have background music or constant noise, or few real pauses. Claude reports the noise level and can set the silence level by hand. |
| A long video stopped halfway | Ask Claude to run it in the background; very long renders can outlast a single command. |
| A new session started the edit over, or doesn't know where it stopped | Say "continue the edit". Claude reads `work/<name>.run.json` and carries on from the first unfinished step. Emptying `work/` deletes it, so the next edit starts from the beginning. |
| Claude says the source changed since the run started | The video in `input/` was replaced by another one with the same name. Claude starts that edit over, so nothing from the old video is reused. |
| "cutting the mistakes failed" when cutting mistakes | Read the line above it. If it says "The project's Python (.venv) was not found", run the setup again. The last cut list is left as it was. |
| An approved mistake cut was "left out" | It sat inside a word that is mostly kept. Widen it to the whole word (from that word's start to the next word's start), or drop it. |
| "no quiet point between the words" when cutting mistakes | The words there run together, so that cut keeps the edges you approved instead of moving to a quiet spot. The re-listen step checks that join. |
| "note: reports/<name>.json could not be read" when cutting mistakes | The dead-air report next to the video is damaged. Run the dead-air step again with `--overwrite` (without it, the step keeps the video it already made and leaves the report as it is), then the mistake step. |
| A few frames of a removed take show right after a jump cut | A dead-air run that failed after the dead-air render replaced the report the mistake step reads. Run the dead-air render again with `--overwrite`, then the mistake step. |
| "WARNING: the cut video is N ms longer/shorter than the kept pieces" when cutting mistakes | Rare. The cut is still usable, but graphics timed from it may be off by that much. Note which clip it was. |
| The re-listen step lists a problem at a join | A cut goes through a word, or left part of a cut word in. Ask Claude to move that cut once, or to put it back. If it is still flagged after one move, it stays and the report names it. |
| The re-listen step prints "Notes, nothing to change" | The speech model heard a word differently next to a cut, but the cut does not touch that word. Nothing to do. |
| The re-listen step says "unheard" at a join | The speech model heard nothing there, so that join was not checked. Run it again; if it stays, listen to that join yourself. |
| The voice level says MISSED | Reaching -14 LUFS would have made the limiter take more than 5 dB off the whole voice, which flattens it (common with computer voices). It stops lower and prints the level it reached. Accept that level with the `--target` it suggests, or ask Claude to leave the volume as it was. |
| Punch-ins stop with "This video is as long as the dead-air cut" | A mistake list from an earlier run is still in `work/`. Run punch-ins on the video made from the mistake cut (`work/<name>.v.mp4`, or `work/<name>.clean.mp4` if the voice level was skipped). If step 4 cut nothing this time, move `work/<name>.mistakes-edl.json` out of `work/` instead. |
| The graphics check says a font isn't bundled | The card asks for a font this folder doesn't ship, before any bundled one, so the render quietly used another. Put Inter, Montserrat XB, Abril Fatface or Architects Daughter first in the list. |
| The graphics check fails every caption with `--platform` | The apps' ad safe zones keep the bottom 35% of the frame clear, and bottom captions sit at 78%. For an organic post, leave out `--platform`. To follow the zones, move the captions up with `make_captions.py --position 0.6`. TikTok's buttons also cover the right side of the frame from 44% of the height down, so a caption line wider than about 44% of the frame fails there at any height: for TikTok, also add `--scale 0.65`. |
| The graphics check says "has no rendered clip" | The plan changed after the render (a new start time or title). Render that pass again with `--overwrite`. |
| The graphics check says a clip "can't be read" | That render stopped part way and left an empty or broken file. Render that pass again with `--overwrite`. |
| The graphics check notes a morph graphic was checked for timing only | No morph clip of that length was rendered for this video after its dead-air cut, or there are fewer clips than morph graphics and their names don't say which is which. Render the missing morph graphic again. |
| The graphics check stops with "isn't valid JSON" | A plan was damaged by a hand edit. The message names the file: fix it, or make it again with the step that wrote it. |
| "The mistake cuts were made on a ... dead-air cut" when the plans move | You changed the pacing after cutting mistakes, so those cuts are timed on the old dead-air cut. Ask Claude to run the transcription and mistakes steps again, then move the plans. |
| "nothing to move" right after you changed the cut | The re-cut didn't happen: the dead-air step keeps a video it already made unless it gets `--overwrite`. Ask Claude to redo the re-cut with `--overwrite`, then move the plans. |
| "The plans in work/ are timed on the cut saved in ..." | The cut was saved again after it changed. Ask Claude to move the plans (`retime.py <name>`) instead. To plan the graphics again from scratch, delete `work/<name>.cutmap.json` first. |
| "kinetic text ... now runs over words put back" | A cut you put back sits inside a kinetic text or text-behind moment, so its words are now said under it. Look at that moment and shorten or re-plan it if the repeat shows. |
| HyperFrames render fails | Run `python .claude/skills/video-editor/scripts/hf.py doctor`. Rendering titles needs an internet connection (the animation library loads from a CDN). On Linux, the headless Chrome may need extra system libraries; `doctor` lists them. |
| Start over completely | Delete `tools/`, `.venv/` and `node_modules/`, then run the setup again. |

## Removing it

Delete the folder. Two things HyperFrames keeps outside the folder, which you can also delete:

- its headless Chrome, in `~/.cache/hyperframes` (Windows: `C:\Users\<you>\.cache\hyperframes`)
- its own Claude skills (`hyperframes`, `hyperframes-cli`, `hyperframes-registry`, `media-use`), in `~/.claude/skills` and `~/.agents/skills`. These appear only if HyperFrames was ever run outside this folder's tools: this folder turns that install off and already contains the first three (`media-use` is not included).

## Changelog

- **2026-11-02 (a sturdier automatic edit):**
  - Mistake cuts (`cut-mistakes`, step 4 of `/video-editor:auto`) now join as cleanly as dead-air cuts. Each edge is measured on the waveform and lands on the quietest frame near the word, never inside a word you keep. When the words run together and the quietest point is inside the word being cut, the cut keeps the edges you approved and says so. The frames are read from the video file itself, so phone clips with a variable frame rate, and clips whose picture starts a moment after the sound, stay frame-exact too. When a dead-air cut sits in the same pause, the edge moves onto it, even when the transcript puts the next word a hair before it, so no frame of the removed take flashes between two jump cuts. Every join gets a short fade, and the video goes through the same encoder and length check as the dead-air cut (HDR stays HDR). The saved timings match the finished file to the frame. The dead-air report (`work/reports/<name>.json`, and `--json`) now saves its cut times to 9 decimals instead of 3, so the two cut lists line up exactly.
  - New re-listen step (`relisten.py`, step 4b). After the last cut, the `large-v3` speech model hears about 1.5 s on each side of every join, and also the same places in the uncut video. It hears only around the joins, but on a video cut every few seconds that is most of it: a 48 s clip with 14 joins took about 7 minutes. It lists a word as a problem only when the cut goes through it, leaves part of a cut word in, or adds a word on real sound. Other differences are notes that need no change. Problems are fixed or reported before the graphics. Check it with `.venv/Scripts/python .claude/skills/video-editor/scripts/relisten.py --self-test` (1 s) or `.venv/Scripts/python tests/test_relisten.py` (a few minutes, Windows).
  - New voice-level step (`voice_level.py`, step 4c): your voice is set to -14 LUFS with one fixed gain, so nothing swells up in the pauses, and a limiter keeps the peaks at or under -2 dBTP so the sound effects still fit. One loud pop doesn't hold the whole voice down: it stops short, and says MISSED, only when reaching -14 would flatten the voice. A voice recorded on one side only now plays on both. The picture is copied, not re-encoded. The volume recipe now uses it instead of one-pass `loudnorm`.
  - New punch-ins on jump cuts (`punch_in.py`, step 4d). At each cut the picture switches between full and 112%, centred on your face and never cropping it, and each framing stays on screen at least 2 s. Each switch lands on the exact frame of its cut, phone videos included. If the saved cut lists don't fit the video, it stops and says why instead of guessing. The picture is encoded once and the sound is copied untouched. It's on for short and medium videos; say "keep it natural" or "no zooms" to turn it off. Check with `.venv/Scripts/python .claude/skills/video-editor/scripts/punch_in.py --self-test`.
  - New graphics check before the hand-over (`qa_graphics.py`, step 8). It names the graphic and the time when a font isn't bundled (the render would quietly swap it), a graphic covers the face or a caption, two graphics come less than 0.5 s apart, a full-screen graphic flashes black, a graphic is cut off at the edge, or a rendered clip is damaged. It reads the morph windows from the run file, and its notes say what it couldn't check. For ads on vertical video, `--platform reels`, `tiktok` or `shorts` also keeps graphics and captions out of the app's own buttons and text. Once the check passes, one fresh subagent looks over the check sheets once.
  - New run file (`run_state.py`). After every step, `work/<name>.run.json` records where the edit is, the current files, the theme and each graphic's time window. A new session reads it and carries on from the next step instead of starting over. The windows that keep kinetic text, captions and sounds off the graphics now come from it, so they are never retyped from memory. Check with `.venv/Scripts/python .claude/skills/video-editor/scripts/run_state.py --self-test`.
  - New `retime.py`: put back a cut, cut more, or make the pacing tighter or gentler after the graphics are planned, and every graphic, sound effect and caption moves onto the new cut and still lands on the same word, without planning the graphics again. It works from the words saved before the graphics (`retime.py <name> --save`), so neither a fresh transcription nor a longer or shorter pause can shift anything, and each sound stays with its graphic. Anything whose words were cut is dropped and listed, words that come back get captions, and the old plans are kept as `.pre-retime.json`. Check with `.venv/Scripts/python .claude/skills/video-editor/scripts/retime.py --self-test`.
  - Fixes from a full test edit and a code review:
    - A re-cut can carry on in a new session: marking a step again takes the marks off every step after it.
    - A ring chart is dropped when the number it counts to is cut.
    - A dead-air preview (`--analyze`) no longer replaces the report the mistake step reads.
    - Under the per-minute cap, every graphic gets its first sound before a card gets a second one, and the printout names any graphic left without a sound.
    - `--position` now works when captions are burned from a saved plan.
    - Numbers said as words ("six months") count as numbers for kinetic text.
    - The mistake step refuses a video whose length doesn't match its transcript, instead of cutting the wrong words.
    - A damaged cut list gets a plain message naming the file.
    - Re-listen finds the uncut video after the project folder moved.
    - A mono voice is levelled the same as a stereo copy of it (about 3 dB lower than before).
  - One home per rule in the guides: graphic spacing and timing live in `talking-head-recut`, and each theme's caption style lives in `motion-templates/themes/<theme>.json` (`captions`). The other guides point there instead of repeating numbers that could drift apart.
- **2026-10-30 (more from HyperFrames):**
  - The `hyperframes`, `hyperframes-cli` and `hyperframes-registry` skills now match the pinned HyperFrames CLI (0.8.221; the registry guide is from upstream main). The new guides were merged in next to the old ones, which other skills still use. Each starts with an "In this folder" note: footage edits go through `video-editor`, HeyGen paid and upload features need your OK, and `/video-editor:auto` uses this folder's own templates first.
  - New `cut-the-curve` skill: nine tested motion recipes with exact timing and easing. Cards now enter on `expo.out`, a full-screen payoff lands with an inverse zoom, and the flowchart camera glides slow-fast-slow.
  - New `sound-effects` skill, a step of `/video-editor:auto` before captions: each sound lands one frame after its graphic, sits under your voice, and the mix leaves the voice and picture untouched. Check with `.venv/Scripts/python .claude/skills/sound-effects/scripts/test_sfx.py`.
  - New `text-behind` skill: one big word behind the speaker with a local cutout (u2net via HyperFrames). It places the word so the head covers part of it while every letter stays readable, in the theme's font and colour, and composites in one encode with the audio copied.
  - Three new templates adapted from the HyperFrames registry: `lower-third`, `title-card` (calm or lockup) and `annotate` (hand-drawn circle or underline).
  - Fixes from an end-to-end test of the director step: the apple theme no longer bounces and its panels are less see-through, previews go to `work/previews/` instead of `output/`, unchanged template clips are reused instead of re-rendered, the face position is measured at the start, and the spacing and timing rules agree.
- **2026-10-30 (directed graphics):**
  - New `talking-head-recut` skill, now the graphics step of `/video-editor:auto`: Claude writes a director's plan (every graphic, timed to the word), shows it for your OK, then designs each card by hand. HeyGen retired the original on 2026-10-21; this version is rebuilt on the local pipeline, with its tested timing and placement numbers.
  - New `card` template: renders a card Claude writes (HTML and GSAP) with the theme, fonts, icons and check frames of the other templates. Web links are refused.
  - New `apple` theme and `--style apple` captions, with the Inter font (OFL) bundled.
  - Three tested example cards: a stat with a count-up, key points that build as they're said, and a full-screen statement.
- **2026-10-30 (motion templates):**
  - New `motion-templates` skill with 8 templates: flowchart explainer, steps, compare, quote, chapter, hook title, label tags and save / follow card.
  - 3 themes: blueprint, midnight and paper.
  - `/video-editor:auto` now adds templates where the speech fits.
  - New `hand` caption style: handwriting, with the spoken word lit up.
  - Bundled assets:
    - the Architects Daughter font (OFL), in `video-editor/assets/fonts`
    - 157 Lucide line icons (ISC, license in `motion-templates/assets/icons`)
  - `build_template.py --self-test` checks every template in every theme.
  - Fixes from a full test run:
    - Captions no longer drop a quick one-word caption, and a word that would flash by alone joins its neighbours. Check with `.venv/Scripts/python tests/test_captions.py`.
    - The flowchart recap plays by itself when there are about 3.4 s after the last box, and holds the full map before the fade.
    - `find_emphasis.py --skip` keeps kinetic text out of graphic windows.
    - The auto-edit guide is clearer about spacing (hook and save card don't count), caption style with blueprint, and hook placement in vertical video.
- **2026-10-30 (automatic edit):**
  - New `/video-editor:auto` command and "auto" keyword. Claude profiles each video (short, medium or long) and then runs the whole chain itself: dead air, retakes, morph charts where numbers are said, kinetic text, captions.
  - The `video-editor` skill maps single keywords ("captions", "highlights", "chart", "retakes") to the right skills and always runs them in the right order.
  - `make_captions.py --hide-during` keeps captions off graphics.
  - The retake finder now also catches a phrase said twice in a row, with a new test (`npm test`: 12 of 12 pass).
  - Fixes from a test run by a fresh agent:
    - Numbers stay whole ("1,000", "87%", "3.5x") in transcripts and captions.
    - The check / X label sits in a dark box.
    - Kinetic-text keywords can be phrases ("phone is enough").
    - Clearer rules for how far apart graphics go and how long a cutaway lasts.
  - The automatic edit first looks at frames of the source. On an already-edited video (for example a downloaded reel with captions burned in), it skips captions and repeated text rather than stacking a second set on top.
- **2026-10-30 (update):** Added the Herk Edit Kit:
  - its 14 skills, tools and style library
  - its playbook, motion philosophy and library guide
  - local transcription for its tools
  - safety fixes

  Added three new skills:
  - `captions`: playbook-style burned-in captions placed below the face
  - `kinetic-text`: emphasis detection plus five text animations
  - `morph-shapes`: seven morphing chart and symbol templates

  Also: OpenCV pinned to 4.x, GSAP added, and HyperFrames runs without telemetry or extra skill installs.

  Fixes from the end-to-end test:
  - The dead-air cutter now also trims picture that runs on after the audio ends.
  - Check / X graphics land on the word and float without a panel.
  - Kinetic text has a dark halo, so it reads on white clothing.
  - `build_morph.py --help` works.

  Published on GitHub (public) under the MIT license.
- **2026-10-30:** First version. Windows and macOS / Linux setup with portable tools, the `video-editor` skill, dead-air cutter with gentle / normal / tight presets, captions, HyperFrames titles, tested FFmpeg recipes.
