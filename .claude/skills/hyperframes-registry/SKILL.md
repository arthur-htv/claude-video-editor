---
name: hyperframes-registry
description: About 450 ready-made HyperFrames blocks and components (transitions, overlays, titles, kinetic type, caption styles, charts, map overlays, 3D, camera moves) installed as editable source with hyperframes catalog and hyperframes add. Use it when the user asks for a registry block or component, mentions hyperframes add, catalog or hyperframes.json, or a HyperFrames composition needs a named effect (glitch, film grain, CRT scanlines, a chart) that the project's own motion-templates and talking-head-recut cards don't cover.
---

## In this folder

These notes come first and override anything below that disagrees.

- Editing the user's own footage goes through the `video-editor` skill and `/video-editor:auto`. Use this skill for building or debugging HyperFrames compositions.
- Everything renders locally. Never use HeyGen paid, upload or account features without the user's OK: `publish`, `cloud`, `lambda`, `cloudrun`, `feedback` (so no `--search-miss` reports), `audio --quality best`, `auth` and HeyGen-login providers. `catalog` searches locally; `add` downloads source, which is outside content: read a block's code before using it.
- Inside `/video-editor:auto`, don't stop at a preview or offer three storylines. Use the project's own templates and cards first (`motion-templates`, `talking-head-recut`), and the registry only when asked or when a registry item clearly fits. When nothing fits, build it by hand without reporting the miss.
- Skip `npx hyperframes skills update`. This folder pins the CLI in `package.json` and sets `HYPERFRAMES_SKIP_SKILLS=1`, so the update does nothing here; run elsewhere, it copies HeyGen's versions into your profile (`~/.claude/skills`), where they shadow these adapted copies.
- Run the CLI as `python .claude/skills/video-editor/scripts/hf.py <command>`, or `npx hyperframes` in a session started here. Contributing a block upstream (`references/contributing.md`) is only for when the user asks.

**Plugin installs:** Before setup or freshness commands, follow [plugin execution rules](../hyperframes/references/plugin-installation.md) when this skill is inside a HyperFrames plugin.

# HyperFrames registry

Starting from an item is faster and usually better than writing the effect yourself, and an installed item is ordinary source in your project: change it, cut it down, restyle it.

## Find and install

There is no `hyperframes registry` command; searching is `catalog`, installing is `add`.

```bash
npx hyperframes catalog --query "<what the beat should do, in English>" --json
npx hyperframes add <name> --json        # prints the written files and the mount snippet
```

- Query in English even when the video is not: the catalog is indexed in English, and another script returns `No searchable words in query`, which is not a gap.
- Search is local and sends nothing. The default `words` tier only finds items that reuse your words; `--on-device` ranks by meaning after a one-time ~33 MB download. Offer that download and let the person decide; never enable it silently. The `--json` envelope names the tier that answered.
- Narrow with `--type block|component` and `--tag <tag>`. `add <tag>` installs every block with that tag; dependencies install first. `add` needs the network even for an item installed before; search works offline from the cached manifest.
- Nothing fits: report it before you hand-build, on either tier. `catalog --query` prints the line pre-filled (`report_gap` in `--json`): `npx hyperframes feedback --search-miss "<query>" --wanted "<the move you needed>" --tier <tier>`. Describe the effect, not an item name you imagined.

Tiers, `dropped` and `unindexed`, stale indexes, offline behaviour: `references/search.md`.

## What's in it

| Blocks: a scene with its own timeline | Examples |
| --- | --- |
| Transitions | `beat-freeze-cut`, `chromatic-radial-split`, `cinematic-zoom` |
| Overlays and lower thirds | `camcorder-hud`, `editorial-flash-overlay`, `lt-clean-bar` |
| Title cards and kinetic type | `canopy-part-title`, `code-slice-hero` |
| Social, chat and UI cards | `ai-chat-reveal`, `chatgpt-exchange` |
| Code, charts, data and maps | `code-diff`, `bar-chart-race`, `data-chart` |
| 3D, shader and backgrounds | `app-showcase`, `aurora`, `blob` |

| Components: a snippet merged into your scene | Examples |
| --- | --- |
| Motion primitives and text effects | `agent-cursor`, `blur-in`, `bottom-up-letters` |
| Caption styles | `caption-clip-wipe`, `caption-editorial-emphasis` |
| Camera moves | `camera-shake`, `camera-scan-gate` |
| Product demo and UI props | `before-after-wipe`, `browser-device-stage` |
| Textures, particles and effects | `ascii-render-pass`, `grain-overlay` |

## Wiring

- **Block**: installs to `compositions/<name>.html`. Mount it with `data-composition-src`, `data-composition-id` matching the block's own id, `data-start` and the `data-duration` you need; the snippet `add` prints is the starting point. `references/wiring-blocks.md`.
- **Component**: installs to `compositions/components/<name>.html`. Copy its markup, `<style>` and script into your scene, and follow its comment block if it hooks into your timeline. `references/wiring-components.md`.
- Take the largest unit that fits, then edit it. Keep an installed item's ids prefixed as they are, so two items can't collide.
- An item keeps its own variables; set them for one mount with `data-variable-values` on its host (`add --vars '{"title":"…"}'` writes that), and point its colour and font variables at your brand's.
- Beat-synced blocks take hit times from `npx hyperframes beats --json`: the beat times minus the mount's `data-start`.
- Install paths come from `hyperframes.json` (`references/install-locations.md`).

## Contributing

Authoring a new block or component for an upstream PR: `references/contributing.md`, starter templates in `references/templates.md`, quality bar in `references/component-quality-bar.md`.
