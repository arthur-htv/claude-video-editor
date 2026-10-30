#!/usr/bin/env bash
# One-time setup for the Claude video editor folder (macOS / Linux).
#
# Checks for FFmpeg + ffprobe, Node.js 22+, Python 3.12 and HyperFrames. Anything missing is
# downloaded as a portable copy into ./tools (no sudo, nothing installed system-wide). Then it
# creates the Python environment in ./.venv and installs the libraries in requirements.txt.
# Safe to run again at any time: finished steps are skipped.
#
#   bash setup.sh                    set everything up
#   bash setup.sh --check            only report what is installed (changes nothing)
#   bash setup.sh --force-portable   ignore tools already on this computer; use copies in ./tools
set -euo pipefail

CHECK=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --force-portable) FORCE=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg  (use --check or --force-portable)"; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$ROOT/tools"
DL="$TOOLS/_downloads"
FFDIR="$TOOLS/ffmpeg/bin"
NODEDIR="$TOOLS/node"
UVDIR="$TOOLS/uv"
PYDIR="$TOOLS/python"
VENV="$ROOT/.venv"
VPY="$VENV/bin/python"
PY_VERSION=3.12
NODE_MIN=22      # HyperFrames needs Node.js 22 or newer
NODE_MAJOR=24    # LTS line downloaded when Node.js is missing

# ------------------------------------------------------------------ output helpers
step() { printf '\n\033[36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mOK\033[0m       %s\n' "$*"; }
note() { printf '   ..       %s\n' "$*"; }
miss() { printf '   \033[33mMISSING\033[0m  %s\n' "$*"; }
warn() { printf '   \033[33mWARNING\033[0m  %s\n' "$*" >&2; }
die()  {   # stderr, so the message shows even inside $(...)
  printf '\n\033[31mSETUP STOPPED: %s\033[0m\n' "$*" >&2
  printf 'Fix the problem above (often a network hiccup) and run the setup again. Finished steps are skipped.\n' >&2
  exit 1
}

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux)  OS=linux ;;
  *) echo "This script is for macOS and Linux. On Windows run: powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1"; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64|amd64)  ARCH=x64 ;;
  arm64|aarch64) ARCH=arm64 ;;
  *) echo "Unsupported processor type: $(uname -m)"; exit 1 ;;
esac

have() { command -v "$1" >/dev/null 2>&1; }

download() {  # url dest  -> prints the final URL after redirects
  mkdir -p "$(dirname "$2")"
  curl -fL --retry 3 -sS -o "$2" -w '%{url_effective}' "$1" || die "download failed: $1"
}

