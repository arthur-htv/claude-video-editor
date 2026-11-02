#!/usr/bin/env node
// Agent 2 — Cut Mistakes & Repeats : apply approved cuts
// Takes an APPROVED cut list (produced after the review-gate) + the input
// transcript + video, removes those ranges, re-times the transcript, and
// optionally renders the cut video (ffmpeg trim+concat, A/V kept in sync).
// [claude-video-editor patch] With --video, the edges are measured on the waveform
// and the video is rendered by video-editor/scripts/cut_dead_air.py (see below).
//
// Approved-cuts file shape: { "cuts": [ { "start": <s>, "end": <s>, "reason": "..." }, ... ] }
//   (start/end in seconds on the INPUT transcript/video timeline)
//
// Outputs (next to the transcript, or --out-dir):
//   <stem>.mistakes-edl.json          keep/delete ranges + summary
//   <stem>.mistakes-transcript.json   words re-timed onto the new timeline
//   <stem>.mistakes-decisions.md      what was removed + why
//   <stem>.mistakes-filter.txt        ffmpeg filtergraph (with --video)
//   <video-stem>.mistakes-cut.mp4     the cut video (with --apply)
//
// Usage:
//   node apply-cuts.mjs <transcript.json> --cuts <approved.json> \
//     [--video in.mp4] [--output out.mp4] [--out-dir dir] [--apply]

import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync, rmSync } from "node:fs";
import { dirname, join, resolve, basename, extname } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { argv, exit } from "node:process";

function die(m, c = 1) { console.error(m); exit(c); }

const args = argv.slice(2);
if (args.length === 0 || args.includes("--help")) {
  console.log("Usage: node apply-cuts.mjs <transcript.json> --cuts <approved.json> [--video in.mp4] [--output out.mp4] [--out-dir dir] [--apply]");
  exit(args.length === 0 ? 1 : 0);
}
const opts = { transcript: null, cuts: null, video: null, output: null, outDir: null, apply: false };
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--cuts") opts.cuts = args[++i];
  else if (a === "--video") opts.video = args[++i];
  else if (a === "--output" || a === "-o") opts.output = args[++i];
  else if (a === "--out-dir") opts.outDir = args[++i];
  else if (a === "--apply") opts.apply = true;
  else if (a.startsWith("--")) die(`unknown option: ${a}`);
  else if (!opts.transcript) opts.transcript = a;
}
if (!opts.transcript) die("no transcript given");
if (!opts.cuts) die("no --cuts file given");

const readJson = (p) => {
  try { return JSON.parse(readFileSync(resolve(p), "utf8")); }
  catch (e) { die(`${p} isn't valid JSON (${e.message}). Fix it, then run this again.`); }
};
const transcriptPath = resolve(opts.transcript);
const transcript = readJson(transcriptPath);
const cutsDoc = readJson(opts.cuts);
const approved = cutsDoc.cuts ?? cutsDoc;
if (!Array.isArray(approved)) die('cuts must be an array (an empty array is valid)');
if (approved.some(c => !c || typeof c.start !== 'number' || typeof c.end !== 'number' || !Number.isFinite(c.start) || !Number.isFinite(c.end) || c.end <= c.start)) die('Every cut range needs finite numeric start < end');
if (!Array.isArray(transcript.words)) die('transcript has no words array');

const words = transcript.words
  .filter((w) => (w.type ? w.type === "word" : true))
  .filter((w) => Number.isFinite(Number(w.start)) && Number.isFinite(Number(w.end)))
  .map((w) => ({ text: w.text, start: Number(w.start), end: Number(w.end) }));
if (!words.length) die('transcript has no timed words');

let duration = Number(transcript.audio_duration_secs);
if (!Number.isFinite(duration)) {
  if (opts.video && existsSync(resolve(opts.video))) {
    const p = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", resolve(opts.video)]);
    duration = Number(p.stdout?.toString().trim());
  }
  if (!Number.isFinite(duration)) duration = words.at(-1).end + 0.2;
}
if (!Number.isFinite(duration) || duration <= 0) die('Invalid source duration');
if (approved.some(c => c.start < 0 || c.end > duration)) die('Cut range is outside source duration bounds');

