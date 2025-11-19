#!/usr/bin/env python3
"""
Convert silly-cat.gif to ASCII frames as text files.

Outputs to ./ascii_frames/frame_0000.txt ... sized to given cols/rows.

Usage:
  python tools/convert_gif_to_ascii.py [cols rows]

Defaults:
  cols=80 rows=40
"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageSequence

# Inverted ramp so black/white appear flipped in output (no '.')
RAMP = "@%#*+=-: "


def to_ascii(img, cols, rows):
    g = img.convert("L").resize((cols, rows), Image.BILINEAR)
    px = g.load()
    n = len(RAMP) - 1
    lines = []
    for y in range(rows):
        line_chars = []
        for x in range(cols):
            v = px[x, y]
            idx = int(v * n / 255)
            line_chars.append(RAMP[idx])
        lines.append("".join(line_chars))
    return "\n".join(lines)


def main():
    cols = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    rows = int(sys.argv[2]) if len(sys.argv) > 2 else 40

    gif_path = Path("silly-cat.gif")
    if not gif_path.exists():
        print("Error: silly-cat.gif not found in current directory")
        sys.exit(1)

    out_dir = Path("ascii_frames")
    out_dir.mkdir(exist_ok=True)

    im = Image.open(gif_path)
    count = 0
    for idx, frame in enumerate(ImageSequence.Iterator(im)):
        frame_rgb = frame.convert("RGB")
        ascii_txt = to_ascii(frame_rgb, cols, rows)
        with open(out_dir / f"frame_{idx:04d}.txt", "w") as f:
            f.write(ascii_txt)
        count += 1
    print(f"Wrote {count} ASCII frames to {out_dir}/")


if __name__ == "__main__":
    main()
