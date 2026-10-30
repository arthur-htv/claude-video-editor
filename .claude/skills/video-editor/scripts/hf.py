#!/usr/bin/env python3
"""Run the HyperFrames CLI with this folder's Node.js and FFmpeg (no PATH setup needed).

Everything after the script name is passed to `hyperframes` unchanged. Run it from
the directory HyperFrames should work in (for render/check: the HyperFrames project).

Examples (from the project folder, with the .venv python)
  python .claude/skills/video-editor/scripts/hf.py doctor
  python .claude/skills/video-editor/scripts/hf.py init work/hyperframes/intro --non-interactive
  cd work/hyperframes/intro && python ../../../.claude/skills/video-editor/scripts/hf.py render -o ../../intro.mp4
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vtools import SETUP_HINT, SetupError, find_tool, project_root  # noqa: E402


def main() -> int:
    root = project_root()
    cli = root / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if not cli.is_file():
        print(f"HyperFrames is not installed in {root / 'node_modules'}. {SETUP_HINT}")
        return 2
    try:
        node, ffmpeg, ffprobe = find_tool("node"), find_tool("ffmpeg"), find_tool("ffprobe")
    except SetupError as e:
        print(e)
        return 2
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(ffmpeg).parent), str(Path(node).parent), env.get("PATH", "")])
    env["HYPERFRAMES_FFMPEG_PATH"] = ffmpeg
    env["HYPERFRAMES_FFPROBE_PATH"] = ffprobe
    # Keep HyperFrames local: no usage telemetry, and no silent install of its skills into ~/.claude
    env.setdefault("HYPERFRAMES_NO_TELEMETRY", "1")
    env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
    return subprocess.call([node, str(cli), *sys.argv[1:]], env=env)


if __name__ == "__main__":
    sys.exit(main())
