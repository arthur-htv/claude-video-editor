# Attribution

This skill is adapted from `.claude/skills/cut-the-curve/` (`SKILL.md` and `examples/gsap-implementation.md`) in
HeyGen's HyperFrames repository (https://github.com/heygen-com/hyperframes, commit 359b6c8a38, Apache License 2.0,
Copyright 2026 HeyGen, Inc.). A few timing rules come from Part 2 of `.claude/skills/motion-doctrine/SKILL.md`
in the same commit, and from the hyperframes skill's `references/motion.md` (bundled in `node_modules/hyperframes`).
The license text is in `licenses/HYPERFRAMES-LICENSE` at the project root.

Changes made here (Apache-2.0 section 4):
- **`SKILL.md` is rewritten for this project.**
  - Every recipe is a set of GSAP lines on `tl` for a seeked HyperFrames timeline.
  - Each recipe is mapped to where it applies in this folder: cards, templates, kinetic text and charts.
  - Travel is written in `vw`/`vh`, and there is a panel-card blur level (14 px).
- **Removed:**
  - the registry `gsap_template` blocks
  - the injector tokens
  - the seam-craft, Seam Gate and vector-ledger references
  - the scope rules for multi-scene compositions
- **Added from `motion-doctrine` Part 2:**
  - no idle wobble
  - 0.3 to 0.75 s of stillness before a payoff
  - exits at about 75% of the entry (here 50 to 75%, to agree with `references/motion.md`)
  - one entry at most 0.8 s, and stagger totals
- **`examples/*.html` are new:** three tested cards in this project's `card` template format.
