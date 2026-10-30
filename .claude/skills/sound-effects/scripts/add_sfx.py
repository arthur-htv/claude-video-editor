#!/usr/bin/env python3
"""Mix a sound-effects plan into a video's audio in one FFmpeg pass, without touching the voice.

Each cue is delayed to its spot, set to its gain and summed onto the original track with
amix normalize=0, so the speech keeps its exact level. The picture is copied, not re-encoded.
Afterwards it measures the result: loudness and true peak before and after, where each cue's
peak really landed (in frames), and how much the audio changed outside the cues. If the mix
would clip, every cue is lowered by the overshoot and the mix runs once more.

Examples (from the project folder)
  PY .claude/skills/sound-effects/scripts/add_sfx.py work/talk.t.mp4 --plan work/talk.sfx.json --out work/talk.s.mp4
  ... --hf-check     also run HyperFrames' local audio analysis on the result (no upload)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suggest_sfx import (SetupError, decode, envelope, find_tool, manifest, measure, mono_pan, probe,  # noqa: E402
                         project_root, sfx_dir)

CEILING = -1.0   # dBTP: the most a mix may peak, unless the source already peaks higher


def audio_format(path: Path) -> tuple[int, int, str]:
    res = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels,channel_layout", "-of", "json", str(path)],
                         capture_output=True, text=True)
    s = (json.loads(res.stdout or "{}").get("streams") or [{}])[0]
    ch = int(s.get("channels") or 1)
    return int(s.get("sample_rate") or 48000), ch, s.get("channel_layout") or ("mono" if ch == 1 else "stereo")


def loudness(path: Path) -> tuple[float, float]:
    """(integrated LUFS, true peak dBTP) from FFmpeg's EBU R128 meter."""
    res = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    lufs = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", res.stderr)
    peak = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", res.stderr)
    return float(lufs[-1]) if lufs else float("nan"), float(peak[-1]) if peak else float("nan")


def filter_graph(cues: list[dict], sr: int, ch: int, layout: str, shift_db: float) -> tuple[list[str], str]:
    """Extra -i inputs (one per distinct sound) and the -filter_complex text."""
    names = sorted({c["sound"] for c in cues})
    inputs, parts, labels = [], [], []
    for k, name in enumerate(names, 1):
        path = sfx_dir() / manifest()[name]["file"]
        inputs += ["-i", str(path)]
        group = [c for c in cues if c["sound"] == name]
        if len(group) > 1:
            parts.append(f"[{k}:a]asplit={len(group)}" + "".join(f"[i{k}_{j}]" for j in range(len(group))))
        for j, c in enumerate(group):
            rate = float(c.get("rate", 1.0))
            start = c["start"]
            chain = [mono_pan(probe(path).audio_channels), f"aresample={sr}"]
            if rate != 1.0:
                chain += [f"asetrate={round(sr * rate)}", f"aresample={sr}"]
            chain.append(f"volume={c['gain_db'] + shift_db:.2f}dB")
            chain.append(f"atrim=start={-start:.5f},asetpts=PTS-STARTPTS" if start < 0
                         else f"adelay={round(start * sr)}S:all=1")
            if ch > 1:  # the sound sits in the front left and right, like a centred voice
                chain.append(f"pan={layout}|c0=c0|c1=c0")
            labels.append(f"[s{k}_{j}]")
            parts.append((f"[{k}:a]" if len(group) == 1 else f"[i{k}_{j}]") + ",".join(chain) + labels[-1])
    parts.append("[0:a:0]" + "".join(labels) + f"amix=inputs={len(labels) + 1}:normalize=0:duration=first[aout]")
    return inputs, ";".join(parts)


def render(video: Path, out: Path, cues: list[dict], shift_db: float) -> None:
    sr, ch, layout = audio_format(video)
    inputs, graph = filter_graph(cues, sr, ch, layout, shift_db)
    bitrate = min(96000 * ch, 6 * sr * ch)  # AAC's ceiling at low sample rates is about 6 bits per sample
    cmd = [find_tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), *inputs,
           "-filter_complex", graph, "-map", "0:V?", "-map", "[aout]", "-c:v", "copy",
           "-c:a", "aac", "-b:a", str(bitrate), "-ar", str(sr), "-map_metadata", "0", "-movflags", "+faststart", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not out.is_file():
        raise SystemExit(f"FFmpeg could not mix the sounds: {res.stderr.strip()[-1500:]}")


def verify(video: Path, out: Path, cues: list[dict], fps: float) -> dict:
    """Subtract the source from the result: what's left is the sound effects (plus codec noise)."""
    sr = min(audio_format(video)[0], 24000)
    a, b = decode(video, sr), decode(out, sr)
    n = min(len(a), len(b))
    diff = b[:n] - a[:n]
    outside = np.ones(n, dtype=bool)
    timing = []
    for c in cues:
        s0, s1 = max(0, int(c["start"] * sr)), min(n, int((c["start"] + c["length"]) * sr))
        outside[s0:s1] = False
        lo, hi = max(0, int((c["at"] - 0.25) * sr)), min(n, int((c["at"] + 0.25) * sr))
        t, db = envelope(diff[lo:hi], sr, 0.001)
        got = lo / sr + float(t[int(np.argmax(db))])
        timing.append({"at": c["at"], "sound": c["sound"], "peak_at": round(got, 3),
                       "off_frames": round((got - c["at"]) * fps, 2), "peak_dbfs": round(float(db.max()), 1)})
    rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)  # noqa: E731
    return {"timing": timing,
            "outside_cues": {"source_rms_db": round(rms(a[:n][outside]), 1), "change_rms_db": round(rms(diff[outside]), 1),
                             "level_change_db": round(rms(b[:n][outside]) - rms(a[:n][outside]), 3)}}


