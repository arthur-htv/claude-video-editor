# HyperFrames: titles, intros and motion graphics

HyperFrames (open source, by HeyGen) renders an HTML page with timed animations into an MP4. Use it for what FFmpeg can't draw well: animated titles, intros and outros, lower thirds (name and role captions), kinetic text, explainer graphics, overlays.

## Where things go

- Each HyperFrames project lives in `work/hyperframes/<name>/`.
- Render to `work/<name>.mp4`, then combine it with the footage (intro recipe, `editing-recipes.md` section 6). Only the combined result goes to `output/`.
- If the graphic itself is what the user asked for ("make me a 5-second intro"), render it straight to `output/`.

## Commands

Run everything from the project folder through the wrapper. It uses this folder's own Node.js and FFmpeg even when they are not on PATH:

```
PY .claude/skills/video-editor/scripts/hf.py <command> ...
```
Below, `HF` stands for that whole prefix.

1. **Create a project.** Pick the canvas that matches the target video: `landscape` (1920x1080), `portrait` (1080x1920, for TikTok / Reels / Shorts) or `square` (1080x1080).
   ```
   HF init work/hyperframes/intro --non-interactive --resolution landscape
   ```
   This folder already includes the HyperFrames skills (`hyperframes`, `hyperframes-cli`, `hyperframes-registry`, `gsap`). Load `hyperframes` before writing a composition. `hf.py` sets `HYPERFRAMES_SKIP_SKILLS=1` and `HYPERFRAMES_NO_TELEMETRY=1`. Without that setting, `init` would install HyperFrames' skills into the user's profile (`--skip-skills` alone is not honored) and send usage telemetry.
2. **Write `work/hyperframes/intro/index.html`** (rules and an example below).
3. **Check it** (lint, runtime, layout, contrast): `HF check work/hyperframes/intro`
4. **Look at it before rendering.** Capture stills and view the PNGs:
   ```
   HF snapshot work/hyperframes/intro --at 0.5,1.5,2.5 --no-end -o work/hyperframes/intro/snaps
   ```
5. **Render:** `HF render work/hyperframes/intro -o work/intro.mp4`
   Options: `--fps 60`, `--quality high`, `--format webm` (transparent background, for overlays).
6. **Combine** with the footage (`editing-recipes.md` section 6). The render has no audio track, so the intro recipe adds a silent one.

`HF doctor` checks Node.js, FFmpeg and the headless Chrome HyperFrames renders with. If Chrome is missing: `HF browser ensure`.

## Composition rules (the minimum that renders correctly)

- The root element carries `data-composition-id`, `data-start="0"`, `data-duration` (seconds), `data-width` and `data-height`, and the page size matches them.
- Every timed element has `class="clip"`, `data-start` and `data-duration`.
- Register exactly one **paused** GSAP timeline per composition on `window.__timelines["<composition-id>"]`. HyperFrames seeks it frame by frame; a timeline that plays on its own renders wrong.
- Keep it deterministic: no `Date.now()`, no `Math.random()`, no network requests besides the GSAP script tag. Every frame must come out the same on every render.
- Fonts: system fonts render reliably. A web font must be loaded in the page and may need `hyperframes-localize-fonts` for offline renders.

Tested example: a 3-second title that rises in and fades out.

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
            integrity="sha384-sG0Hv1tP1lZCk9KQmrIbY/XNwi+OY84GQqhMscbnsoBFqAz8KNCil1kvfL3Hbbk2"
            crossorigin="anonymous"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: #0b0d12; }
      #root { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-family: sans-serif; }
      #title { color: #f5f1e8; font-size: 120px; font-weight: 700; letter-spacing: -0.03em; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="3" data-width="1920" data-height="1080">
      <h1 id="title" class="clip" data-start="0" data-duration="3" data-track-index="0">Episode 12</h1>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      tl.fromTo("#title", { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" }, 0.2);
      tl.to("#title", { opacity: 0, duration: 0.5 }, 2.4);
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
```

Rendering needs an internet connection when the page loads GSAP from the CDN, as above. Keep the `integrity` hash on the script tag: it stops a tampered CDN file from loading, and it only fits this exact GSAP version, so change both together.

## Overlays on footage (lower thirds, animated logos)

Make the page background transparent (`background: transparent` on `html, body`), use the same canvas size as the video, and render with `--format webm`. Then lay it over the footage. `-c:v libvpx-vp9` **before** the overlay input is required: FFmpeg's built-in VP9 decoder drops the transparency and the overlay would cover the video in black.

Overlay starting 2 s into the video and disappearing when it ends:
```
ffmpeg -y -i work/talk.mp4 -c:v libvpx-vp9 -i work/lower_third.webm -filter_complex "[1:v]setpts=PTS+2/TB[ov];[0:v][ov]overlay=0:0:eof_action=pass" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```
Change the `2` to move the start. For an overlay from the very beginning, drop the `setpts` step: `[0:v][1:v]overlay=0:0:eof_action=pass`.
