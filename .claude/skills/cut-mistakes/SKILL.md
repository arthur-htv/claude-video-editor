---
name: cut-mistakes
description: "Agent 2 of the video editing pipeline. Finds and removes spoken mistakes — stutters, repeated words, false starts, and retakes (re-recorded lines) — from a talking-head recording. Use after cut-silences, when asked to cut mistakes, remove stutters / repeats / filler restarts, clean up flubs, or keep the best take. Works review-gated: it proposes every cut with context and a reason for approval, then renders only the approved cuts via ffmpeg. Requires a word-level transcript."
---

# Cut Mistakes & Repeats (Pipeline Agent 2)

Second step of the automated edit, run after **cut-silences**. It removes the things a human editor cuts on a second pass: stutters ("the the", "I- I-"), immediately repeated words, false starts (an abandoned phrase that restarts), and retakes (a line re-recorded — keep the clean take, drop the botched one).

Deciding what counts as a mistake is **judgment, not a formula** — emphatic repetition ("never, never") and rhetorical doubling ("the first piece is, is this…") look identical to a stutter mechanically. So this agent is **review-gated by default**: it surfaces candidates with full context; the agent (and the user) decide; only approved cuts are rendered.

## When to use

- "cut the mistakes", "remove stutters / repeats", "clean up the flubs", "keep the best take", "cut false starts"
- As the second stage of the master edit workflow, on cut-silences' output.

## The three-part flow

### 1. Find candidates (mechanical)

```bash
node .claude/skills/cut-mistakes/scripts/find-cut-candidates.mjs \
  <silence-transcript.json> --out-dir video-projects/<slug>/assets
```

Input is normally Agent 1's `<stem>.silence-transcript.json`, so cuts land on the already-silenced timeline. Writes:

- `<stem>.cut-candidates.json` — structured candidates (type, confidence, proposed `cut` range, `removes`/`keeps` text, context, recommendation)
- `<stem>.cut-candidates.md` — readable proposal

Candidate types: `stutter` (immediate word repeat), `repeat` (a 2-6 word phrase said twice in a row, such as "the biggest mistake is, the biggest mistake is"; added for this folder), `retake` (duplicate/near-duplicate segment via Jaccard similarity), `false_start` (short abandoned phrase that restarts).

In this folder you can skip the `video-projects/` setup: the local transcript from `transcribe.py --json work/<name>.transcript.json` works as the input, with `--out-dir work`. See step 4 of `.claude/skills/video-editor/references/auto-edit.md`.

### 2. Review (the gate — REQUIRED)

Read each candidate **in context** and decide keep-or-cut. The mechanical detector cannot tell intentional emphasis/rhetoric from a real flub, so do not trust `recommend` blindly — read `removes` + `context`. Common false positives: emphatic repetition ("it's never, never hands-off"), copula-then-question ("the piece is, is this…"), listing.

Present the candidates to the user with a recommendation per item; collect approvals. Write the approved cuts to a file:

```json
{ "cuts": [ { "start": 100.93, "end": 101.06, "reason": "I- false start" }, ... ] }
```

(`start`/`end` in seconds on the input transcript/video timeline. You can widen a candidate's range — e.g. for a retake, cut from the botched take's start to the clean restart.)

### 3. Apply approved cuts

```bash
node .claude/skills/cut-mistakes/scripts/apply-cuts.mjs \
  <silence-transcript.json> --cuts approved-cuts.json \
  --video video-projects/<slug>/assets/edited-silenced.mp4 \
  --output video-projects/<slug>/assets/edited-clean.mp4 --apply
```

Writes the EDL, a re-timed `<stem>.mistakes-transcript.json` (feeds the motion-graphics agent + `validate-beat-sync.mjs`), a decisions log, and — with `--apply` — the cut video. Drop `--apply` for a dry run.

With `--video`, the cut is measured on the waveform and rendered by the dead-air cutter (`.claude/skills/video-editor/scripts/cut_dead_air.py`; added for this folder):

- Each edge moves to the quietest frame start within 0.12 s of its word edge. The frame starts are read from the video file itself, so they are exact for a phone's variable frame rate and for a clip whose picture starts late too. An edge never moves into a kept word: a word counts as cut when its middle is inside the cut. An approved cut that holds no word's middle and sits inside one word is left out, and the printout says so: widen it to the whole word, or drop it. When both edges would settle on one quiet dip inside the word being cut (words that run together), the cut would remove less than half of that word's sound: it keeps its approved edges instead, and the printout names it ("no quiet point between the words at ...").
- When the video is a finished dead-air cut with its report (`work/reports/<name>.json`, status `done`), an edge moves onto a dead-air join that sits on its kept side in the same pause, however far away, and also when the transcript puts the kept word up to 50 ms past the join (Whisper rounds word times). So no sliver of a few frames is left between two jump cuts. The edge takes the frame start nearest the join on the kept side, so no frame of the piece being cut can flash. A join on the far side of any sound is never used. A failed dead-air run rewrites the report (a preview with `--analyze` leaves it alone), and then no joins are known: run the dead-air render again with `--overwrite` before this step (without it, the render is skipped and the report stays as it is). `--video` is the video the transcript was made from (in the automatic edit, the dead-air cut `work/<name>.mp4`), never a later pass: the cuts are placed by the transcript's times, and the script doesn't compare the two.
- Every join gets an 8 ms audio fade, the shared encoder (HDR stays 10-bit HEVC) and the same length and A/V sync check. The printout warns if the result is more than one frame off the kept pieces.
- The EDL, the transcript and the decisions log use the edges actually rendered and the video file's own length (a transcript's length can be a few ms off the file either way). A dry run measures them the same way and renders nothing. If the run fails, the last EDL stays as it was.

Without `--video` it edits the transcript only and needs no Python.

## Reviewing the result

Use the shared review tool to eyeball the cuts and spot-check boundaries:

```bash
node scripts/build-edl-review.mjs <stem>.mistakes-edl.json \
  --original video-projects/<slug>/assets/edited-silenced.mp4 \
  --edited   video-projects/<slug>/assets/edited-clean.mp4 \
  --output   video-projects/<slug>/assets/mistakes-review.html
npx serve video-projects/<slug>/assets -p 8080 -n   # serve only the project's assets, never the repo root (it holds .env)
```

## Notes

- A very clean delivery may yield few or zero real cuts — that's a valid outcome; don't cut natural speech to hit a quota.
- Joins don't click: every edge sits on a quiet frame start and gets an 8 ms fade (with `--video`, see above).
- Hand the `mistakes-transcript.json` + the clean video to **Agent 3 (motion graphics / tiered cards)**.