def hf_check(out: Path) -> dict:
    """HyperFrames' own analysis, on this machine only (--quality local; 'best' would upload and may bill)."""
    hf = Path(__file__).resolve().parents[2] / "video-editor" / "scripts" / "hf.py"
    res = subprocess.run([sys.executable, str(hf), "audio", str(out), "--json", "--quality", "local"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=project_root())
    try:
        item = json.loads(res.stdout[res.stdout.index("{"):])["items"][0]
    except (ValueError, KeyError, IndexError):
        return {"error": (res.stderr or res.stdout).strip()[-400:]}
    return {"loudness": item.get("loudness"), "provenance": item.get("provenance")}


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Mix a sound-effects plan into a video's audio.")
    p.add_argument("video", type=Path)
    p.add_argument("--plan", type=Path, required=True, help="work/<name>.sfx.json from suggest_sfx.py")
    p.add_argument("--out", type=Path, help="default: work/<video-stem>.s.mp4")
    p.add_argument("--hf-check", action="store_true", help="also run HyperFrames' local audio analysis (about 20 s)")
    args = p.parse_args()

    video = args.video
    sfx_dir()  # fail before any work when the sounds aren't installed
    out = args.out or project_root() / "work" / f"{video.stem}.s.mp4"
    if out.resolve() == video.resolve() or (project_root() / "input") in out.resolve().parents:
        raise SystemExit("Write the result to work/ or output/, never over the source or into input/.")
    info = probe(video)
    if not info.has_audio:
        raise SystemExit(f"{video.name} has no audio track to mix into.")
    fps = info.fps or 30
    cues = json.loads(args.plan.read_text(encoding="utf-8"))
    for c in cues:
        if c.get("sound") not in manifest():
            raise SystemExit(f"Unknown sound {c.get('sound')!r} in the plan. Choose from: {', '.join(sorted(manifest()))}")
        if not 0 <= float(c["at"]) <= info.duration:
            raise SystemExit(f"Cue at {c['at']} s is outside the video (0-{info.duration:.2f} s).")
        peak, _ = measure(c["sound"])
        rate = float(c.get("rate", 1.0))
        c["start"] = float(c["at"]) - peak / rate
        c["length"] = float(manifest()[c["sound"]]["duration"]) / rate
    if not cues:
        raise SystemExit("The plan has no cues.")
    out.parent.mkdir(parents=True, exist_ok=True)

    before = loudness(video)
    ceiling = max(CEILING, before[1])
    shift = 0.0
    render(video, out, cues, shift)
    after = loudness(out)
    for k in range(6):  # the cues add to the voice, so a cut of X dB lowers the sum's peak by less: cut harder each round
        if after[1] <= ceiling + 0.05:
            break
        shift -= (after[1] - ceiling + 0.3) * 2 ** k
        print(f"The mix peaked at {after[1]:.1f} dBTP; lowering every cue to {shift:.1f} dB and mixing again.")
        render(video, out, cues, shift)
        after = loudness(out)

    check = verify(video, out, cues, fps)
    report = {"video": str(video), "out": str(out), "plan": str(args.plan), "cues": len(cues), "cue_shift_db": round(shift, 1),
              "before": {"lufs": before[0], "true_peak_db": before[1]}, "after": {"lufs": after[0], "true_peak_db": after[1]},
              **check}
    if args.hf_check:
        report["hyperframes_audio"] = hf_check(out)
    rep = out.with_name(out.stem + ".sfx-report.json")
    rep.write_text(json.dumps(report, indent=1), encoding="utf-8")

    oc = check["outside_cues"]
    print(f"Mixed {len(cues)} sounds into {out} (picture copied).")
    print(f"  Loudness {before[0]:.1f} -> {after[0]:.1f} LUFS, true peak {before[1]:.1f} -> {after[1]:.1f} dBTP"
          f" ({'OK' if after[1] <= ceiling + 0.05 else 'OVER'}, limit {ceiling:.1f}).")
    print(f"  Outside the cues the audio changed by {oc['level_change_db']:+.3f} dB "
          f"(difference {oc['change_rms_db']:.1f} dBFS against speech at {oc['source_rms_db']:.1f}: codec noise only).")
    worst = max(abs(t["off_frames"]) for t in check["timing"])
    print(f"  Each cue's peak vs its planned time: within {worst:.2f} frames.")
    for t in check["timing"]:
        print(f"    {t['at']:7.2f}s  {t['sound']:<14} peak at {t['peak_at']:7.3f}s ({t['off_frames']:+.2f} frames)")
    if "hyperframes_audio" in report:
        print(f"  HyperFrames audio (local): {json.dumps(report['hyperframes_audio'].get('loudness') or report['hyperframes_audio'])}")
    print(f"Report: {rep}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as err:
        sys.exit(str(err))
