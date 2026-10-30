# Template specs

A spec file holds one spec or a list of them. Every spec has:
- `template`
- `start` and `end`: seconds on the video's timeline
- an optional `theme`; `--theme` on the command line wins

Times inside a spec are also video seconds. They must lie between `start` and `end`, or the build stops and names the bad time. Text fields accept `*stars*` around words to color them with the theme's accent. Keep text short: the templates shrink long text to fit, but a box with 12 words reads worse than one with 4.

## flowchart (cutaway)

```json
{"template": "flowchart", "start": 9.6, "end": 85.0, "title": "Turning credit into cash",
 "nodes": [
  {"id": "approved", "icon": "credit-card", "text": "Approved", "sub": "$50,000 limit", "at": 10.6},
  {"id": "split", "after": "approved", "branch": "Option 1", "icon": "shopping-cart",
   "text": "Split the payment at checkout", "sub": "Best Buy · Micro Center", "at": 17.2, "sticker": "$2,500"},
  {"id": "return", "after": "split", "icon": "package", "text": "Return it unopened", "at": 33.5},
  {"id": "refund", "after": "return", "text": "Refund goes to", "choice": ["Debit", "Credit"], "pick": 0,
   "pick_at": 42.0, "sub": "You keep the points", "at": 40.1},
  {"id": "bfm", "after": "approved", "branch": "Option 2", "icon": "globe", "text": "Sign up on *Buy For Me*", "at": 55.0},
  {"id": "ach", "after": "bfm", "icon": "landmark", "text": "They ACH the total to your bank", "at": 70.5}],
 "recap": true}
```

| Field | Meaning |
|---|---|
| `nodes[].id` | unique name; `after` points at the box it follows |
| `nodes[].after` | omitted for the first box. Two boxes after the same one become side-by-side columns (branches). A box has one `after`, so branches can't join again: for an "either way, ..." ending, end the flowchart and show the outcome as kinetic text or a tag over the speaker. |
| `branch` | pill on the box's top edge ("Option 1"), usually on the first box of each branch |
| `text`, `sub` | box label (about 2 lines), and a small accent line under it |
| `icon` | from the list below; leave it out for a text-only box |
| `sticker` | small tilted pill on the corner ("$2,500"); it pops 0.6 s after the box |
| `choice`, `pick`, `pick_at` | option boxes instead of an icon; `pick` (index) gets a tick at `pick_at` (default 1.2 s after the box) |
| `at` | when the box appears; the camera glides to it |
| `title` | heading above the first box |
| `recap` | `true` (default): zoom out to the whole map in the last 3 s. It needs about 3.4 s after the last box appears; with less, it is skipped, so end the flowchart later. A time sets when (at least 2.2 s before `end`). `false`: no recap. |

The order on screen follows `at`, not the list order. Branches lay out left to right in list order. Long explanations are fine: 10 to 15 boxes still read well, because the camera keeps one in focus and the recap shows the rest.

## steps (cutaway or overlay)

```json
{"template": "steps", "start": 20.0, "end": 31.0, "title": "3 rules for *business credit*",
 "items": [{"text": "Pay the full balance every month", "at": 21.0},
           {"text": "Keep usage under 30%", "at": 24.5, "icon": "percent"},
           {"text": "Never miss a payment", "at": 28.0}],
 "mode": "cutaway"}
```

- **Items:** 1 to 8. An earlier item dims when the next one appears. An `icon` replaces the item's number.
- **Overlay mode:** with `mode: "overlay"` the steps sit on a panel over the speaker. Use `position` to place it: `top` or `bottom` (vertical video), `left` or `right` (wide video).

## compare (cutaway)

```json
{"template": "compare", "start": 40.0, "end": 50.0, "title": "Where should the refund go?",
 "left": {"title": "Credit card", "tone": "bad", "icon": "credit-card", "at": 40.3,
          "items": [{"text": "Charge gets reversed", "at": 41.5}, {"text": "You lose the points", "at": 43.0}]},
 "right": {"title": "Debit card", "tone": "good", "icon": "landmark", "at": 44.5,
           "items": [{"text": "Cash lands in your bank", "at": 45.5}, {"text": "You keep the points", "at": 47.0}]},
 "vs": "vs"}
```

- **tone:** `good` gives green ticks, `bad` gives red crosses, `neutral` gives dots.
- **Column timing:** a column appears at its `at`, or just before its first item.