sha256_of() { if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
md5_of()    { if have md5sum; then md5sum "$1" | cut -d' ' -f1; else md5 -q "$1"; fi; }

verify() {  # file kind(sha256|md5) checksum-text
  local expected got
  expected="$(printf '%s' "$3" | grep -oE '[0-9a-fA-F]{32,64}' | head -1 | tr 'A-F' 'a-f')"
  if [ -z "$expected" ]; then warn "No checksum published for $(basename "$1"); skipping the check."; return; fi
  if [ "$2" = md5 ]; then got="$(md5_of "$1")"; else got="$(sha256_of "$1")"; fi
  [ "$got" = "$expected" ] || die "checksum mismatch for $(basename "$1"). The download is damaged or was tampered with."
  note "Checksum verified"
}

# ------------------------------------------------------------------ tool status
FF_WHERE=""; FFMPEG=""; FFPROBE=""
find_ffmpeg() {
  FF_WHERE=""; FFMPEG=""; FFPROBE=""
  if [ -x "$FFDIR/ffmpeg" ] && [ -x "$FFDIR/ffprobe" ]; then
    FF_WHERE="portable copy in tools/ffmpeg"; FFMPEG="$FFDIR/ffmpeg"; FFPROBE="$FFDIR/ffprobe"
  elif [ "$FORCE" = 0 ] && have ffmpeg && have ffprobe; then
    FF_WHERE="already installed on this computer"; FFMPEG="$(command -v ffmpeg)"; FFPROBE="$(command -v ffprobe)"
  fi
}

node_major() { "$1" --version 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' | grep -E '^[0-9]+$' || echo 0; }
NODE_WHERE=""; NODE=""
find_node() {
  NODE_WHERE=""; NODE=""
  if [ -x "$NODEDIR/bin/node" ]; then
    NODE_WHERE="portable copy in tools/node"; NODE="$NODEDIR/bin/node"
  elif [ "$FORCE" = 0 ] && have node && [ "$(node_major "$(command -v node)")" -ge "$NODE_MIN" ]; then
    NODE_WHERE="already installed on this computer"; NODE="$(command -v node)"
  fi
}

UV=""
find_uv() {
  UV=""
  if [ -x "$UVDIR/uv" ]; then UV="$UVDIR/uv"
  elif [ "$FORCE" = 0 ] && have uv; then UV="$(command -v uv)"; fi
}

REQUIRED_IMPORTS='import numpy, moviepy, faster_whisper'
OPTIONAL_IMPORTS='import scenedetect, cv2'   # scene detection; OpenCV needs desktop graphics libraries on Linux
venv_ok() { [ -x "$VPY" ] && "$VPY" -c 'import sys' >/dev/null 2>&1; }
libs_ok() { venv_ok && "$VPY" -c "$REQUIRED_IMPORTS" >/dev/null 2>&1; }
scenes_ok() { venv_ok && "$VPY" -c "$OPTIONAL_IMPORTS" >/dev/null 2>&1; }
scenes_hint() {
  warn "Scene detection is unavailable: $("$VPY" -c "$OPTIONAL_IMPORTS" 2>&1 | tail -1)"
  [ "$OS" = linux ] && warn "Fix (Ubuntu / Debian): sudo apt install libgl1 libglib2.0-0. Everything else works without it."
  return 0
}
hyperframes_ok() { [ -f "$ROOT/node_modules/hyperframes/package.json" ] && [ -f "$ROOT/node_modules/gsap/package.json" ]; }

# ------------------------------------------------------------------ installers
install_ffmpeg() {
  local tmp="$DL/ffmpeg" final
  rm -rf "$tmp"; mkdir -p "$tmp" "$FFDIR"
  if [ "$OS" = linux ]; then
    have xz || die "unpacking FFmpeg needs 'xz'. Install it (Ubuntu/Debian: sudo apt install xz-utils) or install FFmpeg itself (sudo apt install ffmpeg), then run the setup again."
    local a=amd64; [ "$ARCH" = arm64 ] && a=arm64
    local url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-$a-static.tar.xz"
    note "Downloading $url"
    download "$url" "$tmp/ffmpeg.tar.xz" >/dev/null
    verify "$tmp/ffmpeg.tar.xz" md5 "$(curl -fsSL "$url.md5" || true)"
    tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"
    cp "$(find "$tmp" -type f -name ffmpeg | head -1)" "$(find "$tmp" -type f -name ffprobe | head -1)" "$FFDIR/"
  else
    local a=arm64; [ "$ARCH" = x64 ] && a=amd64
    for name in ffmpeg ffprobe; do
      local url="https://ffmpeg.martin-riedl.de/redirect/latest/macos/$a/release/$name.zip"
      note "Downloading $url"
      final="$(download "$url" "$tmp/$name.zip")"
      verify "$tmp/$name.zip" sha256 "$(curl -fsSL "$final.sha256" || true)"
      (cd "$tmp" && unzip -o -q "$name.zip")
      cp "$tmp/$name" "$FFDIR/$name"
    done
  fi
  chmod +x "$FFDIR/ffmpeg" "$FFDIR/ffprobe"
}

install_node() {
  local os_tag=linux; [ "$OS" = mac ] && os_tag=darwin
  local base="https://nodejs.org/dist/latest-v$NODE_MAJOR.x" line file
  line="$(curl -fsSL "$base/SHASUMS256.txt" | grep -E "node-v[0-9.]+-$os_tag-$ARCH\.tar\.gz$" | head -1)" \
    || die "could not read the Node.js download list"
  [ -n "$line" ] || die "no Node.js $NODE_MAJOR download for $os_tag-$ARCH"
  file="${line##* }"
  note "Downloading $base/$file"
  download "$base/$file" "$DL/$file" >/dev/null
  verify "$DL/$file" sha256 "${line%% *}"
  rm -rf "$DL/node" "$NODEDIR"; mkdir -p "$DL/node"
  tar -xzf "$DL/$file" -C "$DL/node"
  mv "$DL/node/$(ls "$DL/node" | head -1)" "$NODEDIR"
}

install_uv() {
  local target
  case "$OS-$ARCH" in
    mac-arm64)   target=aarch64-apple-darwin ;;
    mac-x64)     target=x86_64-apple-darwin ;;
    linux-x64)   target=x86_64-unknown-linux-gnu ;;
    linux-arm64) target=aarch64-unknown-linux-gnu ;;
  esac
  local url="https://github.com/astral-sh/uv/releases/latest/download/uv-$target.tar.gz"
  note "Downloading $url"
  download "$url" "$DL/uv.tar.gz" >/dev/null
  verify "$DL/uv.tar.gz" sha256 "$(curl -fsSL "$url.sha256" || true)"
  rm -rf "$DL/uv"; mkdir -p "$DL/uv" "$UVDIR"
  tar -xzf "$DL/uv.tar.gz" -C "$DL/uv"
  cp "$(find "$DL/uv" -type f -name uv | head -1)" "$UVDIR/uv"
  chmod +x "$UVDIR/uv"
}

