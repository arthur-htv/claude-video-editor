# Attribution

This skill is adapted from `skills/talking-head-recut` in HeyGen's HyperFrames repository
(https://github.com/heygen-com/hyperframes, Apache License 2.0, Copyright 2026 HeyGen, Inc.), as it stood
before commit 688229314f (2026-10-21), which retired it upstream. The license text is in
`licenses/HYPERFRAMES-LICENSE` at the project root.

Changes made here (Apache-2.0 section 4):
- `SKILL.md` is rewritten for this project: cards render through the `card` template of the
  `motion-templates` skill (local HyperFrames render, FFmpeg overlay), the plan is shown for approval,
  an Apple-style look and its numbers are added, and the measured timing and placement numbers come from
  the hyperframes skill's `references/overlays.md`. The original's composition assembly, `data-anim`
  compiler, layouts, frames and bundled assets are not included.
- `references/styles/*.html` are copied unchanged from the original's `references/styles/`.
- `examples/*.html` are new.

HeyGen's original skill was itself adapted from vtake-skills (`vtake-cut`, https://github.com/notedit/vtake-skills),
whose MIT notice is kept below as it requires:

```
MIT License

Copyright (c) 2026 leeoxiang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
