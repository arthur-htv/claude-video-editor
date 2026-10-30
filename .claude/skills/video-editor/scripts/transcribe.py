#!/usr/bin/env python3
"""Make subtitles (.srt) from a video or audio file with faster-whisper.

Runs locally and free. The speech model downloads once into tools/models/
(base ~150 MB, small ~480 MB). Short caption lines suit social media.

Examples (from the project folder, with the .venv python)
  python transcribe.py output/talk.mp4                    -> output/talk.srt
  python transcribe.py input/talk.mov --out work/talk.srt --language en
  python transcribe.py output/talk.mp4 --model base --max-chars 32 --words
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

# Quiet the model downloader: no symlink warnings on Windows, no rate-limit notices.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
warnings.filterwarnings("ignore", module="huggingface_hub")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vtools import project_root  # noqa: E402


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _text(ws: list[dict]) -> str:
    return " ".join(x["word"] for x in ws)


def build_cues(words: list[dict], max_chars: int, max_seconds: float = 5.0) -> list[dict]:
    """Group words into caption lines that read naturally.

    A line ends after a sentence (. ? !), at a long pause, or when it would get too
    long; a full line breaks at its last comma or full stop rather than mid-phrase.
    """
    cues, cur = [], []
    for w in words:
        too_long = cur and (len(_text(cur + [w])) > max_chars or w["end"] - cur[0]["start"] > max_seconds)
        pause = cur and w["start"] - cur[-1]["end"] > 0.7
        if pause:
            cues.append(cur)
            cur = []
        elif too_long:
            # Break after the last punctuation in the line if that keeps a reasonable first part.
            cut = max((i + 1 for i, x in enumerate(cur[:-1]) if x["word"].endswith((",", ";", ":", ".", "?", "!"))
                       and len(_text(cur[:i + 1])) >= max_chars * 0.4), default=len(cur))
            cues.append(cur[:cut])
            cur = cur[cut:]
        cur.append(w)
        if w["word"].endswith((".", "?", "!")) and len(_text(cur)) >= 10:
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    return [{"start": c[0]["start"], "end": c[-1]["end"], "text": _text(c)} for c in cues]


def transcribe_words(src: Path, model_name: str = "small", language: str | None = None):
    """Word timings for a media file: ([{"start", "end", "word"}], info). Runs locally."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         download_root=str(project_root() / "tools" / "models"))
    segments, info = model.transcribe(str(src), language=language, vad_filter=True, word_timestamps=True)
    words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
             for seg in segments for w in (seg.words or []) if w.word.strip()]
    return words, info


def load_words(path: Path) -> list[dict]:
    """Read word timings from any of the shapes this folder uses:
    our <name>.words.json list, the Herk kit / ElevenLabs shape {"words": [{"text", "start", "end", "type"}]},
    or HyperFrames transcript.json ([{"text", "start", "end"}])."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("words", data) if isinstance(data, dict) else data
    words = []
    for w in items:
        if w.get("type", "word") != "word":        # ElevenLabs also lists spacing and sound events
            continue
        text = (w.get("word") or w.get("text") or "").strip()
        if text:
            words.append({"start": float(w["start"]), "end": float(w["end"]), "word": text})
    return words


def kit_transcript(words: list[dict], duration: float | None = None) -> dict:
    """The word-level shape the Herk Edit Kit tools (cut-silences, cut-mistakes, beat sync) read."""
    out = {"words": [{"text": w["word"], "start": w["start"], "end": w["end"], "type": "word"} for w in words]}
    if duration:
        out["audio_duration_secs"] = round(duration, 3)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Make an .srt subtitle file from speech (local, free).")
    p.add_argument("file", type=Path, help="video or audio file")
    p.add_argument("--out", type=Path, help="where to write the .srt (default: output/<name>.srt)")
    p.add_argument("--model", default="small", help="tiny, base, small (default), medium, large-v3, turbo")
    p.add_argument("--language", help="language code such as en or es (default: detect)")
    p.add_argument("--max-chars", type=int, default=42, help="longest caption line (default 42)")
    p.add_argument("--words", action="store_true", help="also save word timings as <name>.words.json in work/")
    p.add_argument("--json", type=Path, metavar="PATH",
                   help="also save a word-level transcript in the Herk Edit Kit format (for cut-silences, "
                        "cut-mistakes and beat sync), e.g. video-projects/<slug>/assets/raw.json")
    args = p.parse_args()

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("faster-whisper is missing. Use the project's Python in .venv, or run the setup (see README.md).")
        return 2

    root = project_root()
    src = args.file if args.file.exists() else root / "input" / args.file
    if not src.is_file():
        print(f"Not found: {args.file}")
        return 2
    out = args.out or root / "output" / f"{src.stem}.srt"
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing {src.name} with the '{args.model}' model (first use downloads it)...", flush=True)
    words, info = transcribe_words(src, args.model, args.language)
    if not words:
        print("No speech found.")
        return 1

    cues = build_cues(words, args.max_chars)
    out.write_text("\n".join(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n"
                             for i, c in enumerate(cues, 1)), encoding="utf-8")
    if args.words:
        wpath = root / "work" / f"{src.stem}.words.json"
        wpath.parent.mkdir(parents=True, exist_ok=True)
        wpath.write_text(json.dumps(words, indent=1), encoding="utf-8")
        print(f"Word timings: {wpath}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(kit_transcript(words, info.duration), indent=1), encoding="utf-8")
        print(f"Kit transcript: {args.json}")
    print(f"Language: {info.language} ({info.language_probability:.0%}). {len(cues)} captions -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