# ------------------------------------------------------------------ check mode
if [ "$CHECK" = 1 ]; then
  printf '\033[36mClaude video editor - setup check\033[0m\n'
  missing=0
  find_ffmpeg; if [ -n "$FFMPEG" ]; then ok "FFmpeg + ffprobe   ($FF_WHERE)"; else miss "FFmpeg + ffprobe"; missing=$((missing+1)); fi
  find_node;   if [ -n "$NODE" ];   then ok "Node.js $NODE_MIN+        ($NODE_WHERE)"; else miss "Node.js $NODE_MIN+"; missing=$((missing+1)); fi
  if venv_ok; then ok "Python environment (.venv)"; else miss "Python environment (.venv)"; missing=$((missing+1)); fi
  if libs_ok; then ok "Python libraries (requirements.txt)"; else miss "Python libraries (requirements.txt)"; missing=$((missing+1)); fi
  if scenes_ok; then ok "Scene detection (optional)"; elif venv_ok; then scenes_hint; fi
  if hyperframes_ok; then ok "HyperFrames (node_modules)"; else miss "HyperFrames (node_modules)"; missing=$((missing+1)); fi
  for d in input output; do
    if [ -d "$ROOT/$d" ]; then ok "$d/ folder"; else miss "$d/ folder"; missing=$((missing+1)); fi
  done
  echo
  if [ "$missing" = 0 ]; then printf '\033[32mEverything is ready.\033[0m\n'; exit 0; fi
  printf '\033[33m%s item(s) missing. Run: bash setup.sh\033[0m\n' "$missing"
  exit 1
fi

# ------------------------------------------------------------------ setup
have curl || die "this setup needs 'curl' to download tools. Install it (Ubuntu/Debian: sudo apt install curl) and run the setup again."
have tar  || die "this setup needs 'tar'."
started=$(date +%s)
trap 'rm -rf "$DL"' EXIT
printf '\033[36mClaude video editor - setup\033[0m\n'
echo "Folder: $ROOT"
echo "Everything missing is downloaded into this folder only (tools/, .venv/, node_modules/)."

step "1/6  Folders"
mkdir -p "$ROOT/input" "$ROOT/output" "$ROOT/work" "$TOOLS"
ok "input/ (raw videos), output/ (finished videos), work/ (scratch), tools/ (portable programs)"