function mergeRanges(ranges) {
  const sorted = ranges.map((r) => ({ start: Number(r.start), end: Number(r.end), reasons: r.reason ? [r.reason] : [] }))
    .sort((a, b) => a.start - b.start);
  const merged = [];
  for (const r of sorted) {
    const last = merged.at(-1);
    if (!last || r.start > last.end) merged.push({ ...r });
    else { last.end = Math.max(last.end, r.end); last.reasons.push(...r.reasons); }
  }
  return merged;
}
const mergedDeletes = mergeRanges(approved);

const keepRanges = [];
let cursor = 0;
for (const d of mergedDeletes) {
  if (d.start > cursor) keepRanges.push({ start: cursor, end: d.start });
  cursor = Math.max(cursor, d.end);
}
if (cursor < duration) keepRanges.push({ start: cursor, end: duration });
const usableKeepRanges = keepRanges.filter((r) => r.end > r.start);
if (!usableKeepRanges.length) die('Cut ranges remove the entire source duration');

const stem = basename(transcriptPath, extname(transcriptPath)).replace(/[-.]?(silence-|mistakes-)?transcript.*$/i, "") || "source";
const outDir = opts.outDir ? resolve(opts.outDir) : dirname(transcriptPath);
mkdirSync(outDir, { recursive: true });

