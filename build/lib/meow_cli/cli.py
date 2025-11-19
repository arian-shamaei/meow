import sys
import os
import time
import signal
import curses
from PIL import Image, ImageSequence


def _load_gif():
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
    return frames, durations


def _halfblock_ascii(gray_img, cols, rows):
    # gray_img expected mode 'L' sized (cols, rows*2)
    px = gray_img.load()
    threshold = 128
    lines = []
    h = gray_img.size[1]
    # Combine two vertical pixels per terminal row
    for y in range(0, min(h, rows * 2), 2):
        line_chars = []
        for x in range(cols):
            top = px[x, y]
            bottom = px[x, y + 1] if y + 1 < h else 255
            top_dark = top < threshold
            bottom_dark = bottom < threshold
            if top_dark and bottom_dark:
                ch = "█"
            elif top_dark and not bottom_dark:
                ch = "▀"
            elif not top_dark and bottom_dark:
                ch = "▄"
            else:
                ch = " "
            line_chars.append(ch)
        lines.append("".join(line_chars))
    return "\n".join(lines)


def _tui(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.noecho()
    curses.cbreak()

    frames, durations = _load_gif()
    idx = 0

    # Cache ascii frames per terminal size for smoothness
    cache_size = None
    cached_ascii = None
    src_w, src_h = frames[0].size

    # Handle Ctrl+C gracefully
    running = True

    def handle_sigint(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        next_time = time.time()
        while running:
            try:
                ch = stdscr.getch()
                if ch in (ord('q'), 27):  # q or ESC to quit
                    break
            except curses.error:
                pass

            rows, cols = stdscr.getmaxyx()
            rows = max(1, rows)  # use all rows
            cols = max(1, cols)

            size_key = (cols, rows)
            if size_key != cache_size:
                # Rebuild cached ASCII frames for this size, preserving aspect ratio
                cache_size = size_key
                cached_ascii = []
                target_canvas_h = rows * 2
                # Compute uniform scale to fit within terminal canvas preserving ratio
                scale = min(max(1, cols) / max(1, src_w), max(1, target_canvas_h) / max(1, src_h))
                # Ensure at least 1x1 after scaling
                scaled_w = max(1, int(src_w * scale))
                scaled_h = max(1, int(src_h * scale))
                # Clamp to canvas in case rounding overshoots
                scaled_w = min(cols, scaled_w)
                scaled_h = min(target_canvas_h, scaled_h)
                x_off = (cols - scaled_w) // 2
                y_off = (target_canvas_h - scaled_h) // 2

                for fr in frames:
                    # Create white canvas so letterboxed areas render as blanks
                    canvas = Image.new('L', (cols, target_canvas_h), color=255)
                    g = fr.convert('L').resize((scaled_w, scaled_h), Image.BILINEAR)
                    canvas.paste(g, (x_off, y_off))
                    cached_ascii.append(_halfblock_ascii(canvas, cols, rows))
                # Adjust curses internal structures to new size
                try:
                    curses.resizeterm(rows, cols)
                except curses.error:
                    pass

            stdscr.erase()
            if cached_ascii:
                try:
                    stdscr.addstr(0, 0, cached_ascii[idx])
                except curses.error:
                    # Ignore drawing errors on very small terminals
                    pass
            stdscr.refresh()

            # Frame timing
            next_time += durations[idx] / 1000.0
            sleep_for = max(0, next_time - time.time())
            time.sleep(sleep_for)
            idx = (idx + 1) % len(frames)
    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.curs_set(1)


def main():
    curses.wrapper(_tui)