step "2/6  FFmpeg + ffprobe"
find_ffmpeg
if [ -z "$FFMPEG" ]; then
  note "Not found. Installing a portable copy into tools/ffmpeg..."
  install_ffmpeg
  find_ffmpeg
fi
ok "$("$FFMPEG" -version | head -1)  [$FF_WHERE]"

step "3/6  Node.js $NODE_MIN+"
find_node
if [ -z "$NODE" ]; then
  note "Not found (or older than $NODE_MIN). Installing portable Node.js $NODE_MAJOR LTS into tools/node..."
  install_node
  find_node
fi
ok "Node.js $("$NODE" --version)  [$NODE_WHERE]"

step "4/6  Python $PY_VERSION environment (.venv)"
find_uv
if [ -z "$UV" ]; then
  note "Installing uv (a small, fast Python installer) into tools/uv..."
  install_uv
  find_uv
fi
# Keep uv's downloads and cache inside this folder.
export UV_PYTHON_INSTALL_DIR="$PYDIR" UV_PYTHON_BIN_DIR="$PYDIR/bin" UV_CACHE_DIR="$TOOLS/uv-cache"
if [ "$FORCE" = 1 ]; then export UV_PYTHON_PREFERENCE=only-managed; else export UV_PYTHON_PREFERENCE=managed; fi
if venv_ok; then
  ok ".venv already exists"
else
  note "Creating .venv with Python $PY_VERSION (uses an installed Python $PY_VERSION if there is one, otherwise downloads a portable one into tools/python)..."
  "$UV" venv "$VENV" --python "$PY_VERSION" --seed --clear
fi
ok "$("$VPY" --version) in .venv"

step "5/6  Python libraries (requirements.txt)"
note "Installing numpy, moviepy, faster-whisper, scenedetect, opencv, auto-editor... (first run takes a few minutes)"
"$UV" pip install --quiet --python "$VPY" -r "$ROOT/requirements.txt" || die "installing the Python libraries failed"
if ! libs_ok; then
  "$VPY" -c "$REQUIRED_IMPORTS" || true    # show the real error
  die "the Python libraries installed but do not import (error above)"
fi
ok "Python libraries installed and importable"
if scenes_ok; then ok "Scene detection ready"; else scenes_hint; fi
if [ -x "$VENV/bin/auto-editor" ]; then
  # The pip package fetches its program on first use; do it now so later runs work offline.
  if ae="$(PYTHONUNBUFFERED=1 "$VENV/bin/auto-editor" --version 2>/dev/null | tail -1)"; then
    ok "auto-editor $ae ready"
  else
    warn "auto-editor could not fetch its program (optional; the dead-air cutter does not need it)."
  fi
fi

step "6/6  HyperFrames (HTML-to-video)"
export PATH="$(dirname "$NODE"):$(dirname "$FFMPEG"):$PATH"
have npm || die "npm was not found next to Node.js. Run: bash setup.sh --force-portable"
(cd "$ROOT" && npm install --no-fund --no-audit --loglevel=error) || die "installing HyperFrames failed"
HF_CLI="$ROOT/node_modules/hyperframes/bin/hyperframes.mjs"
ok "HyperFrames $("$NODE" "$HF_CLI" --version 2>/dev/null | tail -1)"
note "Downloading the headless Chrome that HyperFrames renders with (once, into your user cache)..."
if HYPERFRAMES_FFMPEG_PATH="$FFMPEG" HYPERFRAMES_FFPROBE_PATH="$FFPROBE" HYPERFRAMES_NO_TELEMETRY=1 HYPERFRAMES_SKIP_SKILLS=1 \
    "$NODE" "$HF_CLI" browser ensure >/dev/null 2>&1; then
  ok "HyperFrames browser ready"
else
  warn "HyperFrames could not prepare its browser yet. It will retry on first render ('npx hyperframes doctor' explains why). Dead-air cutting does not need it."
fi

echo
printf '\033[32mSetup complete in %ss.\033[0m\n' "$(( $(date +%s) - started ))"
echo 'Next: put raw videos in input/, open this folder in Claude Code and say "edit my videos".'
echo 'Finished videos appear in output/.'
