---
name: cut-the-curve
description: Exact timing and easing numbers for every GSAP move in this folder, so "Apple-smooth" means the same thing everywhere. Card and panel entrances, staged reveals, hook titles (waterfall entry), kinetic words, word-by-word line swaps, the flowchart camera (nudge curve), zoom-through and inverse-zoom payoffs, cut-the-curve between two contents, rack focus, exits and holds. Read it before writing or reviewing any GSAP line here, in talking-head-recut cards, motion-templates modules, kinetic-text styles, morph-shapes charts or any HyperFrames composition. Use it whenever the user says smooth, smoother, Apple-like, keynote, premium or polished motion, easing, timing, "feels cheap", "looks generated", "too bouncy", "too fast", "janky", "the cut jumps", or asks why a move looks off.
---

# Cut the curve: motion numbers

One principle: arrivals land on a long tail, exits accelerate, and when one thing replaces another, cut at peak speed with the same direction and speed on both sides. Every number below was measured from HeyGen's HyperFrames launch films. This skill is adapted from their internal `cut-the-curve` skill (Apache-2.0, see `NOTICE.md`).

## Ground rules (the renderer seeks)

HyperFrames pauses the timeline and jumps it frame by frame, sometimes out of order. So:
- **Timeline only.** Write GSAP lines on `tl` only, at seconds from the clip's start. Don't use timers, randomness, `onUpdate` side effects or `overwrite`.
- **Prefer `tl.fromTo`.**
- **A binary pop:** for something that appears at an exact instant, hide it in CSS (`opacity:0`). Then call `tl.set(el,{opacity:1,y:80},t)` and `tl.to(el,{y:0,...},t)`. A jump back reverts the set, so it hides again.
- **No CSS `transform` on an element GSAP moves.** GSAP overwrites it. Centre with flex or `left`/`top`. A `tl.set` at time 0 doesn't apply on the first frame.
- **Blur:**
  - Blur the wrapper (the card, the line), not each child, and never a `<video>`.
  - Peak blur is **10 px on text**, **14 px on a panel card** and **18 to 20 px on a full-frame surface**.
  - More than that smears the letters into a glitch. Less on a big surface looks like a render hiccup.
- **Units:**
  - Pixel numbers are for u = 1080 (1080×1920 or 1920×1080). Scale them by u/1080 for other sizes.
  - Horizontal travel is written in `vw` (1vw = 1% of the canvas width). GSAP accepts it in `x`.
- `F = 1/60` s in cascade maths, whatever the render fps.

All nine recipes are tested in `examples/`. They render through the `card` template and look the same played forward, backward or seeked at random:
- `ct1-hook.html`: waterfall entry, waterfall cut and nudge.
- `ct2-payoff.html`: arrival, zoom-through, a still beat and the inverse-zoom payoff.
- `ct3-swap.html`: panel arrival, rack focus and cut-the-curve.

## The numbers

| # | Move | Use it for here | Time | Ease | Values |
|---|---|---|---|---|---|
| 1 | Arrival | card or panel entrance, a line of text | 0.6 s (0.5–0.7) | `expo.out` (or `power4.out`) | y 40 → 0, blur 14 → 0 panel or 10 → 0 text, opacity 0 → 1 |
| 2 | Staged reveal | each part of a card, on its word | 0.5 s | `expo.out` | y 24 → 0, opacity 0 → 1; the earlier part dims to 0.4 in 0.4 s |
| 3 | Waterfall entry | hook title, list intro, a kinetic word | 0.10–0.20 s a word | `power4.out` | binary opacity; y 30–80 px by weight; ±1–2 F overlap |
| 4 | Nudge curve | flowchart camera glide, a group making room | 0.57 s (ref) | `power3.in`, `none`, `power4.out` | distance 10 / 65 / 25 %, time 20 / 18 / 62 % |
| 5 | Zoom-through | swap one headline for the next | 0.2 + 0.5 s | `power3.in`, `expo.out` | out scale 1 → 1.2, in 0.75 → 1; blur 10; opacity 0.15 at the cut |
| 6 | Inverse zoom | the payoff: statement card, hero number | 0.2 + 0.5 s | `power3.in`, `expo.out` | out scale 1 → 0.8, in 1.25 → 1; blur 10 |
| 7 | Cut the curve | one content replacing another in a card | 0.33 + 0.33–0.42 s | `power4.in`, `power4.out` | travel 12vw, blur 8, entry ignites at opacity 0.35 |
| 8 | Waterfall cut | a line swapped word by word | 0.34 + 0.3 s | `power4.in`, `power4.out` | ±12vw, fade 0.18 s, stagger 0.022 s; entry gaps 0.05 × 0.84 |
| 9 | Rack focus | same panel, new state (before → after) | 0.3 + 0.35 s | `power2.in`, `power2.out` | drift 4vw, scale 1.06, blur 12; outgoing stays opaque |
| | Count-up | a stat | 1.2–1.6 s | `power2.out` | lands on the spoken number |
| | Exit | the end of a card | 0.35 s (the `card` template adds it) | `power2.in` | 50–75% of the entry |

