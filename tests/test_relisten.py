"""Re-listen check with the real speech model. Run: .venv/Scripts/python tests/test_relisten.py (Windows: it
makes computer speech with the built-in voice). Takes a few minutes: the large-v3 model hears two short cuts.

The cuts are made the pipeline's way: step 4's apply-cuts.mjs writes the cut list and the words (it leaves out
every word a cut touches), and cut_dead_air.render cuts the video with its 8 ms fades.
- clean: one cut from pause to pause must pass, and only the 3 s around its join may be heard (plus the same
  places in the uncut work/<name>.mp4, to compare with).
- mixed: cuts through "busi|ness" and "|Then" must each be caught at their own join, while a third cut inside a
  pause, in the same video, must have no finding.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
S = REPO / ".claude/skills/video-editor/scripts"
APPLY = REPO / ".claude/skills/cut-mistakes/scripts/apply-cuts.mjs"
sys.path.insert(0, str(S))
from cut_dead_air import HOP, measure_loudness, render, runs  # noqa: E402
from transcribe import kit_transcript, transcribe_words  # noqa: E402
from vtools import find_tool, probe, run  # noqa: E402

SAY = """Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile($args[0])
$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendText('We started the business in a small garage behind the house.')
$p.AppendBreak([TimeSpan]::FromMilliseconds(700))
$p.AppendText('Every customer got a handwritten thank you note from us.')
$p.AppendBreak([TimeSpan]::FromMilliseconds(700))
$p.AppendText('Then we grew it month after month without outside money.')
$p.AppendBreak([TimeSpan]::FromMilliseconds(700))
$p.AppendText('Now we ship to twelve countries.')
$s.Speak($p)
$s.Dispose()
"""


def relisten(work, name, words, duration, cuts):
    """Cut work/<name>.mp4 the way step 4 does, then re-listen to the result: (exit code, report)."""
    shutil.copyfile(work / "talk.mp4", work / f"{name}.mp4")
    (work / f"{name}.transcript.json").write_text(json.dumps(kit_transcript(words, duration)), encoding="utf-8")
    (work / f"{name}.approved-cuts.json").write_text(json.dumps(
        {"cuts": [{"start": a, "end": b, "reason": "test"} for a, b in cuts]}), encoding="utf-8")
    res = run([find_tool("node"), str(APPLY), str(work / f"{name}.transcript.json"), "--cuts",
               str(work / f"{name}.approved-cuts.json"), "--out-dir", str(work)])
    assert res.returncode == 0, res.stderr
    edl = json.loads((work / f"{name}.mistakes-edl.json").read_text(encoding="utf-8"))
    video = work / f"{name}.clean.mp4"
    render(probe(work / f"{name}.mp4"), [(k["start"], k["end"]) for k in edl["keep_ranges"]], video,
           work / "graph.txt", 23, "ultrafast")
    res = subprocess.run([sys.executable, str(S / "relisten.py"), str(video), "--words",
                          str(work / f"{name}.mistakes-transcript.json"), "--work", str(work)], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(res.stdout + res.stderr)
    return res.returncode, json.loads((work / f"{name}.relisten.json").read_text(encoding="utf-8"))


def main() -> int:
    if os.name != "nt":
        print("relisten model test: skipped (it makes its speech with the Windows voice)")
        return 0
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        (work / "say.ps1").write_text(SAY, encoding="utf-8")
        wav = work / "speech.wav"
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(work / "say.ps1"),
                        str(wav)], check=True)
        res = run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=30", "-i",
                   str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                   str(work / "talk.mp4")])
        assert res.returncode == 0, res.stderr

        info = probe(work / "talk.mp4")
        db = measure_loudness(info)
        pauses = [(s + e) / 2 * HOP for quiet, s, e in runs(db < -45) if quiet and e - s > 50 and 0 < s and e < db.size]
        assert len(pauses) == 3, pauses                       # the three pauses between the sentences
        words, _ = transcribe_words(wav, "small", "en")       # the model step 3 of the auto edit uses

        def inside(text):                                     # the loudest 10 ms of a word: mid-word for sure
            w = next(w for w in words if w["word"].strip(".,").lower() == text)
            a, b = int(w["start"] / HOP), int(w["end"] / HOP)
            return round((a + int(db[a:b].argmax()) + 0.5) * HOP, 3)

        code, rep = relisten(work, "clean", words, info.duration, [(pauses[0], pauses[1])])
        assert code == 0 and rep["findings"] == [], rep["findings"]
        assert Path(rep["compared_with"]).name == "clean.mp4", rep     # heard against the uncut video, not W
        assert rep["uncut_heard_seconds"] < info.duration, rep          # only around the cut's two edges there too
        assert rep["heard_seconds"] <= 3.0 + 1e-6 < rep["duration"], rep          # only the 3 s around the join

        p = pauses[2]
        code, rep = relisten(work, "mixed", words, info.duration,
                             [(inside("business"), pauses[0]), (pauses[1], inside("then")), (p - 0.15, p + 0.15)])
        assert code == 1 and len(rep["joins"]) == 3, (code, rep["joins"])
        busi, then, pause = rep["joins"]
        found = {f["join"] for f in rep["findings"]}
        assert busi in found and then in found and pause not in found, rep["findings"]
        assert all(f["cut"].startswith("mistake cut") for f in rep["findings"]), rep["findings"]
        assert rep["heard_seconds"] < rep["duration"], rep
    print("relisten model test: all checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
