import sys
import os
import time
import signal
import curses
import shutil
import subprocess
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
    # use ordered dithering 2x2 for smoother shading
    bayer = ((0, 128), (192, 64))
    lines = []
    h = gray_img.size[1]
    for y in range(0, min(h, rows * 2), 2):
        line_chars = []
        for x in range(cols):
            top = px[x, y]
            bottom = px[x, y + 1] if y + 1 < h else 255
            # invert brightness: darker -> filled
            tt = bayer[(y // 1) & 1][x & 1]
            bt = bayer[(y + 1) & 1][x & 1]
            top_dark = top < tt
            bottom_dark = bottom < bt
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
    return lines


def _braille_ascii(gray_img, cols, rows):
    # gray_img expected mode 'L' sized (cols*2, rows*4)
    # Braille dot layout indexes: (x,y) -> bit
    # (0,0)->1, (0,1)->2, (0,2)->4, (1,0)->8, (1,1)->16, (1,2)->32, (0,3)->64, (1,3)->128
    px = gray_img.load()
    lines = []
    # 2x4 Bayer matrix thresholds (0..255 scaled)
    bayer = (
        (0, 128),
        (192, 64),
        (48, 176),
        (240, 112),
    )
    for cy in range(rows):
        y0 = cy * 4
        line_chars = []
        for cx in range(cols):
            x0 = cx * 2
            bits = 0
            # For each subpixel in 2x4 block, compare against threshold
            for dy in range(4):
                for dx in range(2):
                    yy = y0 + dy
                    xx = x0 + dx
                    val = px[xx, yy] if (xx < gray_img.size[0] and yy < gray_img.size[1]) else 255
                    thr = bayer[dy][dx]
                    dark = val < thr  # inverted
                    if dark:
                        # Map to braille bit
                        if dx == 0 and dy == 0:
                            bits |= 0x01
                        elif dx == 0 and dy == 1:
                            bits |= 0x02
                        elif dx == 0 and dy == 2:
                            bits |= 0x04
                        elif dx == 1 and dy == 0:
                            bits |= 0x08
                        elif dx == 1 and dy == 1:
                            bits |= 0x10
                        elif dx == 1 and dy == 2:
                            bits |= 0x20
                        elif dx == 0 and dy == 3:
                            bits |= 0x40
                        elif dx == 1 and dy == 3:
                            bits |= 0x80
            ch = chr(0x2800 + bits) if bits else " "
            line_chars.append(ch)
        lines.append("".join(line_chars))
    return lines


def _full_ascii(gray_img, cols, rows):
    # gray_img mode 'L' sized (cols, rows). Map average brightness to levels
    px = gray_img.load()
    shades = [" ", "░", "▒", "▓", "█"]  # inverted levels low->bright
    lines = []
    for y in range(rows):
        line_chars = []
        for x in range(cols):
            v = px[x, y]
            idx = 4 - min(4, int(v * 5 / 256))  # inverted
            line_chars.append(shades[idx])
        lines.append("".join(line_chars))
    return lines


def _tui(stdscr, *, debug=False, fit_mode="contain", pixel_mode="auto"):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.noecho()
    curses.cbreak()

    frames, durations = _load_gif()
    idx = 0

    # Cache ascii frames per terminal size for smoothness
    cache_key = None
    cached_ascii = None  # list[str] per frame
    cached_info = None  # (scaled_w, scaled_h, x_off, y_off, mode, avail_rows)
    src_w, src_h = frames[0].size

    def _detect_term_size():
        # Try curses first
        try:
            r, c = stdscr.getmaxyx()
            if r > 0 and c > 0:
                return c, r
        except Exception:
            pass
        # Env variables
        try:
            c = int(os.environ.get("COLUMNS", 0))
            r = int(os.environ.get("LINES", 0))
            if c > 0 and r > 0:
                return c, r
        except Exception:
            pass
        # shutil fallback
        try:
            ts = shutil.get_terminal_size(fallback=(80, 24))
            return ts.columns, ts.lines
        except Exception:
            pass
        # stty size
        try:
            out = subprocess.check_output(["stty", "size"], stderr=subprocess.DEVNULL)
            r, c = map(int, out.split())
            return c, r
        except Exception:
            pass
        # tput cols/lines
        try:
            c = int(subprocess.check_output(["tput", "cols"]))
            r = int(subprocess.check_output(["tput", "lines"]))
            return c, r
        except Exception:
            pass
        return 80, 24

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
            rows = max(1, rows)
            cols = max(1, cols)
            if rows <= 1 or cols <= 1:
                # Fallback detection if curses reports something tiny
                cols, rows = _detect_term_size()

            # Reserve a status line in debug mode to avoid overlap
            avail_rows = max(1, rows - (1 if debug else 0))

            size_key = (cols, avail_rows, fit_mode, pixel_mode)
            if size_key != cache_key:
                # Rebuild cached ASCII frames for this size, preserving aspect ratio
                cache_key = size_key
                cached_ascii = []
                cached_info = None
                # Choose pixel mode
                mode = pixel_mode
                if mode == "auto":
                    # Prefer braille when reasonably sized terminal
                    mode = "braille" if avail_rows >= 6 and cols >= 10 else "half"
                if mode == "braille":
                    canvas_w = cols * 2
                    canvas_h = avail_rows * 4
                    renderer = _braille_ascii
                elif mode == "half":
                    canvas_w = cols
                    canvas_h = avail_rows * 2
                    renderer = _halfblock_ascii
                else:  # full
                    canvas_w = cols
                    canvas_h = avail_rows
                    renderer = _full_ascii
                # Compute uniform scale to fit within terminal canvas preserving ratio
                if fit_mode == "cover":
                    scale = max(max(1, canvas_w) / max(1, src_w), max(1, canvas_h) / max(1, src_h))
                else:
                    scale = min(max(1, canvas_w) / max(1, src_w), max(1, canvas_h) / max(1, src_h))
                # Ensure at least 1x1 after scaling
                scaled_w = max(1, int(src_w * scale))
                scaled_h = max(1, int(src_h * scale))
                # Clamp to canvas in case rounding overshoots
                scaled_w = min(canvas_w, scaled_w)
                scaled_h = min(canvas_h, scaled_h)
                x_off = (canvas_w - scaled_w) // 2
                y_off = (canvas_h - scaled_h) // 2

                for fr in frames:
                    # Create white canvas so letterboxed areas render as blanks
                    canvas = Image.new('L', (canvas_w, canvas_h), color=255)
                    g = fr.convert('L').resize((scaled_w, scaled_h), Image.NEAREST)
                    canvas.paste(g, (x_off, y_off))
                    cached_ascii.append(renderer(canvas, cols, avail_rows))
                cached_info = (scaled_w, scaled_h, x_off, y_off, mode, avail_rows)
                # Adjust curses internal structures to new size
                try:
                    curses.resizeterm(rows, cols)
                except curses.error:
                    pass

            stdscr.erase()
            if cached_ascii:
                # Draw line-by-line to avoid bottom-right scroll issues
                lines = cached_ascii[idx]
                for r in range(min(len(lines), avail_rows)):
                    try:
                        stdscr.addnstr(r, 0, lines[r], cols)
                    except curses.error:
                        pass
            # Optional debug overlay (border + status line)
            if debug and cached_info is not None:
                sw, sh, xo, yo, mode, avail_rows = cached_info
                # Map pixel canvas coords to cell coords
                if mode == "braille":
                    top = yo // 4
                    scaled_rows = (sh + 3) // 4
                    left = xo // 2
                elif mode == "half":
                    top = yo // 2
                    scaled_rows = (sh + 1) // 2
                    left = xo
                else:
                    top = yo
                    scaled_rows = sh
                    left = xo
                right = min(cols - 1, left + (sw // (2 if mode=="braille" else 1)) - 1)
                bottom = min(avail_rows - 1, top + scaled_rows - 1)
                # Draw border
                try:
                    if 0 <= top < rows:
                        stdscr.hline(top, left, ord('-'), max(0, right - left + 1))
                    if 0 <= bottom < rows:
                        stdscr.hline(bottom, left, ord('-'), max(0, right - left + 1))
                    for r in range(max(0, top), min(rows, bottom + 1)):
                        if 0 <= left < cols:
                            stdscr.addch(r, left, ord('|'))
                        if 0 <= right < cols:
                            stdscr.addch(r, right, ord('|'))
                    # Corners
                    if 0 <= top < rows and 0 <= left < cols:
                        stdscr.addch(top, left, ord('+'))
                    if 0 <= top < rows and 0 <= right < cols:
                        stdscr.addch(top, right, ord('+'))
                    if 0 <= bottom < rows and 0 <= left < cols:
                        stdscr.addch(bottom, left, ord('+'))
                    if 0 <= bottom < rows and 0 <= right < cols:
                        stdscr.addch(bottom, right, ord('+'))
                except curses.error:
                    pass
                # Status line at bottom
                status = f"term {cols}x{rows} | src {src_w}x{src_h} | scaled {sw}x{sh} px | fit {fit_mode} | mode {mode} | off {xo},{yo}"
                try:
                    stdscr.addnstr(rows - 1, 0, status.ljust(cols), cols)
                except curses.error:
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
    debug = False
    fit_mode = "contain"
    pixel_mode = "auto"
    for arg in sys.argv[1:]:
        if arg in ("-d", "--debug"):
            debug = True
        elif arg.startswith("--fit="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in ("contain", "cover"):
                fit_mode = val
        elif arg.startswith("--pixel-mode="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in ("auto", "braille", "half", "full"):
                pixel_mode = val
    curses.wrapper(lambda stdscr: _tui(stdscr, debug=debug, fit_mode=fit_mode, pixel_mode=pixel_mode))
