"""Mistake cuts measured on the waveform, end to end through apply-cuts.mjs --video.
Run: .venv/Scripts/python tests/test_cut_edges.py (or .venv/bin/python). Uses the setup's ffmpeg and node.

1. The clip's "words" are tone bursts with known silences between them; the transcript gives Whisper-style
   times (words touch, edges up to 50 ms off, a length 20 ms past the file as faster-whisper reports it).
   One cut starts in the middle of a kept word, one sits inside continuous sound, where only the fade can
   keep the join from clicking.
2. The auto-edit chain: the dead-air cutter (tight) first, then a retake cut that starts 0.155 s after a
   dead-air join, out of the 0.12 s reach. The cut must start on that join (no sliver of a few frames between
   two jump cuts), and the composed cut map must have no phantom pieces.
3. A run that fails leaves the last EDL as it was; an unreadable dead-air report is only a note.
4. A clip whose picture starts 28 ms after its sound: its dead-air cut has the frames after each join off the
   even grid. Six pieces, a retake with both edges on dead-air joins: the output is as long as the kept total
   within a frame, and every output frame is matched to the frame of the dead-air cut it shows, none from a
   piece that was cut.
"""
import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".claude/skills/video-editor/scripts"
sys.path.insert(0, str(SCRIPTS))
import numpy as np  # noqa: E402
from timemap import TimeMap, load  # noqa: E402
from vtools import find_tool, probe  # noqa: E402

FRAME = 1001 / 60000                                   # 59.94 fps, as the owner's camera records
FFMPEG = find_tool("ffmpeg")


