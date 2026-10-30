#!/usr/bin/env bash
# SessionStart hook for the Claude video editor.
#  1. Tells Claude whether setup is complete. Whatever this prints becomes context for Claude.
#  2. Puts this folder's tools on PATH for the shell commands Claude runs in this session,
#     so ffmpeg, ffprobe, node, hyperframes and the .venv python work by name.
# It never installs anything by itself: Claude runs the setup with the user's knowledge.

root="${CLAUDE_PROJECT_DIR:-$PWD}"
if command -v cygpath >/dev/null 2>&1; then root="$(cygpath -u "$root")"; fi

exe=""
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) exe=".exe" ;; esac

missing=()

# FFmpeg + ffprobe: the portable copy first, then anything already on PATH.
if [ -f "$root/tools/ffmpeg/bin/ffmpeg$exe" ] && [ -f "$root/tools/ffmpeg/bin/ffprobe$exe" ]; then :
elif command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then :
else missing+=("FFmpeg + ffprobe"); fi

# Node.js 22 or newer.
node_bin=""
for c in "$root/tools/node/node$exe" "$root/tools/node/bin/node"; do
  if [ -f "$c" ]; then node_bin="$c"; break; fi
done
[ -z "$node_bin" ] && node_bin="$(command -v node 2>/dev/null || true)"
if [ -z "$node_bin" ]; then
  missing+=("Node.js 22+")
else
  major="$("$node_bin" --version 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/')"
  case "$major" in ''|*[!0-9]*) major=0 ;; esac
  [ "$major" -ge 22 ] || missing+=("Node.js 22+ (found v$major)")
fi

# Python environment and HyperFrames.
if [ ! -f "$root/.venv/Scripts/python.exe" ] && [ ! -f "$root/.venv/bin/python" ]; then
  missing+=("Python environment (.venv)")
fi
[ -f "$root/node_modules/hyperframes/package.json" ] || missing+=("HyperFrames")
[ -f "$root/node_modules/gsap/package.json" ] || missing+=("GSAP (run the setup again)")

# How many raw videos are waiting in input/.
waiting=0
if [ -d "$root/input" ]; then
  waiting=$(find "$root/input" -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.m4v' \
    -o -iname '*.mkv' -o -iname '*.avi' -o -iname '*.webm' -o -iname '*.mts' -o -iname '*.wmv' \
    -o -iname '*.mp3' -o -iname '*.wav' -o -iname '*.m4a' \) 2>/dev/null | wc -l | tr -d ' ')
fi

if [ ${#missing[@]} -gt 0 ]; then
  list="$(printf '%s, ' "${missing[@]}")"
  list="${list%, }"
  cat <<EOF
[video-editor] Setup is NOT complete. Missing: $list.
Before editing anything: read README.md, tell the user in one line what will be installed (portable copies inside this folder, nothing system-wide), then run the setup:
  Windows:       powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
  macOS / Linux: bash setup.sh
The first run downloads a few hundred MB, so give it a 10-minute timeout or run it in the background. Then confirm with the same command plus -Check (Windows) or --check (macOS / Linux).
EOF
else
  echo "[video-editor] Setup OK: FFmpeg, ffprobe, Node.js, HyperFrames and .venv are ready. Raw videos waiting in input/: $waiting. Finished videos go to output/. Use the video-editor skill for any editing request."
fi

# Put the folder's tools first on PATH for Claude's shell commands (harmless if a folder doesn't exist yet).
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  add=""
  for d in "$root/.venv/Scripts" "$root/.venv/bin" "$root/tools/ffmpeg/bin" "$root/tools/node/bin" "$root/tools/node" "$root/node_modules/.bin"; do
    add="$add$d:"
  done
  printf 'export PATH="%s$PATH"\n' "$add" >> "$CLAUDE_ENV_FILE"
  # Keep HyperFrames local: no usage telemetry, no silent install of its skills into ~/.claude
  printf 'export HYPERFRAMES_NO_TELEMETRY=1\nexport HYPERFRAMES_SKIP_SKILLS=1\n' >> "$CLAUDE_ENV_FILE"
fi

exit 0
