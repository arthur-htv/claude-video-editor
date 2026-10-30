# Attribution

The placement and usage rules in `SKILL.md` are adapted from HeyGen's HyperFrames
(https://github.com/heygen-com/hyperframes, Apache License 2.0, Copyright 2026 HeyGen, Inc.):

- the "Text behind the speaker" section of `skills/hyperframes/references/captions.md` (30-55% covered,
  under ~15% floats, over ~65% is eaten, measure the rendered word against the matte, the model's limits
  with mic arms, rigs and held objects)
- `skills/media-use/.../remove-background.md` (compositing a cutout over its own source)
- `.claude/skills/captions-overlay/SKILL.md` at commit 359b6c8a38 (the drop / rail / embed model: an
  embed is scarce, at most one per beat, never two on screen together)

The license text is in `licenses/HYPERFRAMES-LICENSE` at the project root.

Changes made here (Apache-2.0 section 4): the rules are rewritten for this project's FFmpeg pipeline.
`scripts/build_behind.py` is new. It takes the alpha channel of `hyperframes remove-background`'s output
and applies it to the source's own pixels, and it measures coverage on the matte to size and place the word.