**Where else:** `morph-shapes` bars and rings arrive like #1. A shape turning into another eases both ways (`power3.inOut`). The `pop` and `stack` kinetic styles are #3 with one or a few words, and a word replaced by the next is #5.

## 1. Arrival
```js
tl.fromTo(".c04",{opacity:0,y:40,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.6,ease:"expo.out"},0.0);
```
`expo.out` covers most of the way in the first frames, then settles on a long tail. Using `power2.out` at 0.5 s on everything is the flat default that makes a video look generated.

## 2. Staged reveal
```js
tl.fromTo("#c04b",{opacity:0,y:24},{opacity:1,y:0,duration:0.5,ease:"expo.out"},at);
tl.to("#c04a",{opacity:0.4,duration:0.4,ease:"power2.out"},at);   // the earlier part steps back
```

## 3. Waterfall entry
Words whip up from below, each starting as the previous one settles: a wave that ends composed. The opacity is binary, because a fade fights the snap. Heavier words travel further and take longer:

| | Anchor (the key word) | Normal word | Light word, punctuation |
|---|---|---|---|
| y offset | 60–80 px | 40–50 px | 30–48 px |
| duration | 0.16–0.20 s | 0.13–0.16 s | 0.10–0.13 s |
| starts | 0–2 F after the previous settles | 1 F before | 1–2 F before |

```js
var F = 1/60, t = 0.10;   // next start = previous start + its duration, then + or - frames
tl.set("#w1",{opacity:1,y:45},t); tl.to("#w1",{y:0,duration:0.15,ease:"power4.out"},t); t += 0.15 + F;  // normal
tl.set("#w2",{opacity:1,y:80},t); tl.to("#w2",{y:0,duration:0.18,ease:"power4.out"},t); t += 0.18 - F;  // anchor
tl.set("#w3",{opacity:1,y:40},t); tl.to("#w3",{y:0,duration:0.12,ease:"power4.out"},t);                  // light
```
- **CSS:** `.w{display:inline-block;opacity:0}`.
- **The last word:** split it into two fragments (y 70, 0.16 s and 0.15 s) to stretch the climax.
- **Direction and ease:** one direction per cascade, and never an `.inOut` ease on an arrival.
- **Speed:** a word inside a cascade may take under 0.25 s. The whole cascade takes 0.4 s or more.
- **A quieter title** (HyperFrames motion guide): each word goes from `blur(6px)` to 0 and from opacity 0 to 1 in 0.13 s, 0.067 s apart, without moving.

## 4. Nudge curve
No single ease is slow-fast-slow: `power4.inOut` smacks into its stop. So chain three tweens on one property. The reference move is 270 px in 0.57 s:
```js
tl.to(".grp",{y:-27, duration:0.12,ease:"power3.in"},t);        // ramp-in: 10% of the way in 20% of the time
tl.to(".grp",{y:-203,duration:0.10,ease:"none"},t + 0.12);      // burst: 65% in 18%, linear
tl.to(".grp",{y:-270,duration:0.35,ease:"power4.out"},t + 0.22); // tail: 25% in 62%
```
- **The tail:** it takes at least 3× the ramp-in time. If it still smacks, lengthen the tail's time, not its distance, or use `power5.out`.
- **The burst:** keep it linear. Show new content during it, and the burst hides its appearance.
- **Other moves:** scale the distances and keep the time ratios. A camera move does the same on `x`, `y` and `scale`, with stops at 10% and 75% of the way.

## 5. Zoom-through (push: everything grows)
```js
var E = 1.30, C = E + 0.2;                                      // E: the old line starts leaving; C: the cut
tl.to("#a",{scale:1.2,filter:"blur(10px)",duration:0.2,ease:"power3.in"},E);
tl.to("#a",{opacity:0.15,duration:0.2,ease:"none"},E);           // its own linear tween: power3.in holds opacity too long
tl.set("#a",{opacity:0},C);
tl.set("#b",{opacity:0.15,scale:0.75,filter:"blur(10px)"},C);
tl.to("#b",{opacity:1,scale:1,filter:"blur(0px)",duration:0.5,ease:"expo.out"},C);
```
The two texts are never visible together: the swap hides at peak blur. Use it on headlines and short phrases only, never on body text.

## 6. Inverse zoom (pull: everything shrinks, for the payoff)
- **The code:** the same as #5, with the old line going `scale:0.8` and the new one starting at `scale:1.25`.
- **When:** spend it on arrivals, such as the statement card's payoff, a hero number or the last line.
- **Arriving first:** when the payoff is the first thing on screen, start it at opacity 0 instead of 0.15.
- **The Z-sign rule:** never answer a shrinking exit with a grow-from-small entry (0.92 → 1), or a growing exit with an oversized one. It reads as a mirror. Stage the next parts after the payoff settles.