def make_clip(path, sounds, frames, extra="", fps=Fraction(60000, 1001), late=0.0):
    """A test-pattern clip whose sound is a 440 Hz tone during `sounds` ((start, end) in seconds); its picture
    starts `late` seconds after the sound."""
    gate = "+".join(f"between(t\\,{a}\\,{b})" for a, b in sounds)
    cmd = [FFMPEG, "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}"]
    if sounds:
        cmd += ["-f", "lavfi", "-i", f"aevalsrc=0.4*sin(2*PI*440*t)*({gate}){extra}:s=48000:d={frames / fps:.6f}"]
    if late:
        cmd += ["-vf", f"settb=1/90000,setpts=PTS+{late}/TB", "-enc_time_base:v", "1/90000", "-fps_mode", "passthrough"]
    subprocess.run(cmd + ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", str(path)], check=True)


def gray_frames(path):
    """Every frame of a video, small and gray, with its start time (as shown, not as stored)."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "scale=80:60,format=gray", "-fps_mode",
                          "passthrough", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    times = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries",
                            "frame=pts_time", "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                           check=True).stdout.split()
    return np.frombuffer(raw, np.uint8).reshape(-1, 60, 80).astype(np.float32), [float(t.strip(",")) for t in times]


def apply_cuts(transcript, cuts, video, out_dir, *extra, ok=True):
    r = subprocess.run([find_tool("node"), str(ROOT / ".claude/skills/cut-mistakes/scripts/apply-cuts.mjs"),
                        str(transcript), "--cuts", str(cuts), "--video", str(video), "--out-dir", str(out_dir), *extra],
                       capture_output=True, text=True, cwd=ROOT)
    assert (r.returncode == 0) == ok, r.stderr
    return r


SOUND = [(0.50, 0.90), (1.00, 1.40), (1.50, 1.90), (2.40, 3.60)]    # the last one is a long tone, no word
WORDS = [("one", 0.45, 0.95), ("two", 0.95, 1.45), ("two", 1.45, 1.95)]
CUTS = [(0.75, 1.45, "planted: starts in the middle of the kept word 'one'"), (2.80, 3.10, "inside a long tone")]

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    src = d / "talk.mp4"
    make_clip(src, SOUND, 240)                                       # 4.004 s
    (d / "talk.transcript.json").write_text(json.dumps({"audio_duration_secs": 4.024, "words": [
        {"text": t, "start": a, "end": b, "type": "word"} for t, a, b in WORDS]}))
    (d / "cuts.json").write_text(json.dumps({"cuts": [{"start": a, "end": b, "reason": r} for a, b, r in CUTS]}))

    def run(*extra):
        r = apply_cuts(d / "talk.transcript.json", d / "cuts.json", src, d, *extra)
        return json.loads(r.stdout), json.loads((d / "talk.mistakes-edl.json").read_text())

    # Without --apply the edges are measured the same way, and nothing is rendered.
    dry, dry_edl = run()
    assert dry["video"]["rendered"] is False and not (d / "talk.mistakes-cut.mp4").exists(), dry
    summary, edl = run("--output", str(d / "clean.mp4"), "--apply")
    assert summary["video"]["rendered"] is True and edl["keep_ranges"] == dry_edl["keep_ranges"], (dry_edl, edl)
    keeps = [(k["start"], k["end"]) for k in edl["keep_ranges"]]
    kept = sum(b - a for a, b in keeps)

    # The edge planted in the middle of "one" moved out of it, into the silence after it.
    assert 0.90 < keeps[0][1] < 1.00, keeps
    # Every edge is on a whole frame, and the kept words are whole.
    assert all(abs(t / FRAME - round(t / FRAME)) < 1e-3 for k in keeps for t in k), keeps
    for _, a, b in (WORDS[0], WORDS[2]):
        assert any(s <= a and b <= e for s, e in keeps), (a, b, keeps)

    # The source length is the file's own, not the transcript's 20 ms longer one, so the output is as long as
    # the kept pieces within one frame, picture and sound alike.
    assert abs(edl["source_duration"] - probe(src).duration) < 1e-6, edl["source_duration"]
    out = probe(d / "clean.mp4")
    for got in (out.duration, out.video_duration, out.audio_duration):
        assert abs(got - kept) <= FRAME, (got, kept)

    # Every join has a fade: in the filter graph, and audibly at the join inside the long tone.
    graph = (d / "talk.mistakes-filter.txt").read_text()
    assert graph.count("afade=t=in") == graph.count("afade=t=out") == len(keeps), graph
    pcm = subprocess.run([FFMPEG, "-v", "error", "-i", str(d / "clean.mp4"), "-ac", "1",
                          "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.abs(np.frombuffer(pcm, "<f4"))
    j = round((keeps[0][1] - keeps[0][0] + keeps[1][1] - keeps[1][0]) * 48000)     # that join, in samples
    assert audio[j - 48:j + 48].max() < 0.15 < audio[j - 2400:j - 1200].max(), "no fade at the join"

    # The transcript is re-timed from the edges actually rendered.
    t = json.loads((d / "talk.mistakes-transcript.json").read_text())
    assert [w["text"] for w in t["words"]] == ["one", "two"] and abs(t["audio_duration_secs"] - kept) < 0.002, t
    assert abs(t["words"][1]["start"] - (1.45 - (keeps[1][0] - keeps[0][1]))) < 0.002, t

    # 2. Dead air first, as auto-edit step 2 runs it, in a project folder of its own: "so", a pause, "go" (a
    # botched take), "go" (the retake), over a faint noise floor. 218 frames = 3.636967 s.
    proj = d / "proj"
    for sub in ("input", "output"):
        (proj / sub).mkdir(parents=True)
    make_clip(proj / "input/s.mp4", [(0.50, 0.90), (1.80, 2.20), (2.40, 2.80)], 218, "+0.001*(2*random(0)-1)")
    env = dict(os.environ, PATH=str(Path(FFMPEG).parent) + os.pathsep + os.environ.get("PATH", ""))
    subprocess.run([sys.executable, str(SCRIPTS / "cut_dead_air.py"), "input/s.mp4", "--preset", "tight",
                    "--output-dir", "work"], cwd=proj, env=env, check=True, capture_output=True)
    work = proj / "work"
    report = json.loads((work / "reports/s.json").read_text())
    dead = TimeMap.from_cuts(report["cuts"], report["duration_before"])
    # The report keeps the length and the cuts unrounded, so a length that rounds up (3.637) adds no phantom
    # piece at the end: just the two pieces with sound, one join.
    assert report["duration_before"] == probe(proj / "input/s.mp4").duration and len(dead.keeps) == 2, dead.keeps
    join = dead.joins()[0]                                               # in the pause before the botched take
    # Whisper's word times on the dead-air cut's timeline. It hears the botched take start 40 ms late.
    words = [("so", 0.45, 0.95), ("go", 1.84, 2.25), ("go", 2.35, 2.85)]
    at = {x: dead.to_cut(x) for _, a, b in words for x in (a, b)}
    assert None not in at.values() and at[1.84] - join > 0.12, (at, join)       # out of reach of the word edge
    (work / "s.transcript.json").write_text(json.dumps({"audio_duration_secs": dead.duration, "words": [
        {"text": w, "start": at[a], "end": at[b], "type": "word"} for w, a, b in words]}))
    (work / "s.approved-cuts.json").write_text(json.dumps({"cuts": [
        {"start": at[1.84], "end": at[2.35], "reason": "retake: keep the second go"}]}))
    apply_cuts(work / "s.transcript.json", work / "s.approved-cuts.json", work / "s.mp4", work,
               "--output", str(work / "s.clean.mp4"), "--apply")
    edl = json.loads((work / "s.mistakes-edl.json").read_text())
    assert abs(edl["keep_ranges"][0]["end"] - join) < 1e-6, (edl["keep_ranges"], join)    # it starts on the join
    m = load("s", work)
    assert len(m.keeps) == 2 and min(b - a for a, b in m.keeps) > 3 * FRAME, m.keeps     # no sliver, no phantom
    kept = sum(k["end"] - k["start"] for k in edl["keep_ranges"])
    # The last piece runs to the file's own end, a hair past the dead-air report's: the map clips that hair.
    assert abs(probe(work / "s.clean.mp4").duration - kept) <= FRAME and abs(m.duration - kept) <= FRAME, kept

    # A kept word whose transcript edge sits a hair past the join (Whisper's rounding): the edge lands on the
    # join, inside that word's span, and the word stays in the re-timed transcript, its edge moved onto the join.
    # Left: "so" ends 30 ms past the join, the retake cut starts at the botched "go". Right: "so" is cut and the
    # kept "go" starts 10 ms before the join. Measured only (no render).
    edge = d / "edge"
    edge.mkdir()
    for side, said, cut, want in (
            ("left", [("so", at[0.45], join + 0.03), ("go", at[1.84], at[2.25]), ("go", at[2.35], at[2.85])],
             (at[1.84], at[2.35]), [("so", None, join), ("go", None, None)]),
            ("right", [("so", at[0.45], at[0.95]), ("go", join - 0.01, at[2.25]), ("go", at[2.35], at[2.85])],
             (0.0, join - 0.01), [("go", 0.0, None), ("go", None, None)])):
        (edge / f"{side}.transcript.json").write_text(json.dumps({"audio_duration_secs": dead.duration, "words": [
            {"text": w, "start": a, "end": b, "type": "word"} for w, a, b in said]}))
        (edge / f"{side}.cuts.json").write_text(json.dumps({"cuts": [{"start": cut[0], "end": cut[1]}]}))
        summary = json.loads(apply_cuts(edge / f"{side}.transcript.json", edge / f"{side}.cuts.json", work / "s.mp4",
                                        edge).stdout)
        got = json.loads((edge / f"{side}.mistakes-transcript.json").read_text())["words"]
        assert [w["text"] for w in got] == [w for w, _, _ in want] and summary["editedWords"] == len(want), (side, got)
        assert all(abs(g[k] - x) < 0.002 for g, (_, a, b) in zip(got, want) for k, x in (("start", a), ("end", b))
                   if x is not None), (side, got, join)

    # The report keeps absolute paths: after the project folder moves, the edge still finds the join.
    good = (work / "reports/s.json").read_text()
    (work / "reports/s.json").write_text(json.dumps({**report, "source": str(d / "old/input/s.mp4"),
                                                     "output": str(d / "old/work/s.mp4")}))
    apply_cuts(edge / "left.transcript.json", edge / "left.cuts.json", work / "s.mp4", edge)
    keeps = json.loads((edge / "left.mistakes-edl.json").read_text())["keep_ranges"]
    assert abs(keeps[0]["end"] - join) < 1e-6, (keeps, join)
    (work / "reports/s.json").write_text(good)
    # A dead-air preview after the render leaves the report (and so the joins) of the cut already made.
    subprocess.run([sys.executable, str(SCRIPTS / "cut_dead_air.py"), "input/s.mp4", "--analyze", "--preset", "gentle",
                    "--output-dir", "work"], cwd=proj, env=env, check=True, capture_output=True)
    assert (work / "reports/s.json").read_text() == good and load("s", work).keeps == m.keeps
    # The cut video never replaces the video being cut, under another spelling of its path either.
    before = (work / "s.mp4").read_bytes()
    os.link(work / "s.mp4", work / "alias.mp4")
    r = apply_cuts(work / "s.transcript.json", work / "s.approved-cuts.json", work / "s.mp4", work,
                   "--output", str(work / "alias.mp4"), "--apply", ok=False)
    assert "Refusing to write over the video being cut" in r.stderr and (work / "s.mp4").read_bytes() == before, r.stderr

    # 3. A half-written dead-air report only costs the join snapping, with a note.
    (work / "reports/s.json").write_text('{"cuts": [[0, 0.1]], "output": "')
    r = apply_cuts(work / "s.transcript.json", work / "s.approved-cuts.json", work / "s.mp4", work)
    assert "could not be read" in r.stderr, r.stderr
    # A run that fails (here: a video without sound) leaves the last EDL as it was.
    make_clip(d / "mute.mp4", [], 30)
    last = (d / "talk.mistakes-edl.json").read_text()
    apply_cuts(d / "talk.transcript.json", d / "cuts.json", d / "mute.mp4", d, "--output", str(d / "mute.clean.mp4"),
               "--apply", ok=False)
    assert (d / "talk.mistakes-edl.json").read_text() == last and not (d / "mute.clean.mp4").exists()

    # 4. Twelve "words" at 29.97 fps, the picture 28 ms late; three pauses become dead-air cuts.
    F30 = 1001 / 30000
    late = d / "late"
    for sub in ("input", "output"):
        (late / sub).mkdir(parents=True)
    tones = [(0.30, 0.60), (0.70, 1.00), (1.10, 1.40), (2.10, 2.40), (2.50, 2.80), (3.40, 3.70), (3.80, 4.10),
             (4.20, 4.50), (5.20, 5.50), (5.60, 5.90), (6.00, 6.30), (6.40, 6.70)]
    make_clip(late / "input/l.mp4", tones, 215, "+0.001*(2*random(0)-1)", Fraction(30000, 1001), 0.028)
    subprocess.run([sys.executable, str(SCRIPTS / "cut_dead_air.py"), "input/l.mp4", "--preset", "tight",
                    "--output-dir", "work"], cwd=late, env=env, check=True, capture_output=True)
    work = late / "work"
    report = json.loads((work / "reports/l.json").read_text())
    dead = TimeMap.from_cuts(report["cuts"], report["duration_before"])
    at = dead.to_cut
    (work / "l.transcript.json").write_text(json.dumps({"audio_duration_secs": dead.duration, "words": [
        {"text": f"w{i}", "start": at(a), "end": at(b), "type": "word"} for i, (a, b) in enumerate(tones, 1)]}))
    # Words 2, 7, 10 and 12, and the botched take (words 4-5) from its first word to the pause after it: both
    # of its edges sit in pauses that hold a dead-air join on their kept side.
    (work / "l.approved-cuts.json").write_text(json.dumps({"cuts": [
        {"start": at(a), "end": at(b), "reason": "test"} for a, b in
        ((0.70, 1.10), (2.10, 2.85), (3.80, 4.20), (5.60, 6.00), (6.40, 6.70))]}))
    apply_cuts(work / "l.transcript.json", work / "l.approved-cuts.json", work / "l.mp4", work,
               "--output", str(work / "l.clean.mp4"), "--apply")
    keeps = [(k["start"], k["end"]) for k in json.loads((work / "l.mistakes-edl.json").read_text())["keep_ranges"]]
    kept = sum(b - a for a, b in keeps)
    j1, j2 = dead.joins()[:2]                       # the dead-air joins before and after the botched take
    assert len(keeps) == 6 and j1 - 2 * F30 < keeps[1][1] <= j1 + 1e-6 and j2 - 1e-6 <= keeps[2][0] < j2 + F30, \
        (keeps, j1, j2)
    # Within a frame is the promise; the edges are the file's own frame starts, so here it is far closer (frame
    # starts taken from the average frame rate were 29 ms off on this clip).
    assert abs(probe(work / "l.clean.mp4").duration - kept) <= F30 / 4, (probe(work / "l.clean.mp4").duration, kept)
    # Each output frame, matched to the frame it shows: exactly the dead-air cut's frames inside the kept pieces,
    # and none from the dead-air piece that holds the botched take (no one-frame flash of it at the joins).
    o, _ = gray_frames(work / "l.clean.mp4")
    v, vt = gray_frames(work / "l.mp4")
    shown = [vt[int(((v - f) ** 2).mean(axis=(1, 2)).argmin())] for f in o]
    assert shown == [t for t in vt if any(a - 1e-6 <= t < b - 1e-6 for a, b in keeps)], shown
    s, st = gray_frames(late / "input/l.mp4")
    botched = dead.keeps[1]
    flash = [t for t in (st[int(((s - f) ** 2).mean(axis=(1, 2)).argmin())] for f in o) if botched[0] <= t < botched[1]]
    assert not flash, (flash, botched)
    # The cut map has no phantom piece where an edge meets a dead-air join.
    m = load("l", work)
    assert min(b - a for a, b in m.keeps) > 2 * F30, m.keeps

print("cut edges: all checks pass")
