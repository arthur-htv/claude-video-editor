---
name: talking-head-recut
description: Direct the graphics of a talking-head video. Read the transcript, plan a designed card for each moment that deserves one (title, stat, key points, name, quote, full-screen statement) timed to the exact word, show the plan for an OK, then write each card's HTML and render it over the untouched video. Apple-style clean look built in. Use it whenever the user wants the edit "directed", custom or designed graphics, cards, lower thirds, callouts, "Apple style", "clean", "premium", "keynote", "super clean motion graphics", or says the templates look generic. It is the graphics step of /video-editor:auto.
---

# Talking-head recut: directed cards

The speaker's video plays untouched. You are the director: you decide which moments get a graphic, what it says, where it sits and the frame it lands on, and you design each card by hand (HTML and GSAP) instead of filling a fixed template. Rendering is local: HyperFrames turns each card into a transparent clip, and FFmpeg lays them all over the video in one encode. No account, no paid service.

Adapted from HeyGen HyperFrames' `talking-head-recut` (retired upstream on 2026-10-21; its measured numbers now live in the hyperframes skill's `references/overlays.md`) and from vtake-skills. See `NOTICE.md`.

`PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`. `T` = `.claude/skills/motion-templates/scripts`. Run everything from the project folder.

## 1. Inputs

- `V`: the video that gets the cards. In `/video-editor:auto` it is the file after the cuts; on its own, a file in `input/`.
- `W`: its word timings, `work/<name>.words.json`. Missing? `PY .claude/skills/video-editor/scripts/transcribe.py V --out work/<name>.srt --words --json work/<name>.transcript.json`
- Where the face is: the face box measured in auto-edit step 1 (`face found at x 0.35-0.62, y 0.14-0.30`), and the source sheet `work/<name>.source-check.png` to see the rest of the frame.

## 2. Write the director's plan

Read the whole transcript before choosing anything. Then write `work/<name>.director.md`, one row per graphic, with times taken from `W`:

| # | In → out | Lands on (words said) | Graphic | Where | Shows |
|---|---|---|---|---|---|
| 1 | 0:08.40 → 0:10.85 | "free" · "10 minutes" | stat card | over the speaker | EIN from the IRS · 10 min · Free |
| 2 | 0:27.80 → 0:30.60 | "90 days" | statement card | full screen | In about 90 days · you'll have a business credit score |

**What earns a graphic:** a number, a name or term, a claim worth remembering, a list or a choice, a contrast, a definition, a payoff. Greetings, filler and repeats get nothing. The face is the best graphic, so leave stretches clear.

**How many:** start from one graphic every 6 to 8 s under a minute, 8 to 12 s up to 3 minutes, 12 to 20 s up to 10 minutes. Use fewer (×1.5 the gap) for a slow story and more (×0.7) when the talk is dense with numbers and lists.

**Which tool for which moment** (all in one look):

| The speaker... | Use |
|---|---|
| walks through a process that branches or has 5+ steps | `flowchart` (motion-templates) |
| goes through up to 4 steps in a row (with the `apple` look, prefer this over a flowchart unless asked for a diagram) | a staged checklist card: each step arrives on its word and ticks off when the next begins |
| opens with a promise | `hook-title`, a `title-card` (calm or lockup), or a title card you design |
| names a person (themselves or a guest) and their role | `lower-third` (motion-templates), or a name card you design |
| points at something in the frame | `annotate` (motion-templates): a hand-drawn circle or underline |
| says one big number or word with weight, standing still, with wall around the head | `text-behind`: the word goes behind the speaker (instead of a full-screen statement card for that moment) |
| ends with "save this" / "follow" | `cta`, or an end card you design |
| compares amounts, or gives a share of a whole | a `morph-shapes` chart |
| says anything else worth a graphic: a stat, a list, A vs B, a term, a quote, a payoff | a card you design (this skill) |

**Timing, to the word:**
- A card comes in 0.15 to 0.25 s before the first word it shows, so it is readable as the word is heard. Each piece inside a card enters on its own word: card time = word start − card start − 0.15.
- It leaves at the end of its sentence, after 2.5 to 8 s. A card on screen longer than 8 s keeps revealing new parts; past about 15 s, split it.
- One card at a time, with at least 0.5 s between cards. The last card ends before the video does.
- When these clash (sentences that run together), keep no-overlap and the 0.5 s gap first, then landing on the word. The card's end gives way first: end it 0.5 s before the next card starts. Then a count-up shortens (not below 0.8 s) rather than starting earlier.

**Where** (vertical 1080×1920; scale for other sizes):
- **Over the speaker** (the default): a panel between the chin and the captions. The top edge sits below the face box plus 0.05 of the height. The bottom edge stays at or above 0.72 of the height when captions sit at the bottom. The sides have 7% margins.
- **Wide video:** the bottom 30% (a lower third), or a side panel on the right 42%, on the side away from the face.
- **Full screen** (`"mode": "cutaway"`): a big statement, a payoff number or dense data. Hold it 2.5 to 4 s, at most one every 20 s. The voice keeps going.

## 3. Show the plan, then wait

Show the table and ask the user to reply OK or change any line. This is the one stop in `/video-editor:auto`: directing is a creative call worth one look before about two minutes of rendering. Skip the stop only when the user said to decide everything ("no questions", "surprise me"), and say so in the report.

## 4. The look

