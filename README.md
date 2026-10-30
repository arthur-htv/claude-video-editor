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
- Disk space: plan for about 2 GB. The first time you make captions, the speech model adds about 0.5 GB (in `tools/models/`). `tools/uv-cache/` is only a download cache: deleting it frees space and doesn't break anything.
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
| `video-editor` | Cutting dead air, plus everyday edits: trim, join, vertical, music, logo, compress | "edit my videos", "make it tighter" |
| `captions` | Burned-in captions in the playbook's reel style (1-3 words, dark box, colored keywords, never over the mouth), one-word captions, or clean subtitles + `.srt` | "add captions", "subtitles for YouTube" |
| `kinetic-text` | Animated text only on the words you stress, numbers and names (pop, slam, typewriter, highlight, stack), spaced out so there's no clutter | "make the key points pop", "add kinetic typing on the important words" |
| `morph-shapes` | A circle that becomes a bar chart, donut, line chart, check / X, or counting ring | "show 6 hours vs 1 hour as a chart at 0:12", "add a checkmark when I say approved" |
| `edit-video` | Herk Edit Kit: the full talking-head edit (transcript, silences, mistakes, story, motion graphics, verified render) | "use edit-video on input/raw.mp4" |
| `short-form-edit` | Herk Edit Kit: reels, Shorts and short ads with a hook, captions, B-roll and sound | "turn input/raw.mp4 into a 9:16 reel" |
| `cut-silences`, `cut-mistakes` | Herk Edit Kit: transcript-driven silence cuts, then a reviewed list of retakes, stutters and false starts | "remove my retakes and stutters" |
| `video-storytelling`, `hyperframes-video-beats` | Herk Edit Kit: the visual story arc, glass cards, paper takeovers, callbacks | "plan the motion graphics for this video" |
| `style-library` | Herk Edit Kit: 406 ready-made motion-graphic cards in two styles (Vox-like explainer, Kallaway-like) | "use a stat card from the style library" |
| `motion-showreel`, `make-a-video`, `website-to-hyperframes` | Herk Edit Kit: showreels cut to music, videos from a brief, videos from a website | "make a 15-second showreel" |
| `hyperframes`, `hyperframes-cli`, `hyperframes-registry`, `gsap` | Rules and commands for HTML-to-video animation (used by the skills above) | (used automatically) |

How Nate's videos are edited with these skills (the order, the numbers, the caption and B-roll rules, the lessons) is in **[docs/EDITING-PLAYBOOK.md](docs/EDITING-PLAYBOOK.md)**. The motion vocabulary is in **[MOTION_PHILOSOPHY.md](MOTION_PHILOSOPHY.md)**, the card library rules in **[style-library/GUIDE.md](style-library/GUIDE.md)**, and the kit's own workspace guide in **[AGENTS.md](AGENTS.md)**. Step-by-step kit workflows: [docs/WORKFLOW.md](docs/WORKFLOW.md), [docs/SHORT-FORM.md](docs/SHORT-FORM.md), [docs/PROMPTS.md](docs/PROMPTS.md).

### A full edit, in order

1. "Cut the dead air" (`video-editor`), or for a reel "use short-form-edit".
2. "Show me the retakes and stutters to cut" (`cut-mistakes`). You approve each cut.
3. "Make the key points pop" (`kinetic-text`) and "show the numbers as charts" (`morph-shapes`).
4. "Add captions" (`captions`). Captions go last, so they match the final timing.

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
├── work/                  scratch files and reports (safe to empty)
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
│   └── skills/
│       ├── video-editor/  dead air + everyday edits (scripts, recipes, fonts)
│       ├── captions/, kinetic-text/, morph-shapes/
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

The `.gitignore` already keeps the big and personal things out of git: `tools/`, `.venv/`, `node_modules/`, `work/`, `video-projects/`, `.env`, and the contents of `input/` and `output/`. Only the setup scripts, the guides, the skills and the style library get shared, about 2.5 MB. Anyone who clones the folder runs the setup once (Step 3) and has the same editor.

Before you push changes, run `git status` and check that no video, API key or `.env` file is listed.

## Troubleshooting

| Problem | Fix |
|---|---|
| Windows: "running scripts is disabled on this system" | Use `setup.cmd`, or the full command `powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1`. |
| The setup stopped with a download error | Usually a network hiccup or a firewall. Run the setup again; finished steps are skipped. |
| "checksum mismatch" | The download was damaged. Run the setup again. If it keeps happening, your network may be altering downloads (some company proxies do). |
| Antivirus removed `ffmpeg.exe` | Allow the `tools` folder in your antivirus, then run the setup again. |
| Windows: "Importing the numpy C-extensions failed" or other DLL load errors | The folder sits too deep: Windows has a 260-character path limit and some library files are nested deeply. Move the folder somewhere short, such as `Documents\claude-video-editor`, and run the setup again. |
| Linux: setup asks for `curl` or `xz` | `sudo apt install curl xz-utils` (Debian / Ubuntu), then run the setup again. |
| Linux: "Scene detection is unavailable" | Scene detection is optional. To enable it: `sudo apt install libgl1 libglib2.0-0`. Everything else works without it. |
| Claude doesn't mention the setup status at the start | The start-up check needs the folder to be trusted, and on Windows it needs Git for Windows (which Claude Code uses anyway). Without it, Claude still follows `CLAUDE.md`; you can also say "check the setup". |
| You moved or renamed the folder | Run the setup again. It notices the Python environment points to the old place and rebuilds it. |
| Words are cut off | Ask for "more natural" (`gentle`) or "more padding". |
| Hardly anything was cut | The video may have background music or constant noise, or few real pauses. Claude reports the noise level and can set the silence level by hand. |
| A long video stopped halfway | Ask Claude to run it in the background; very long renders can outlast a single command. |
| HyperFrames render fails | Run `python .claude/skills/video-editor/scripts/hf.py doctor`. Rendering titles needs an internet connection (the animation library loads from a CDN). On Linux, the headless Chrome may need extra system libraries; `doctor` lists them. |
| Start over completely | Delete `tools/`, `.venv/` and `node_modules/`, then run the setup again. |

## Removing it

Delete the folder. Two things HyperFrames keeps outside the folder, which you can also delete:

- its headless Chrome, in `~/.cache/hyperframes` (Windows: `C:\Users\<you>\.cache\hyperframes`)
- its own Claude skills (`hyperframes`, `hyperframes-cli`, `hyperframes-registry`, `media-use`), in `~/.claude/skills` and `~/.agents/skills`. These appear only if HyperFrames was ever run outside this folder's tools: this folder turns that install off and already contains those skills.

## Changelog

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

  Published on GitHub (public).
- **2026-10-30:** First version. Windows and macOS / Linux setup with portable tools, the `video-editor` skill, dead-air cutter with gentle / normal / tight presets, captions, HyperFrames titles, tested FFmpeg recipes.
