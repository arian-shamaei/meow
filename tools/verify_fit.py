#!/usr/bin/env python3
"""
Verify scaling preserves full-frame containment for given terminal sizes.

Usage:
  python tools/verify_fit.py [cols rows]

If no args provided, runs a sweep of common sizes.
"""
import sys
from pathlib import Path
from PIL import Image


def compute_scaled(src_w, src_h, cols, rows, fit="contain"):
    canvas_h = rows * 2
    if fit == "cover":
        scale = max(cols / src_w, canvas_h / src_h)
    else:
        scale = min(cols / src_w, canvas_h / src_h)
    sw = max(1, int(src_w * scale))
    sh = max(1, int(src_h * scale))
    sw = min(cols, sw)
    sh = min(canvas_h, sh)
    xo = (cols - sw) // 2
    yo = (canvas_h - sh) // 2
    return sw, sh, xo, yo


def assert_contained(src_w, src_h, cols, rows):
    sw, sh, xo, yo = compute_scaled(src_w, src_h, cols, rows, fit="contain")
    assert sw <= cols and sh <= rows * 2, (sw, sh, cols, rows)
    # With contain, at least one dimension should hit the bound when ratios differ
    ratio_src = src_w / src_h
    ratio_can = cols / (rows * 2)
    if abs(ratio_src - ratio_can) > 1e-6:
        # allow 1px slack due to rounding
        assert (sw >= cols - 1) or (sh >= rows * 2 - 1), (sw, sh, cols, rows)
    return sw, sh, xo, yo


def main():
    gif = Path("silly-cat.gif")
    if not gif.exists():
        # Also check packaged path for local runs
        pkg_gif = Path("src/meow_cli/silly-cat.gif")
        if pkg_gif.exists():
            gif = pkg_gif
        else:
            print("silly-cat.gif not found")
            sys.exit(1)
    im = Image.open(gif)
    src_w, src_h = im.size

    tests = []
    if len(sys.argv) >= 3:
        tests.append((int(sys.argv[1]), int(sys.argv[2])))
    else:
        tests = [
            (40, 12), (80, 24), (100, 30), (120, 32), (160, 40),
            (200, 60), (240, 70), (320, 90)
        ]

    ok = True
    for cols, rows in tests:
        try:
            sw, sh, xo, yo = assert_contained(src_w, src_h, cols, rows)
            print(f"OK  term {cols}x{rows} -> scaled {sw}x{sh} px off {xo},{yo}")
        except AssertionError as e:
            ok = False
            print(f"FAIL term {cols}x{rows}: {e}")

    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
