---
description: Automatic edit. Scans each video in input/ and applies the effects that fit what is said (dead air, retakes, kinetic text, morph charts, captions), then delivers to output/.
argument-hint: "[video name] [notes, e.g. no captions, keywords: Claude]"
---

Do an automatic edit with the `video-editor` skill:

1. Read `.claude/skills/video-editor/SKILL.md` for the folder contract and Step 0 (tools ready).
2. Follow `.claude/skills/video-editor/references/auto-edit.md` from start to finish.

Videos and notes from the user: $ARGUMENTS

If that is empty, edit every video in `input/` that has no finished copy in `output/` yet.