## quote (cutaway or overlay)

```json
{"template": "quote", "start": 36.0, "end": 40.5, "text": "Failure is *not the end*.", "author": "Franco Salvacion"}
```

The words appear one by one. `mode: "overlay"` puts it in a panel (`position`: `top` or `bottom`).

## chapter (cutaway, 1.5 to 2.5 s)

```json
{"template": "chapter", "start": 54.6, "end": 56.6, "label": "Option 2", "title": "Buy For Me", "icon": "globe"}
```

## hook-title (overlay)

```json
{"template": "hook-title", "start": 0.0, "end": 2.6, "title": "How to pull *cash* off a credit card",
 "sub": "Step by step · part 2"}
```

`position`: `top` (default), `center`, or the top edge as a fraction of the height. In vertical video, look at the source frames first: when the face is high in the frame, `top` covers the eyes, so put the title under the chin (about `0.40`).

## tag (overlay)

```json
{"template": "tag", "start": 8.0, "end": 12.0, "tags": [
  {"text": "Manufactured spending", "at": 8.3, "until": 10.6, "x": 0.5, "y": 0.06},
  {"text": "Business credit card", "at": 9.1, "x": 0.72, "y": 0.66, "point": [0.45, 0.6], "style": "box"}]}
```

| Field | Meaning |
|---|---|
| `x`, `y` | the tag's centre, as fractions of the frame |
| `point` | the spot a line points at (find it by looking at a frame) |
| `style` | `pill` (accent color, the default) or `box` (dark with a light edge) |
| `until` | when it leaves; the default is 2.5 s after it appears |

Keep tags off the face and out of the caption area (`y` above about 0.7).

## cta (overlay)

```json
{"template": "cta", "start": 82.0, "end": 85.4, "handle": "@yourhandle", "text": "Save this", "icon": "bookmark", "y": 0.55}
```

- **icon:** `bookmark` (save), `user-plus` (follow), `bell`, `heart`, `share-2` or `send`.
- **Tap:** the button gets "tapped" 1 s after it appears.
- **handle:** ask the user for their handle. Don't guess one.

## card (overlay or cutaway)

A card designed by hand for one moment. The `talking-head-recut` skill says how to plan and write one; its `examples/` folder has three tested cards.

```json
{"template": "card", "start": 8.4, "end": 10.85, "file": "work/cards/c01.html", "checks": [9.0, 10.5]}
```

