#!/usr/bin/env python3
"""Set the voice to one steady loudness: one fixed gain to the target, peaks held under a ceiling.

Speech on YouTube, Instagram, TikTok and Spotify plays at about -14 LUFS. This pass measures the
whole sound track (EBU R128 loudness and true peak) and raises or lowers it by one fixed amount.
A limiter running at 192 kHz, so it also sees the peaks between samples, holds the loudest
syllables under the ceiling. The pauses move with the voice, never on their own, so nothing
pumps (one-pass loudnorm turns them up). The limiter costs some loudness, so the gain is found
by measuring the whole chain a few times before the one real render. A lone pop or click costs
almost nothing, but on a voice whose every syllable peaks the limiter takes more and more: once
it takes 5 dB off the voice on average, the pass stops there and reports the level it reached
rather than flatten the voice. A voice recorded on one channel only (the other 10 dB or more
quieter, or silent) is copied to both. The picture is copied untouched; the sound becomes AAC
192k at the source sample rate. The result is measured again and, if it missed, corrected and
redone once.

Examples (from the project folder; PY = .venv/Scripts/python.exe or .venv/bin/python)
  PY .claude/skills/video-editor/scripts/voice_level.py work/talk.clean.mp4 --out work/talk.v.mp4
  ... --target -16     a quieter level, for example a podcast
  ... --ceiling -1     the highest a peak may reach, in dBTP (the default -2 leaves room for sound effects)
  ... --overwrite      replace the output when it is already there
  PY .claude/skills/video-editor/scripts/voice_level.py --self-test
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cut_dead_air import output_args, run_ffmpeg  # noqa: E402
from vtools import SetupError, find_tool, probe, project_root, run  # noqa: E402

TARGET = -14.0       # LUFS
CEILING = -2.0       # dBTP: the sound effects mixed in later still fit under -1
TOLERANCE = 0.5      # LU the result may miss the target by
ONE_SIDED = 10.0     # dB: a channel this much quieter than the other carries no voice
OVERSAMPLE = 192000  # Hz the limiter runs at: the rate ebur128 measures true peaks at
MARGIN = 0.3         # dB the limiter sits under the ceiling: the AAC encode lifted peaks up to 0.1 dB in tests
MAX_LOSS = 5.0       # dB the limiter may take off the voice on average; past this it flattens the voice
                     # (measured: a real voice lands at 0.2-0.5; computer voices would need 10 or more)
SHORTEST = 0.4       # s: ebur128 measures on 400 ms blocks, so a shorter sound reads as silence
# dualmono: a mono track plays on both speakers, 3 LU louder than one channel measures; stereo is unchanged.
METER = "astats=measure_perchannel=RMS_level:measure_overall=none,ebur128=peak=true:dualmono=true:framelog=quiet"


def db(x: float) -> str:
    return f"{round(x, 1) + 0.0:.1f}"  # + 0.0 turns -0.0 into 0.0


def meter(path: Path, chain: str = "") -> dict:
    """Integrated loudness (LUFS), true peak (dBTP) and each channel's RMS level (dB) of the first
    sound track, after an optional filter chain."""
    res = run([find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-i", str(path), "-map", "0:a:0",
               "-af", ",".join(filter(None, [chain, METER])), "-f", "null", "-"])
    found = lambda pattern: [float(x) for x in re.findall(pattern, res.stderr)]  # noqa: E731
    lufs, peak = found(r"I:\s+(-?[\d.]+|-inf) LUFS"), found(r"Peak:\s+(-?[\d.]+|-inf) dBFS")
    if res.returncode != 0 or not lufs or not peak:
        raise RuntimeError(f"could not measure the sound of {path.name}: {res.stderr.strip()[-600:]}")
    return {"lufs": lufs[-1], "peak": peak[-1], "channels": found(r"RMS level dB: (-?[\d.]+|-?inf)")}


def channel_fix(levels: list[float]) -> str:
    """A pan filter copying the louder channel to both when the other is 10 dB or more quieter, else ''."""
    if len(levels) != 2 or not abs(levels[0] - levels[1]) >= ONE_SIDED:  # two silent channels give nan: no fix
        return ""
    loud = 0 if levels[0] > levels[1] else 1
    return f"pan=stereo|c0=c{loud}|c1=c{loud}"


def chain(pre: str, gain: float, limit_db: float, rate: int) -> str:
    # level=false: alimiter's auto level would lift the limited peaks back to 0 dBFS.
    # latency=true: without it the sound comes out 5 ms (the lookahead) behind the picture.
    return ",".join(filter(None, [pre, f"volume={gain:.2f}dB", f"aresample={OVERSAMPLE}",
                                  f"alimiter=limit={10 ** (limit_db / 20):.5f}:level=false:latency=true",
                                  f"aresample={rate}"]))


def find_gain(src: Path, pre: str, start: dict, target: float, limit: float, rate: int) -> tuple[float, float]:
    """The fixed gain that lands the limited sound on the target, or the lower one where the limiter
    takes MAX_LOSS off the voice on average, found by secant steps on the measured chain (nothing
    encoded). Returns the gain and what the limiter takes off the voice there, on average (dB)."""
    gain, prev = target - start["lufs"], None
    for i in range(6):
        got = meter(src, chain(pre, gain, limit, rate))["lufs"]
        loss = start["lufs"] + gain - got  # a lone pop costs ~0 here; peaks on every syllable cost a lot
        miss = max(got - target, loss - MAX_LOSS)  # rises with the gain; 0 at the gain we want
        slope = 1.0 if prev is None else max(0.2, (miss - prev[1]) / (gain - prev[0]))
        if abs(miss) <= 0.1 or abs(miss) < 0.05 * slope or i == 5:
            break
        prev, gain = (gain, miss), gain - miss / slope
    return gain, loss


def render(src: Path, out: Path, info, audio_chain: str) -> None:
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(src)]
    if info.has_video:
        cmd += ["-map", f"0:v:{info.video_index}", "-c:v", "copy"]
    # The AAC encoder's default noise substitution and intensity stereo glitched up to 2 dB over the limiter
    # on speech transients (a click; measured on 21 gains); with them off and the fast coder: within 0.1 dB.
    cmd += ["-map", "0:a:0", "-af", audio_chain, "-c:a", "aac", "-b:a", "192k", "-aac_coder", "fast",
            "-aac_pns", "0", "-aac_is", "0", "-map_metadata", "0", *output_args(out),
            "-progress", "pipe:1", "-nostats", str(out)]
    try:
        run_ffmpeg(cmd, info.duration, src.name)
    except RuntimeError as err:
        out.unlink(missing_ok=True)  # never leave a broken file where a result is expected
        if "not currently supported in container" in str(err):
            raise RuntimeError(f"The picture of {src.name} ({info.video_codec}) can't be saved as {out.suffix}. "
                               f"Save it as .mov instead (--out ending in .mov).") from None
        raise


def level(src: Path, out: Path, target: float = TARGET, ceiling: float = CEILING) -> dict:
    """Level src into out, printing each step in plain words. Returns the measurements and "ok"."""
    info = probe(src)
    if not info.has_audio:
        raise SystemExit(f"{src.name} has no sound track, so there is no voice to level.")
    rate = int(run([find_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                    "stream=sample_rate", "-of", "csv=p=0", str(src)]).stdout.split()[0])
    before = meter(src)
    if before["lufs"] <= -69.9:  # ebur128's floor: nothing it could measure
        if (info.audio_duration or info.duration) < SHORTEST:
            raise SystemExit(f"{src.name} is too short to level: its sound lasts under {SHORTEST:g} s, "
                             f"and a loudness needs at least that much to measure.")
        raise SystemExit(f"{src.name} is silent (under -70 LUFS), so there is no voice to level.")
    print(f"Voice level of {src.name}: {db(before['lufs'])} LUFS, peaks at {db(before['peak'])} dBTP.")
    pre, start = channel_fix(before["channels"]), before
    if pre:
        left, right = before["channels"]
        gap = abs(left - right)
        print(f"  The voice is on the {'left' if left > right else 'right'} channel only (the other is "
              f"{'silent' if gap == float('inf') else f'{gap:.1f} dB quieter'}): copying it to both.")
        start = meter(src, pre)
    partial = out.with_name(f"{out.stem}.partial{out.suffix}")
    limit, aim = ceiling - MARGIN, target
    for attempt in (1, 2):
        gain, loss = find_gain(src, pre, start, aim, limit, rate)
        render(src, partial, info, chain(pre, gain, limit, rate))
        after = meter(partial)
        missed, over = abs(after["lufs"] - target) > TOLERANCE, after["peak"] > ceiling
        capped = loss >= MAX_LOSS - 0.1 and after["lufs"] < target  # louder would only flatten the voice
        if attempt == 2 or not (over or (missed and not capped)):
            break
        print(f"  First try came out at {db(after['lufs'])} LUFS, peaks at {db(after['peak'])} dBTP: correcting once.")
        aim += target - after["lufs"] if missed else 0.0
        limit -= after["peak"] - ceiling + 0.1 if over else 0.0
    partial.replace(out)
    print(f"  {'Raised' if gain >= 0 else 'Lowered'} by {abs(gain):.1f} dB, the same amount all the way through.")
    squeeze = start["peak"] + gain - limit
    if squeeze > 0:
        print(f"  A limiter holds the peaks under {ceiling:g} dBTP: it takes up to {squeeze:.1f} dB off the loudest "
              f"moments and {max(loss, 0.0):.1f} dB off the voice on average.")
    ok = not (missed or over)
    if ok:
        verdict = "on target, under the ceiling."
    elif missed and capped:
        verdict = (f"MISSED: here the limiter already takes {loss:.1f} dB off the voice on average, the most "
                   f"allowed, and going louder would flatten it. --target {after['lufs']:.0f} accepts this level.")
    else:
        verdict = (f"MISSED: the aim was {target:g} LUFS (within {TOLERANCE} LU) and peaks at or under "
                   f"{ceiling:g} dBTP. The file is saved; listen to it before using it.")
    print(f"  After: {db(after['lufs'])} LUFS, peaks at {db(after['peak'])} dBTP: {verdict}")
    print(f"  {'Picture copied, not re-encoded. ' if info.has_video else ''}Saved {out}")
    return {"before": before, "after": after, "gain_db": gain, "loss_db": loss, "channel_fix": pre, "ok": ok}


def _mono(path: Path) -> np.ndarray:
    raw = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                          "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4")


def _lag(a_path: Path, b_path: Path, w: int = 80) -> int:
    """Samples at 8 kHz that b's sound runs late against a's, searched within w samples (10 ms)."""
    a, b = _mono(a_path), _mono(b_path)
    n = min(len(a), len(b))
    return max(range(-w, w + 1), key=lambda k: float(np.dot(a[w:n - w], b[w + k:n - w + k])))


def self_test() -> int:
    inf = float("-inf")
    assert channel_fix([-20.0, -20.0]) == "" and channel_fix([-20.0, -29.9]) == ""
    assert channel_fix([-20.0, -30.0]) == "pan=stereo|c0=c0|c1=c0"
    assert channel_fix([inf, -25.0]) == "pan=stereo|c0=c1|c1=c1"
    assert channel_fix([inf, inf]) == "" and channel_fix([-20.0]) == "" and channel_fix([-20.0] * 6) == ""
    assert db(-0.04) == "0.0" and db(-14.06) == "-14.1" and db(1.25) == "1.2"
    ffmpeg = find_tool("ffmpeg")
    # Noise, not a tone, so the sync check has one clear match; low-passed below (speech has little energy
    # up high, and white noise loses 1 LU in the AAC encode, which would blur the checks).
    voice = "(random(0)-0.5)*(0.6+0.4*sin(2*PI*3*t))"
    click = "sin(2*PI*1000*t)*lt(mod(t,0.5),0.001)"       # 1 ms bursts, like plosives on a hot mic
    pop = "1.2*sin(2*PI*167*t)*between(t,1.5,1.503)"      # one 3 ms bump, a breath into the mic
    buzz = "sin(2*PI*1000*t)*lt(mod(t,0.012),0.0005)"     # a peak every 12 ms: the limiter never lets go
    clips = {"one-sided": f"{voice}|0",                                       # about -20 LUFS, left only
             "hot": f"0.9*{voice}+1.2*{click}|0.9*{voice}+1.2*{click}",       # about -17 LUFS, peaks over 0 dBTP
             "pop": f"0.4*{voice}+{pop}|0.4*{voice}+{pop}",                   # about -24 LUFS, one pop near 0 dBTP
             "dense": f"0.1*{voice}+0.9*{buzz}|0.1*{voice}+0.9*{buzz}"}       # peaks everywhere: can't reach -14
    video_md5 = lambda p: run([ffmpeg, "-v", "error", "-i", str(p), "-map", "0:v", "-c", "copy",  # noqa: E731
                               "-f", "md5", "-"]).stdout.strip()
    got = {}
    with tempfile.TemporaryDirectory() as d:
        def make(name: str, expr: str, secs: float = 3, ext: str = ".mp4",
                 video: tuple = ("libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p")) -> Path:
            src = Path(d) / f"{name}{ext}"
            made = run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=160x120:r=25:d={secs}",
                        "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={secs},lowpass=f=4000",
                        "-c:v", *video, "-c:a", "aac", "-b:a", "192k", str(src)])
            assert made.returncode == 0, made.stderr
            return src

        for name, expr in clips.items():
            src, out = make(name, expr), Path(d) / f"{name}.v.mp4"
            r = got[name] = level(src, out)
            ch = r["after"]["channels"]
            assert r["after"]["peak"] <= CEILING and len(ch) == 2 and abs(ch[0] - ch[1]) < 0.5, r
            md5 = video_md5(src)
            assert md5 and md5 == video_md5(out), "the picture was re-encoded"
            pi, po = probe(src), probe(out)
            assert abs(pi.video_start - po.video_start) < 1e-3 and abs(pi.video_duration - po.video_duration) < 1e-3
            assert abs(pi.audio_start - po.audio_start) < 2e-3 and abs(_lag(src, out)) <= 1, "sound moved against the picture"
        try:
            level(make("short", f"{voice}|{voice}", 0.3), Path(d) / "short.v.mp4")
            raise AssertionError("a 0.3 s clip was levelled")
        except SystemExit as err:
            assert "too short" in str(err), err
        try:
            level(make("prores", f"{voice}|{voice}", 1, ".mov", ("prores_ks", "-profile:v", "0")), Path(d) / "prores.v.mp4")
            raise AssertionError("a ProRes picture went into an .mp4")
        except RuntimeError as err:
            assert ".mov" in str(err) and not list(Path(d).glob("prores.v*")), err  # a hint, and no broken file left
        # A mono voice is measured as it plays on two speakers: the same as its copy on both channels.
        mono = make("mono", voice, 1)
        assert abs(meter(mono)["lufs"] - meter(mono, "pan=stereo|c0=c0|c1=c0")["lufs"]) < 0.2
        # A source named like the temporary file of --out is refused, not deleted by a failed render.
        src = mono.replace(Path(d) / "talk.partial.mp4")
        argv = sys.argv
        sys.argv = ["voice_level.py", str(src), "--out", str(Path(d) / "talk.mp4")]
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                main()
            raise AssertionError("a source named like the temporary file was taken")
        except SystemExit as err:
            assert err.code == 2 and src.is_file(), err
        finally:
            sys.argv = argv
    one, hot, pop_, dense = got["one-sided"], got["hot"], got["pop"], got["dense"]
    assert one["channel_fix"] and abs(one["before"]["lufs"] + 20) < 1.5 and one["before"]["channels"][1] == inf
    assert hot["before"]["peak"] > 0 and not hot["channel_fix"]
    for r in (one, hot, pop_):
        assert r["ok"] and abs(r["after"]["lufs"] - TARGET) <= TOLERANCE, r
    # One pop needed over 10 dB off and still landed: it costs the voice almost nothing on average.
    assert pop_["before"]["peak"] + pop_["gain_db"] - CEILING > 10 and pop_["loss_db"] < 1, pop_
    assert not dense["ok"] and dense["after"]["lufs"] < TARGET - TOLERANCE, dense  # reported, not flattened
    assert dense["loss_db"] >= MAX_LOSS - 0.1, dense
    print("voice_level self-test: OK")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Set the voice to one steady loudness: one fixed gain, peaks limited.")
    p.add_argument("video", type=Path, nargs="?")
    p.add_argument("--out", type=Path, help="default: work/<video-stem>.v.mp4 (.v.mov for a .mov)")
    p.add_argument("--target", type=float, default=TARGET, help="loudness in LUFS (default -14)")
    p.add_argument("--ceiling", type=float, default=CEILING, help="highest true peak in dBTP (default -2)")
    p.add_argument("--overwrite", action="store_true", help="replace the output when it is already there")
    p.add_argument("--self-test", action="store_true", help="run the built-in checks on synthetic clips")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if not args.video:
        p.error("give the video, or --self-test")
    if not -40 <= args.target <= -5:
        p.error("--target is in LUFS, between -40 and -5 (for example -14)")
    if not -20 <= args.ceiling <= 0:
        p.error("--ceiling is in dBTP, between -20 and 0 (for example -2)")
    if not args.video.is_file():
        p.error(f"not found: {args.video}")
    # A .mov holds every picture a .mov source can carry (ProRes, for one); an .mp4 does not.
    suffix = ".mov" if args.video.suffix.lower() == ".mov" else ".mp4"
    out = args.out or project_root() / "work" / f"{args.video.stem}.v{suffix}"
    if out.resolve() == args.video.resolve() or (project_root() / "input").resolve() in out.resolve().parents:
        p.error("write the result to work/ or output/, never over the source or into input/")
    if out.with_name(f"{out.stem}.partial{out.suffix}").resolve() == args.video.resolve():  # level() renders there
        p.error(f"{args.video.name} is the temporary file this pass writes before {out.name}: pick another --out")
    if out.exists() and not args.overwrite:
        p.error(f"{out} is already there: add --overwrite to replace it, or pick another --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    return 0 if level(args.video, out, args.target, args.ceiling)["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SetupError, RuntimeError) as err:
        sys.exit(str(err))
