import sys
import os
import time
import shutil
import signal
from PIL import Image, ImageSequence


# Inverted ASCII ramp: bright -> spaces, dark -> dense (no '.')
RAMP = "@%#*+=-: "


def to_ascii(img, cols, rows):
    if cols <= 0 or rows <= 0:
        return ""
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


def clear_and_home():
    sys.stdout.write("\x1b[H\x1b[2J")


def hide_cursor():
    sys.stdout.write("\x1b[?25l")


def show_cursor():
    sys.stdout.write("\x1b[?25h")


def main():
    # Look for GIF in CWD first, then alongside installed package
    cwd = os.getcwd()
    local = os.path.join(cwd, "silly-cat.gif")
    pkg_dir = os.path.dirname(__file__)
    bundled = os.path.join(pkg_dir, "silly-cat.gif")
    gif_path = local if os.path.exists(local) else (bundled if os.path.exists(bundled) else None)
    if not gif_path:
        print("Error: silly-cat.gif not found in current directory.")
        sys.exit(1)

    try:
        im = Image.open(gif_path)
    except Exception as e:
        print(f"Failed to open GIF: {e}")
        sys.exit(1)

    frames = []
    durations = []
    for frame in ImageSequence.Iterator(im):
        frames.append(frame.convert("RGB"))
        dur_ms = frame.info.get("duration", 100)
        durations.append(max(40, int(dur_ms)))

    if not frames:
        print("No frames found in GIF.")
        sys.exit(1)

    running = True

    def handle_sigint(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        hide_cursor()
        idx = 0
        while running:
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            rows = max(1, rows - 1)
            frame = frames[idx]
            ascii_frame = to_ascii(frame, cols, rows)
            clear_and_home()
            sys.stdout.write(ascii_frame)
            sys.stdout.flush()
            time.sleep(durations[idx] / 1000.0)
            idx = (idx + 1) % len(frames)
    finally:
        show_cursor()
        sys.stdout.write("\n")
        sys.stdout.flush()