// [claude-video-editor patch] With --video, cut_dead_air.py measures and renders the cut, so mistake cuts join
// like dead-air cuts: each edge moves to the quietest frame start within 0.12 s of its word edge (never
// inside a kept word), or onto a dead-air cut in the same pause, every join gets an 8 ms fade, and the video
// goes through the shared encoder (HDR kept) and its length and sync check. Everything below then uses the
// edges it rendered and the video's own length. No --video: no Python.
let deletes = mergedDeletes, keeps = usableKeepRanges, video = null;
if (opts.video) {
  const videoPath = resolve(opts.video);
  if (!existsSync(videoPath)) die(`--video not found: ${videoPath}`);
  const outputPath = resolve(opts.output ?? join(outDir, `${basename(videoPath, extname(videoPath))}.mistakes-cut.mp4`));
  if (outputPath === videoPath) die('Output must be a different path from the source video');
  // A later pass than the transcript's video has other times: its words would be cut in the wrong places.
  const probed = Number(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', videoPath]).stdout?.toString().trim());
  const said = Number(transcript.audio_duration_secs);
  if (Number.isFinite(probed) && probed > 0 && Number.isFinite(said) && Math.abs(probed - said) > 0.5)
    die(`${basename(videoPath)} is ${probed.toFixed(2)} s long, but the transcript is from a ${said.toFixed(2)} s video. --video must be the video the transcript was made from (in the automatic edit, the dead-air cut work/<name>.mp4).`);
  const root = resolve(import.meta.dirname, '../../../..');
  const python = [join(root, '.venv/Scripts/python.exe'), join(root, '.venv/bin/python')].find((p) => existsSync(p));
  if (!python) die("The project's Python (.venv) was not found: run the setup first (see README.md).");
  // Python measures the keeps in a scratch file, so a failed run leaves the last EDL as it was.
  const keepsPath = join(mkdtempSync(join(tmpdir(), 'apply-cuts-')), 'keeps.json');
  writeFileSync(keepsPath, JSON.stringify({ source_duration: duration, keep_ranges: keeps }));
  const py = spawnSync(python, [join(root, '.claude/skills/video-editor/scripts/cut_dead_air.py'), videoPath,
    '--keeps', keepsPath, '--words', transcriptPath, '--graph', join(outDir, `${stem}.mistakes-filter.txt`),
    ...(opts.apply ? ['--render', outputPath] : [])], { stdio: ['ignore', 2, 'inherit'] });   // its messages go to stderr
  const measured = py.status === 0 ? JSON.parse(readFileSync(keepsPath, 'utf8')) : null;
  rmSync(dirname(keepsPath), { recursive: true, force: true });
  if (!measured) die(`cutting the mistakes failed (${py.error?.message ?? 'see the message above'}); the last cut list is unchanged`, py.status || 1);
  ({ keep_ranges: keeps, source_duration: duration } = measured);
  deletes = [];    // the cuts made: the gaps between the kept pieces, with the reasons of the approved cuts in them
  let pos = 0;
  for (const k of [...keeps, { start: duration, end: duration }]) {
    if (k.start - pos > 1e-3) deletes.push({ start: pos, end: k.start, reasons: mergedDeletes.filter((d) => d.start < k.start && d.end > pos).flatMap((d) => d.reasons) });
    pos = k.end;
  }
  video = { input: videoPath, output: outputPath, rendered: opts.apply };
}

const removedTotal = deletes.reduce((s, r) => s + (r.end - r.start), 0);
const editedDuration = Number((duration - removedTotal).toFixed(3));

function removedBefore(t) {
  let removed = 0;
  for (const d of deletes) {
    if (d.end <= t) removed += d.end - d.start;
    else if (d.start < t) removed += t - d.start;
    else break;
  }
  return removed;
}
// With --video an edge can sit up to 50 ms inside a kept word (on a dead-air join), so a word counts as cut by
// its middle, as cut_dead_air.py decides it; removedBefore() then puts its trimmed edge on the join.
const inDeleted = (w) => deletes.some((d) => video
  ? d.start <= (w.start + w.end) / 2 && (w.start + w.end) / 2 <= d.end
  : w.start < d.end && d.start < w.end);

const editedWords = [];
for (const w of words) {
  if (inDeleted(w)) continue;
  editedWords.push({
    text: w.text,
    source_start: w.start, source_end: w.end,
    start: Number((w.start - removedBefore(w.start)).toFixed(3)),
    end: Number((w.end - removedBefore(w.end)).toFixed(3)),
  });
}

function fmt(s) { const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(2).padStart(5, "0")}`; }

const edl = { agent: "cut-mistakes", source_duration: duration, edited_duration: editedDuration, removed: Number(removedTotal.toFixed(3)), delete_ranges: deletes, keep_ranges: keeps };
const transcriptOut = { language_code: transcript.language_code, source_audio_duration_secs: duration, audio_duration_secs: editedDuration, produced_by: "cut-mistakes", words: editedWords };

writeFileSync(join(outDir, `${stem}.mistakes-edl.json`), JSON.stringify(edl, null, 2));
writeFileSync(join(outDir, `${stem}.mistakes-transcript.json`), JSON.stringify(transcriptOut, null, 2));
writeFileSync(join(outDir, `${stem}.mistakes-decisions.md`), [
  "# Cut-Mistakes Decisions (applied)",
  "",
  `Input duration: ${fmt(duration)} (${duration.toFixed(2)}s)`,
  `Output duration: ${fmt(editedDuration)} (${editedDuration.toFixed(2)}s)`,
  `Removed: ${removedTotal.toFixed(2)}s across ${deletes.length} cuts`,
  "",
  ...deletes.map((d) => `- ${fmt(d.start)}–${fmt(d.end)} (${(d.end - d.start).toFixed(2)}s): ${d.reasons.join("; ") || "approved cut"}`),
].join("\n"));

const summary = {
  inputDuration: Number(duration.toFixed(3)), editedDuration,
  removed: Number(removedTotal.toFixed(3)), removedPct: Number(((removedTotal / duration) * 100).toFixed(1)),
  cuts: deletes.length, editedWords: editedWords.length, outDir,
};

if (video) {
  summary.video = video;
  if (!opts.apply) summary.hint = "re-run with --apply to render";
}

console.log(JSON.stringify(summary, null, 2));