| Field | Meaning |
|---|---|
| `file` | an HTML fragment (markup, one `<style>`, one `<script>` of GSAP lines on `tl`, timed from the card's start); or `html` with the same text inline |
| `mode` | `overlay` (default, transparent, over the speaker) or `cutaway` (the theme's background, full screen) |
| `checks` | video times for the check frames (default: 30% and 60% of the way through) |

`[[icon:name]]` in the fragment becomes a bundled icon. A 0.35 s fade-out is added at the end. Web links are refused, so renders stay offline and repeatable.

## lower-third (overlay, 3 to 5 s)

A person's name and role beside the speaker, or a product and what it is. Adapted from HyperFrames' `lt-*` lower thirds.

```json
{"template": "lower-third", "start": 3.0, "end": 7.5, "name": "Franco *Salvacion*", "title": "Founder, HighThrive",
 "style": "clean-bar"}
```

| Field | Meaning |
|---|---|
| `name` | the big line, one line (long names shrink to fit) |
| `title` | the role line under it; optional |
| `style` | `clean-bar` (default): a panel with an accent tab that wipes in, readable on any footage. `accent-underline`: no panel, an accent rule draws under the name. `kicker-name`: an accent tag drops in above the name (needs `kicker`). `side-rule`: a vertical accent bar, the text slides in beside it. The styles without a panel use white text with a dark halo (the one kinetic text uses), so they read on white clothing; `clean-bar` is still the calmest over busy footage. |
| `kicker` | the short tag of `kicker-name` ("Episode 4", "Guest") |
| `at` | when it starts (default `start`); it leaves in the last 0.55 s |
| `position` | `bottom` (default): its bottom edge at 0.70 of the height in vertical video and 0.78 in wide, just above the captions. `top`: the top edge at 0.06. A number: the bottom edge as a fraction of the height. |

Left-aligned, 7% in from the left edge. Use it once, when the person (or the thing) is first named or first on screen, not over a cutaway.

## title-card (cutaway or overlay, 2.5 to 4 s)

A calm, typographic title: an intro, a topic, a reveal, a breather between parts. Adapted from HyperFrames' `titlecard-calm` and `titlecard-lockup`.

```json
{"template": "title-card", "start": 0.0, "end": 3.5, "title": "Business credit, *explained*", "kicker": "Part 1",
 "sub": "No personal guarantee", "style": "calm"}
```

| Field | Meaning |
|---|---|
| `title` | the headline (up to 3 lines in `calm`, 2 in `lockup`) |
| `kicker` | a small spaced-out label above it; optional |
| `sub` | a line under it (the small label under the rule in `lockup`); optional |
| `style` | `calm` (default): left-aligned, the kicker then the headline fade up, then the card drifts gently upward. `lockup`: centred, the headline settles with one small scale move, a hairline rule draws left to right, the label fades in, then it holds still. Neither bounces. |
| `mode` | `cutaway` (default): full screen on the theme's background. `overlay`: over the speaker, with the footage dimmed to 78% of the theme's background. |
| `at` | when it starts (default `start`); it fades out at the end. Under about 1.8 s (`calm`) or 2.3 s (`lockup`) the motion speeds up to fit. |
| `position` | `center` (default) or the card's centre as a fraction of the height |

As a cutaway, pass its window to captions' `--hide-during`, like `chapter`. Use `chapter` for a numbered section with an icon; use `title-card` for a quieter, Apple-like title.

## annotate (overlay)

Hand-drawn marks over the footage: a wobbly circle around something in the frame, or a squiggle under it, drawn on as it is mentioned. Adapted from HyperFrames' `hw-callout-circle` and `hw-underline`.

```json
{"template": "annotate", "start": 5.0, "end": 9.0, "marks": [
  {"shape": "circle", "x": 0.5, "y": 0.55, "w": 0.42, "h": 0.14, "at": 5.2, "label": "The *card*"},
  {"shape": "underline", "x": 0.5, "y": 0.66, "w": 0.5, "at": 6.4, "until": 8.8}]}
```

| Field | Meaning |
|---|---|
| `shape` | `circle` (default) or `underline` |
| `x`, `y` | the centre of the thing being marked (for an underline: the line's centre), as fractions of the frame. Find them on a frame of the video. |
| `w`, `h` | its width and height as fractions of the frame's width and height; an underline uses only `w` |
| `at`, `until` | when it draws on (0.7 s for a circle, 0.55 s for an underline) and when it leaves (default: `end`) |
| `label` | a short line under the mark, or above it when the mark is in the lower half; optional |

The marks use the theme's accent colour and "boil" (a slight hand-drawn jitter), except in `apple`, where they hold still. Keep them off the face and above the captions (`y` under about 0.7). For a label with a straight pointer line, use `tag` instead.

## Icons (`assets/icons`, Lucide, ISC license)

alarm-clock arrow-down arrow-right arrow-up award baby badge-dollar-sign ban banknote bell book-open bookmark bot box boxes brain briefcase
building-2 building calculator calendar camera car chart-bar chart-line chart-pie check circle-check circle-dollar-sign circle-help circle-x
clipboard-list clock cloud code coffee coins contact cpu credit-card crown database dollar-sign download dumbbell eye-off eye file-check file-text
file-x film flag flame frown gavel gem gift git-branch globe graduation-cap hammer hand-coins handshake headphones heart hospital hourglass house
image info key landmark laptop layers lightbulb link list-checks lock-open lock mail map-pin map megaphone message-circle message-square mic
milestone monitor moon mouse-pointer-click music notebook-pen package-open package pause pen pencil percent person-standing phone piggy-bank plane
play puzzle receipt refresh-cw repeat rocket rotate-ccw route scale scan-barcode school scissors search send server settings share-2 shield-check
shield shopping-bag shopping-cart shuffle signpost smartphone smile sparkles star store sun tag target thumbs-down thumbs-up timer trending-down
trending-up triangle-alert trophy truck upload user-check user-plus user-x user users utensils vault video wallet warehouse wifi workflow wrench x zap

Banks: `landmark`. Money in or out: `hand-coins`, `banknote`, `wallet`. Approval: `circle-check`, `badge-dollar-sign`. A website: `globe`. Growth: `trending-up`. A warning: `triangle-alert`.
