"""Where graphics can go without covering the speaker's face.

Samples a few frames, finds the speaker's face with OpenCV's built-in face
detector, and turns that into safe positions for captions and on-screen text.
Used by the captions, kinetic-text and morph-shapes skills. If OpenCV is not
available (e.g. Linux without desktop graphics libraries) it falls back to
sensible fixed positions.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from vtools import MediaInfo, find_tool, probe

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


@dataclass
class Layout:
    width: int
    height: int
    face: tuple[float, float, float, float] | None   # x0, y0, x1, y1 as fractions of the frame
    caption_y: float                                  # caption center, fraction of height
    text_zone: str                                    # where kinetic text fits: top / left / right
    note: str

    @property
    def vertical(self) -> bool:
        return self.height > self.width


def _frame_gray(path: Path, t: float, width: int = 480):
    cmd = [find_tool("ffmpeg"), "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
           "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    if not raw:
        return None
    h = len(raw) // width
    return np.frombuffer(raw[: h * width], dtype=np.uint8).reshape(h, width)


def find_face(info: MediaInfo, samples: int = 9) -> tuple[float, float, float, float] | None:
    """Median face box over sampled frames (fractions), or None when no steady face is found."""
    if np is None or not info.has_video:
        return None
    try:
        import cv2
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if detector.empty():
            return None
    except Exception:          # OpenCV missing, or a build without the classic face detector
        return None
    boxes = []
    for i in range(samples):
        t = info.duration * (0.1 + 0.8 * i / max(1, samples - 1))
        img = _frame_gray(info.path, t)
        if img is None:
            continue
        h, w = img.shape
        found = detector.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(w // 12, w // 12))
        if len(found):
            x, y, fw, fh = max(found, key=lambda b: b[2] * b[3])
            boxes.append((x / w, y / h, (x + fw) / w, (y + fh) / h))
    if len(boxes) < max(2, samples // 3):
        return None
    arr = np.array(boxes)
    return tuple(float(v) for v in np.median(arr, axis=0))


def analyze(path: Path | str, info: MediaInfo | None = None) -> Layout:
    info = info or probe(path)
    w, h = info.width or 1920, info.height or 1080
    face = find_face(info)
    vertical = h > w
    if face:
        x0, y0, x1, y1 = face
        face_h = y1 - y0
        chin = y1 + 0.10 * face_h                       # face boxes stop around the mouth; add the chin
        if vertical:
            cap = min(max(chin + 0.12, 0.62), 0.80)      # on the chest, never on the jaw
        else:
            cap = 0.86 if chin < 0.74 else 0.93
        cx = (x0 + x1) / 2
        if y0 > 0.30:
            zone = "top"                                 # room above the head
        elif vertical:
            zone = f"y={min(chin + 0.05, cap - 0.16):.2f}"   # under the chin, above the captions
        else:
            zone = "left" if cx > 0.5 else "right"       # wide frame: the side away from the face
        note = f"face found at x {x0:.2f}-{x1:.2f}, y {y0:.2f}-{y1:.2f}"
    else:
        cap = 0.72 if vertical else 0.86
        zone = "top"
        note = "no steady face found (or OpenCV unavailable); using default positions"
    return Layout(w, h, face, cap, zone, note)


if __name__ == "__main__":
    import sys
    lay = analyze(Path(sys.argv[1]))
    print(lay)