## 7. Cut the curve (one content replaces another)
```js
var C = 3.40;                                                   // the cut, on the word
tl.to("#a",{x:"-12vw",filter:"blur(8px)",duration:0.33,ease:"power4.in"},C - 0.33);
tl.to("#a",{opacity:0,duration:0.3,ease:"power2.in"},C - 0.33);  // gone just before the cut
tl.set("#b",{opacity:0.35,x:"12vw",filter:"blur(8px)"},C);
tl.to("#b",{opacity:1,x:0,filter:"blur(0px)",duration:0.42,ease:"power4.out"},C);
```
- **Why it's smooth:** `power4.in` and `power4.out` over the same distance are the two halves of one `power4.inOut`, so the speed matches at the cut.
- **Travel:** 12% of the frame, never fully off screen. Vertical is `y` −12vh → +12vh.
- **Direction:**
  - Use the default leftward direction for every swap in a video.
  - Turn only for a reason: up for a conclusion, or a chapter change.
  - Never ping-pong.
- **Timing:** the entry is at least as long as the exit.
- **Background:** in an overlay card the speaker shows through the seam. Cutaways already have an opaque ground.

## 8. Waterfall cut (a line swapped word by word)
```js
var s = C - 0.32;                                               // exits start before the cut
oldWords.forEach(function (w) { tl.to(w,{x:"-12vw",duration:0.34,ease:"power4.in"},s);
  tl.to(w,{opacity:0,duration:0.18,ease:"power1.in"},s); s += 0.022; });
var off = 0, gap = 0.05;                                        // shrinking gaps: the cascade speeds up
newWords.forEach(function (w) { tl.set(w,{opacity:0.35,x:"12vw"},C + off);
  tl.to(w,{opacity:1,x:0,duration:0.3,ease:"power4.out"},C + off); off += gap; gap *= 0.84; });
```
New words start hidden in CSS. A short first line may exit whole, its fade ending about 0.02 s before the cut.

## 9. Rack focus (the cut meant to be seen)
```js
tl.to("#a",{x:"-4vw",scale:1.06,filter:"blur(12px)",duration:0.3,ease:"power2.in"},R);
tl.set("#a",{opacity:0},R + 0.3);                               // swap at peak blur
tl.set("#b",{opacity:1,x:"4vw",scale:1.06,filter:"blur(12px)"},R + 0.3);
tl.to("#b",{x:0,scale:1,filter:"blur(0px)",duration:0.35,ease:"power2.out"},R + 0.3);
```
- **What it is:** a camera focus pull on the same surface. The old state stays fully opaque until the swap.
- **Blur:** peak at 8 to 12 px, never above 18 px. Use `power2`, not `power4`: soft optics, not momentum.
- **How often:** at most once every 8 s, on a story beat, never during a hold.
- **A dolly instead of a pan:** drop the `x` and use scale 0.92 out and 1.08 → 1 in.

## Timing around the moves
- **Exits** run 50 to 75% of the entry and accelerate (`power2.in`, `power3.in`). The card's 0.35 s fade after a 0.6 s entry is 58%. Seams (#5 to #9) invert this: their entry is longer than their exit.
- **One entry takes at most 0.8 s.** A longer build is a stagger, not a slower move.
- **Stagger:** words 0.06 to 0.12 s apart, list items 0.04 to 0.08 s, in total 0.5 s at most. Similar elements share one ease and duration.
- **Stillness before the payoff:** leave 0.3 to 0.75 s between the setup landing and the payoff, when the speech allows. The word timing wins.
- **A landed element stays still.** No breathing, floating, drift, pulse or slow creeping scale. If a card still has seconds left, reveal its next part or end it sooner.
- **No `bounce` or `elastic`.** In the `apple` look, no `back` either. In other themes use `back.out(1.4)` to `back.out(1.7)` at most, on a small pop. Opacity and colour never overshoot.
- **Ease by role:**
  - an arrival: `expo.out` or `power4.out`
  - an exit or a push into the frame: `power3.in`
  - a camera move or colour change: `power2.inOut`, or the nudge
  - linear only for progress, rotation and the nudge burst

## When the user says

| They say | Change |
|---|---|
| "feels cheap", "looks generated" | Vary the arrivals: #1 for panels, #3 for the hook, #6 for the payoff. Remove idle loops, and no fade-and-rise on everything |
| "too bouncy" | `back.out(2+)` → `expo.out` (apple) or `back.out(1.4)`. Remove shakes, `elastic` and `bounce` |
| "too fast", "glitchy" | Slow every move and zoom to 0.7× of its speed, nothing else. Check that no arrival is under 0.5 s outside a cascade |
| "it stops hard" | Use the nudge curve, with a longer tail |
| "the cut jumps" | Same direction and speed on both sides, and the same blur and opacity at the cut frame |
| "the title keeps moving" | Land it, then hold it dead still until it leaves |

## Don't
- An `.inOut` ease on either side of a cut, or a gentle `power2.out` arrival after one.
- Two texts visible during a zoom-through, or 20 px blur on text.
- Full off-screen moves. Use partial travel and an early fade.
- Queued entries or equal gaps in a cascade, or a fade on a waterfall arrival.
- A different ease and duration for every similar element.