Use one look for the whole video, shared with any templates through `--theme`:
- **`apple`**: black ground, Inter, one blue accent, dark glass panels, soft shadows. It is the default when the user asks for Apple, clean, premium, minimal or keynote. Captions: `--style apple`.
- **`blueprint`, `midnight`, `paper`**: the motion-templates themes. Cards use the same variables, so they follow along.
- **A different look:** `references/styles/*.html` holds 10 reference cards: academic, audit, editorial, geom, minimal, spotlight, swiss, terminal, whiteboard and xhs.
  - Take their palette, type scale and ornaments.
  - They are 1920×1080 landscape cards, so scale the type ×1.3 for vertical.
  - Replace their `data-anim` attributes with GSAP lines.
  - Their fonts aren't bundled, so use a bundled one.

**The Apple look in numbers** (vertical, `u` = 1080 px):
- **Type:** Inter. Headlines are weight 700 with tracking −0.025em and line height 1.02 to 1.1, at 0.065u to 0.09u. Stats are 0.17u to 0.22u. Labels are weight 600 at 0.034u to 0.04u in `--muted`. Use two weights per card at most, and no all-caps headlines.
- **Colour:** `--text` (#f5f5f7) on `--panel` (dark glass) with one `--accent` (#2997ff). `--good` and `--bad` only carry meaning. One hero number per video may use a blue-to-purple gradient (`background-clip:text`).
- **Surface:**
  - Use `--panel`, a 1 px `--line` hairline, `--radius` corners and the `--glow` shadow.
  - Skip backdrop blur. The card renders apart from the video, so there is nothing behind it to blur.
- **Space:** padding of 0.05u to 0.06u, one idea per card, about 12 words at most.
- **Motion** (exact recipes in the `cut-the-curve` skill and its tested `examples/`):
  - **Entrances:** 0.6 s (0.5 to 0.7) with `expo.out` or `power4.out`. A panel rises 40 px and its blur clears from 14 px to 0. Bare text clears from 10 px. A part arriving on its word rises 24 px in 0.5 s.
  - **Stagger:** parts 0.06 to 0.1 s apart.
  - **Payoff:** a full-screen payoff or hero number lands with the inverse zoom: scale 1.25 → 1, blur 10 px → 0, 0.5 s `expo.out`. Leave 0.3 to 0.75 s of stillness before it when the speech allows.
  - **Count-up:** 1.2 to 1.6 s, landing on the spoken number.
  - **Exit:** a 0.35 s fade, added for you (exits run 50 to 75% of the entry).
  - **Never:** bounce (`back`, `elastic`) or spin. Nothing is faster than 0.25 s, except words inside a waterfall cascade. No idle drift or creeping scale once a card is in.

## 5. Write each card

One file per card, `work/cards/<id>.html`, holding the markup, one `<style>` and one `<script>`. Copy the closest example from `examples/` and change it:
- **`c01-stat.html`:** a stat over the speaker, with a count-up and a pill.
- **`c02-options.html`:** a 13 s card that reveals in stages: a title, then two options with icons, each arriving on its word.
- **`c03-statement.html`:** a full-screen statement with a gradient hero number.

Rules:
- **Classes:** start every class with the card id (`.c04-...`).
- **Sizes:** use `calc(var(--u)*...)` for sizes and `%` of the canvas for positions, so a card fits any resolution. The canvas is the video's own size (1080×1920 for a phone video).
- **Theme variables:** `--text --muted --accent --on-accent --panel --line --radius --glow --shadow --good --bad --tile --font-display --font-body`.
- **Helper classes:** `.panel .pill .tile .disp .acc .good .bad`.
- **Icons:** `[[icon:name]]` takes a file name from `motion-templates/assets/icons` (`credit-card`, `clock`, `check` and so on). The icon takes the text colour and is 1em tall.
- **Script:**
  - Write GSAP lines on `tl` only, at times in seconds from the card's start.
  - Prefer `tl.fromTo(...)` for anything that appears, so every frame renders right when the renderer jumps to it. `tl.to(...)` is fine for changing something already on screen (dim, swap, move).
  - Count-up: `tl.fromTo(el,{innerText:0},{innerText:N,duration:1.4,ease:"power2.out",snap:{innerText:1}},at)`.
  - No timers, randomness or network calls.
- **Staged cards:** hidden parts still take their space, so a card that reveals in stages can open as a half-empty panel. Start the card on its first piece, and show the coming rows faintly (numbers or placeholders at about 25% opacity) so the panel reads as a list being filled.
- **Self-contained:** no web links; the render refuses them. Bundled fonts: Inter (400, 600, 700), Montserrat XB, Abril Fatface, Architects Daughter.

List each card in `work/<name>.templates.json`, next to any templates:

```json
{"template": "card", "start": 8.4, "end": 10.85, "file": "work/cards/c01.html", "checks": [9.0, 10.5]}
{"template": "card", "start": 27.8, "end": 30.6, "file": "work/cards/c03.html", "mode": "cutaway"}
```

`checks` are the video times worth a look (each reveal). `"mode"` is `"overlay"` (the default) or `"cutaway"`.

## 6. Render and check

**Preview one card fast, without the video:**
```
PY T/build_template.py work/c01.json --size 1080x1920 --theme apple
```
Its spec goes in its own file. This writes `work/previews/tpl-card-*.webm` (an `.mp4` for a cutaway card) and `work/tpl-card-*.check.png`.

**All of them over the video, in one encode** (about 20 to 40 s per card):
```
PY T/build_template.py work/<name>.templates.json --video V --theme apple --out work/<name>.t.mp4
```

Look at `work/<name>.t.templates-check.png`. Every card should be on its word and readable, with the face and mouth clear, nothing under the captions, and no line wrapping where it shouldn't. Fix the card file and render again (`--overwrite`). Captions go on last: `--style apple --position bottom --hide-during "<full-screen windows>"`.
