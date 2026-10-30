# Editing recipes

Tested FFmpeg commands for common edits. Each one reads from `input/` or `work/` and writes to `work/` (an in-between step) or `output/` (the finished file). Run them from the project folder.

`ffmpeg` and `ffprobe` are on PATH when the session status line said "Setup OK". If not, use `tools/ffmpeg/bin/ffmpeg` and `tools/ffmpeg/bin/ffprobe` (add `.exe` on Windows). `PY` = `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS / Linux).

Shared encoder settings used below. Keep them unless the user asks otherwise; they are high quality and play everywhere:
`-c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart`

## Contents
1. Look before you edit
2. Trim, cut out a section, join
3. Reframe: vertical 9:16, square, resize, compress
4. Speed, loudness, music, fades
5. Captions and subtitles
6. Intro / outro, logo
7. Stills, GIFs, audio, scenes
8. Hand off to Premiere / DaVinci Resolve / Final Cut

---

## 1. Look before you edit

```
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate -of compact input/clip.mp4
```
Grab a frame to look at (you can view PNGs):
```
ffmpeg -y -ss 12 -i input/clip.mp4 -frames:v 1 work/frame_12s.png
```
A contact sheet shows the whole video at a glance (one frame every 10 s, 4x3 grid):
```
ffmpeg -y -i input/clip.mp4 -vf "fps=1/10,scale=320:-1,tile=4x3" -frames:v 1 work/sheet.png
```

## 2. Trim, cut out a section, join

**Keep 0:02 to 0:07** (`-ss` = start, `-t` = length). Re-encoding makes the cut frame-accurate:
```
ffmpeg -y -ss 2 -i input/clip.mp4 -t 5 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart output/clip.mp4
```

**Remove a section** (keep 0-4 s and 7 s to the end):
```
ffmpeg -y -i input/clip.mp4 -filter_complex "[0:v]trim=0:4,setpts=PTS-STARTPTS[v0];[0:a]atrim=0:4,asetpts=PTS-STARTPTS[a0];[0:v]trim=start=7,setpts=PTS-STARTPTS[v1];[0:a]atrim=start=7,asetpts=PTS-STARTPTS[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k output/clip.mp4
```

**Join clips that share the same format** (same camera and settings) with no re-encode. Write a list file in `work/`. Paths in it are relative to the list file, so they start with `../`:
```
file '../input/part1.mp4'
file '../input/part2.mp4'
```
```
ffmpeg -y -f concat -safe 0 -i work/join.txt -c copy output/joined.mp4
```

**Join clips with different sizes or frame rates.** Normalize each one to the same canvas, then concat (shown for 1920x1080 at 30 fps):
```
ffmpeg -y -i input/a.mp4 -i input/b.mov -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v0];[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v1];[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart output/joined.mp4
```
A clip with no audio needs a silent track to join: add `-f lavfi -t <its length> -i anullsrc=r=48000:cl=stereo` as an extra input and use it in place of that clip's audio (see the intro recipe in section 6).

## 3. Reframe: vertical 9:16, square, resize, compress

**Vertical for TikTok / Reels / Shorts, center crop** (fills the screen; the sides are cut off, which works for a centered speaker):
```
ffmpeg -y -i work/talk.mp4 -vf "crop=trunc(ih*9/16/2)*2:ih,scale=1080:1920,setsar=1" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```
To keep a speaker who sits off-center, move the crop window: `crop=trunc(ih*9/16/2)*2:ih:X:0`, where X is the left edge in pixels. Find it from a frame grab.

**Vertical with the whole frame visible** (blurred copy fills the background, nothing is cut):
```
ffmpeg -y -i work/talk.mp4 -filter_complex "[0:v]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg2];[fg]scale=1080:-2[fg2];[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1[v]" -map "[v]" -map "0:a?" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```

**Square 1:1** (center crop):
```
ffmpeg -y -i work/talk.mp4 -vf "crop=ih:ih,scale=1080:1080,setsar=1" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```

**Smaller file for email / WhatsApp / upload limits** (720p, stronger compression):
```
ffmpeg -y -i input/clip.mp4 -vf "scale=-2:720" -c:v libx264 -crf 26 -preset slow -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart output/clip.mp4
```
Raise `-crf` (28, 30) for smaller files; every +6 roughly halves the size.

## 4. Speed, loudness, music, fades

**Speed up 1.25x** (pitch stays natural):
```
ffmpeg -y -i work/talk.mp4 -filter_complex "[0:v]setpts=PTS/1.25[v];[0:a]atempo=1.25[a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k output/talk.mp4
```
`atempo` accepts 0.5 to 2.0. Chain two for more (`atempo=2,atempo=1.5`).

**Even out the volume** to the -14 LUFS level YouTube, Instagram and Spotify use (video untouched):
```
ffmpeg -y -i work/talk.mp4 -af "loudnorm=I=-14:TP=-1.5:LRA=11" -c:v copy -c:a aac -b:a 192k -ar 48000 output/talk.mp4
```

**Background music that ducks under the voice.** The music file goes in `input/`; it loops if it's shorter than the video, and `volume=0.25` sets its level:
```
ffmpeg -y -i work/talk.mp4 -stream_loop -1 -i input/music.mp3 -filter_complex "[1:a]volume=0.25[m];[0:a]asplit=2[voice][key];[m][key]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest output/talk.mp4
```
Only use music the user supplied or confirmed they have the rights to.

**Fade in and out** (0.5 s). `END` = the video's length minus 0.5; get the length with ffprobe first:
```
ffmpeg -y -i work/talk.mp4 -vf "fade=t=in:st=0:d=0.5,fade=t=out:st=END:d=0.5" -af "afade=t=in:st=0:d=0.5,afade=t=out:st=END:d=0.5" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k output/talk.mp4
```

## 5. Captions and subtitles

Make the subtitle file (local speech-to-text; the model downloads once into `tools/models/`):
```
PY .claude/skills/video-editor/scripts/transcribe.py work/talk.mp4 --out work/talk.srt
```
Options: `--language en` (skip detection), `--model base` (faster) or `--model medium` (more accurate), `--max-chars 32` (shorter lines for vertical video), `--words` (word timings in `work/`). Open the `.srt` and fix names or jargon before burning it in.

**Burn captions into the picture** (always visible; best for social media). Keep the subtitle path relative, since a Windows drive letter breaks the filter:
```
ffmpeg -y -i work/talk.mp4 -vf "subtitles=work/talk.srt:force_style='FontName=Arial,FontSize=20,Outline=2,MarginV=40'" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```
For vertical video, use a bigger font and a higher margin (`FontSize=14,MarginV=120`; the size is relative to the frame height).

**Attach subtitles the viewer can switch on or off** (no re-encode):
```
ffmpeg -y -i work/talk.mp4 -i work/talk.srt -map 0 -map 1 -c copy -c:s mov_text -metadata:s:s:0 language=eng output/talk.mp4
```
To deliver the subtitles as a separate file instead, copy the `.srt` into `output/` next to the video.

## 6. Intro / outro, logo

**Put an intro clip before the video.** A HyperFrames title has no audio, so give it a silent track as long as the intro (3 s here). Normalize both to the main video's size and frame rate:
```
ffmpeg -y -i work/intro.mp4 -i work/talk.mp4 -f lavfi -t 3 -i anullsrc=r=48000:cl=stereo -filter_complex "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v0];[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v1];[2:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart output/talk.mp4
```
For an outro, swap the order of the inputs in the concat (`[v1][a1][v0][a0]`).

**Logo in the top-right corner** (200 px wide, 40 px from the edges; the logo goes in `input/`):
```
ffmpeg -y -i work/talk.mp4 -i input/logo.png -filter_complex "[1:v]scale=200:-1[logo];[0:v][logo]overlay=W-w-40:40" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy output/talk.mp4
```
Positions: top-left `40:40`, bottom-right `W-w-40:H-h-40`, bottom-left `40:H-h-40`.

## 7. Stills, GIFs, audio, scenes

**Thumbnail** at 3 s: `ffmpeg -y -ss 3 -i output/talk.mp4 -frames:v 1 output/talk_thumbnail.png`

**GIF** (3 s from 0:01, 480 px wide, good colors):
```
ffmpeg -y -ss 1 -t 3 -i output/talk.mp4 -filter_complex "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" output/talk.gif
```

**Audio only** (podcast version): `ffmpeg -y -i output/talk.mp4 -vn -c:a libmp3lame -q:a 2 output/talk.mp3`

**Find scene changes / shot boundaries** (writes a CSV list of scenes to `work/`):
```
.venv/Scripts/scenedetect -i input/clip.mp4 -o work detect-adaptive list-scenes
```
(macOS / Linux: `.venv/bin/scenedetect`.) Add `split-video` to also cut the video into one file per scene.

## 8. Hand off to Premiere / DaVinci Resolve / Final Cut

When the user wants to fine-tune the dead-air cuts themselves in an editing program, auto-editor exports an editable timeline instead of a rendered video:
```
.venv/Scripts/auto-editor input/talk.mp4 --margin 0.2s --export premiere -o output/talk_premiere.xml --no-open --progress none
```
`--export resolve` (DaVinci Resolve `.fcpxml`), `--export final-cut-pro` and `--export shotcut` work the same way. The timeline points at the original file in `input/`, so it must stay there. Always pass `--no-open`; otherwise auto-editor opens the result in the default app.
