import sys
import os
import time
import signal
import curses
import shutil
import subprocess
from PIL import Image, ImageSequence


# ── Colour-theory helpers ─────────────────────────────────────────────

def _hsl_to_rgb1000(h, s, l):
    """Convert HSL to RGB in curses 0-1000 scale.

    h: 0-360 (hue degrees), s: 0-1 (saturation), l: 0-1 (lightness).
    Returns (r, g, b) each clamped to 0-1000 for curses.init_color().
    """
    h = h % 360
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (
        max(0, min(1000, int((r + m) * 1000))),
        max(0, min(1000, int((g + m) * 1000))),
        max(0, min(1000, int((b + m) * 1000))),
    )


def _nearest_std_color(rgb):
    """Map an RGB (0-1000) tuple to the nearest curses standard colour ID."""
    std = [
        (0, (0, 0, 0)),           # BLACK
        (1, (1000, 0, 0)),        # RED
        (2, (0, 1000, 0)),        # GREEN
        (3, (1000, 1000, 0)),     # YELLOW
        (4, (0, 0, 1000)),        # BLUE
        (5, (1000, 0, 1000)),     # MAGENTA
        (6, (0, 1000, 1000)),     # CYAN
        (7, (1000, 1000, 1000)),  # WHITE
    ]
    best_id, best_d = 7, float("inf")
    for cid, c in std:
        d = sum((a - b) ** 2 for a, b in zip(rgb, c))
        if d < best_d:
            best_id, best_d = cid, d
    return best_id


# ── Theme definitions ─────────────────────────────────────────────────
# fg / bg are each (start_rgb, end_rgb).  Equal endpoints → solid colour;
# different endpoints → vertical gradient.
#
# All palettes derived from colour-wheel harmonies:
#   Analogous    ≤ 30°   — natural, soothing
#   Complementary  180°  — maximum contrast
#   Split-comp.  150/210° — contrast with less tension
#   Triadic       120°   — balanced vibrancy
#   Golden angle  137.5° — φ-based organic spread
#   Monochrome           — single hue, varying lightness
#
# Background lightness kept ≤ 0.08 so the cat silhouette pops.

THEMES = {
    "classic": {
        "desc": "Original monochrome  (white on black)",
        "harmony": "none",
        "fg": (_hsl_to_rgb1000(0, 0, 1.0), _hsl_to_rgb1000(0, 0, 1.0)),
        "bg": (_hsl_to_rgb1000(0, 0, 0.0), _hsl_to_rgb1000(0, 0, 0.0)),
    },
    "ember": {
        "desc": "Warm fire gradient   (analogous 15\u00b0\u201345\u00b0)",
        "harmony": "analogous",
        "fg": (_hsl_to_rgb1000(15, 1.0, 0.55), _hsl_to_rgb1000(45, 1.0, 0.55)),
        "bg": (_hsl_to_rgb1000(10, 0.8, 0.08), _hsl_to_rgb1000(30, 0.6, 0.05)),
    },
    "ocean": {
        "desc": "Deep sea gradient    (analogous 190\u00b0\u2013220\u00b0)",
        "harmony": "analogous",
        "fg": (_hsl_to_rgb1000(190, 1.0, 0.6), _hsl_to_rgb1000(220, 0.9, 0.6)),
        "bg": (_hsl_to_rgb1000(210, 0.8, 0.06), _hsl_to_rgb1000(230, 0.7, 0.04)),
    },
    "forest": {
        "desc": "Lush canopy gradient (analogous 100\u00b0\u2013140\u00b0)",
        "harmony": "analogous",
        "fg": (_hsl_to_rgb1000(100, 0.8, 0.55), _hsl_to_rgb1000(140, 0.7, 0.4)),
        "bg": (_hsl_to_rgb1000(120, 0.6, 0.05), _hsl_to_rgb1000(140, 0.5, 0.03)),
    },
    "sunset": {
        "desc": "Dusk sky gradient    (split-comp. 20\u00b0\u2192280\u00b0)",
        "harmony": "split-complementary",
        "fg": (_hsl_to_rgb1000(20, 1.0, 0.6), _hsl_to_rgb1000(280, 0.8, 0.55)),
        "bg": (_hsl_to_rgb1000(340, 0.5, 0.06), _hsl_to_rgb1000(260, 0.5, 0.04)),
    },
    "lavender": {
        "desc": "Soft purple gradient (analogous 260\u00b0\u2013300\u00b0)",
        "harmony": "analogous",
        "fg": (_hsl_to_rgb1000(260, 0.7, 0.7), _hsl_to_rgb1000(300, 0.6, 0.65)),
        "bg": (_hsl_to_rgb1000(270, 0.5, 0.06), _hsl_to_rgb1000(290, 0.4, 0.04)),
    },
    "matrix": {
        "desc": "Terminal green       (monochrome 120\u00b0)",
        "harmony": "monochrome",
        "fg": (_hsl_to_rgb1000(120, 1.0, 0.5), _hsl_to_rgb1000(120, 1.0, 0.5)),
        "bg": (_hsl_to_rgb1000(0, 0, 0.0), _hsl_to_rgb1000(0, 0, 0.0)),
    },
    "golden": {
        "desc": "Gold-to-teal         (golden angle 45\u00b0\u2192182.5\u00b0)",
        "harmony": "golden-angle",
        "fg": (_hsl_to_rgb1000(45, 0.9, 0.55), _hsl_to_rgb1000(182.5, 0.8, 0.45)),
        "bg": (_hsl_to_rgb1000(45, 0.5, 0.05), _hsl_to_rgb1000(182.5, 0.4, 0.04)),
    },
    "candy": {
        "desc": "Pink-to-mint         (triadic 330\u00b0\u219290\u00b0)",
        "harmony": "triadic",
        "fg": (_hsl_to_rgb1000(330, 0.9, 0.65), _hsl_to_rgb1000(90, 0.8, 0.55)),
        "bg": (_hsl_to_rgb1000(330, 0.4, 0.05), _hsl_to_rgb1000(90, 0.3, 0.04)),
    },
    "arctic": {
        "desc": "Ice field gradient   (analogous 200\u00b0\u2013220\u00b0)",
        "harmony": "analogous",
        "fg": (_hsl_to_rgb1000(200, 0.3, 0.85), _hsl_to_rgb1000(220, 0.7, 0.6)),
        "bg": (_hsl_to_rgb1000(210, 0.6, 0.06), _hsl_to_rgb1000(220, 0.5, 0.04)),
    },
    "rose": {
        "desc": "Rose-to-teal         (complementary 350\u00b0\u2194170\u00b0)",
        "harmony": "complementary",
        "fg": (_hsl_to_rgb1000(350, 0.8, 0.6), _hsl_to_rgb1000(170, 0.7, 0.45)),
        "bg": (_hsl_to_rgb1000(350, 0.4, 0.06), _hsl_to_rgb1000(170, 0.3, 0.04)),
    },
    "rainbow": {
        "desc": "Full spectrum rainbow (hue sweep 0\u00b0\u2192300\u00b0)",
        "harmony": "full-spectrum",
        "fg": (_hsl_to_rgb1000(0, 1.0, 0.5), _hsl_to_rgb1000(300, 1.0, 0.5)),
        "fg_stops": [
            _hsl_to_rgb1000(0, 1.0, 0.5),     # red
            _hsl_to_rgb1000(30, 1.0, 0.5),    # orange
            _hsl_to_rgb1000(60, 1.0, 0.5),    # yellow
            _hsl_to_rgb1000(120, 1.0, 0.5),   # green
            _hsl_to_rgb1000(180, 1.0, 0.5),   # cyan
            _hsl_to_rgb1000(240, 1.0, 0.5),   # blue
            _hsl_to_rgb1000(300, 1.0, 0.5),   # violet
        ],
        "bg": (_hsl_to_rgb1000(0, 0, 0.0), _hsl_to_rgb1000(0, 0, 0.0)),
    },
}


# ── Theme colour-pair initialisation ──────────────────────────────────

def _interpolate_stops(stops, t):
    """Interpolate through a list of RGB colour stops at position t (0-1)."""
    if len(stops) < 2:
        return stops[0] if stops else (0, 0, 0)
    t = max(0.0, min(1.0, t))
    n = len(stops) - 1
    seg = t * n
    idx = min(int(seg), n - 1)
    lt = seg - idx
    a, b = stops[idx], stops[idx + 1]
    return tuple(max(0, min(1000, int(a[i] + (b[i] - a[i]) * lt))) for i in range(3))


def _init_theme_pairs(theme_name, num_rows, can_custom):
    """Create per-row curses colour pairs for a vertical gradient.

    Returns a list of colour-pair IDs (one per row).  When the terminal
    supports >=256 custom colours each row gets a unique interpolated
    pair; otherwise a single solid pair using the nearest standard
    colour is returned for every row.

    Supports multi-stop foreground gradients via the optional 'fg_stops'
    theme key (used by rainbow and similar themes).
    """
    if num_rows <= 0:
        return []

    theme = THEMES.get(theme_name, THEMES["classic"])
    fg_start, fg_end = theme["fg"]
    bg_start, bg_end = theme["bg"]
    fg_stops = theme.get("fg_stops")  # None for two-point themes

    if not can_custom:
        fg_id = _nearest_std_color(fg_start)
        bg_id = _nearest_std_color(bg_start)
        curses.init_pair(1, fg_id, bg_id)
        return [1] * num_rows

    # Two colour IDs per gradient step (fg + bg), starting at 16 to
    # avoid clobbering the standard terminal palette.
    max_gradient = (min(curses.COLORS, 256) - 16) // 2
    max_pairs = min(curses.COLOR_PAIRS - 1, 32767)
    usable = max(1, min(num_rows, max_gradient, max_pairs))

    pairs = []
    last_gi = -1
    for i in range(num_rows):
        gi = min(i, usable - 1)
        if gi != last_gi:
            t = gi / max(1, usable - 1)
            if fg_stops:
                fg = _interpolate_stops(fg_stops, t)
            else:
                fg = tuple(
                    max(0, min(1000, int(s + (e - s) * t)))
                    for s, e in zip(fg_start, fg_end)
                )
            bg = tuple(
                max(0, min(1000, int(s + (e - s) * t)))
                for s, e in zip(bg_start, bg_end)
            )
            fg_cid = 16 + gi * 2
            bg_cid = 16 + gi * 2 + 1
            curses.init_color(fg_cid, *fg)
            curses.init_color(bg_cid, *bg)
            curses.init_pair(gi + 1, fg_cid, bg_cid)
            last_gi = gi
        pairs.append(gi + 1)
    return pairs


# ── GIF loader ────────────────────────────────────────────────────────

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


# ── ASCII renderers (unchanged) ───────────────────────────────────────

def _halfblock_ascii(gray_img, cols, rows):
    px = gray_img.load()
    bayer = ((0, 128), (192, 64))
    lines = []
    h = gray_img.size[1]
    for y in range(0, min(h, rows * 2), 2):
        line_chars = []
        for x in range(cols):
            top = px[x, y]
            bottom = px[x, y + 1] if y + 1 < h else 255
            tt = bayer[(y // 1) & 1][x & 1]
            bt = bayer[(y + 1) & 1][x & 1]
            top_dark = top < tt
            bottom_dark = bottom < bt
            if top_dark and bottom_dark:
                ch = "\u2588"
            elif top_dark and not bottom_dark:
                ch = "\u2580"
            elif not top_dark and bottom_dark:
                ch = "\u2584"
            else:
                ch = " "
            line_chars.append(ch)
        lines.append("".join(line_chars))
    return lines


def _braille_ascii(gray_img, cols, rows):
    px = gray_img.load()
    lines = []
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
            for dy in range(4):
                for dx in range(2):
                    yy = y0 + dy
                    xx = x0 + dx
                    val = px[xx, yy] if (xx < gray_img.size[0] and yy < gray_img.size[1]) else 255
                    thr = bayer[dy][dx]
                    dark = val < thr
                    if dark:
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
    px = gray_img.load()
    shades = [" ", "\u2591", "\u2592", "\u2593", "\u2588"]
    lines = []
    for y in range(rows):
        line_chars = []
        for x in range(cols):
            v = px[x, y]
            idx = 4 - min(4, int(v * 5 / 256))
            line_chars.append(shades[idx])
        lines.append("".join(line_chars))
    return lines


# ── TUI main loop ────────────────────────────────────────────────────

def _tui(stdscr, *, debug=False, fit_mode="contain", pixel_mode="auto",
         theme="classic"):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.noecho()
    curses.cbreak()

    # One-time colour bootstrap
    curses.start_color()
    curses.use_default_colors()
    can_custom_color = curses.can_change_color() and curses.COLORS >= 256

    frames, durations = _load_gif()
    idx = 0

    cache_key = None
    cached_ascii = None
    cached_info = None
    row_pairs = None
    src_w, src_h = frames[0].size

    def _detect_term_size():
        try:
            r, c = stdscr.getmaxyx()
            if r > 0 and c > 0:
                return c, r
        except Exception:
            pass
        try:
            c = int(os.environ.get("COLUMNS", 0))
            r = int(os.environ.get("LINES", 0))
            if c > 0 and r > 0:
                return c, r
        except Exception:
            pass
        try:
            ts = shutil.get_terminal_size(fallback=(80, 24))
            return ts.columns, ts.lines
        except Exception:
            pass
        try:
            out = subprocess.check_output(["stty", "size"], stderr=subprocess.DEVNULL)
            r, c = map(int, out.split())
            return c, r
        except Exception:
            pass
        try:
            c = int(subprocess.check_output(["tput", "cols"]))
            r = int(subprocess.check_output(["tput", "lines"]))
            return c, r
        except Exception:
            pass
        return 80, 24

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
                if ch in (ord('q'), 27):
                    break
            except curses.error:
                pass

            rows, cols = stdscr.getmaxyx()
            rows = max(1, rows)
            cols = max(1, cols)
            if rows <= 1 or cols <= 1:
                cols, rows = _detect_term_size()

            avail_rows = max(1, rows - (1 if debug else 0))

            size_key = (cols, avail_rows, fit_mode, pixel_mode)
            if size_key != cache_key:
                cache_key = size_key
                cached_ascii = []
                cached_info = None

                # Rebuild gradient colour pairs for new row count
                row_pairs = _init_theme_pairs(theme, avail_rows, can_custom_color)

                mode = pixel_mode
                if mode == "auto":
                    mode = "braille" if avail_rows >= 6 and cols >= 10 else "half"
                if mode == "braille":
                    canvas_w = cols * 2
                    canvas_h = avail_rows * 4
                    renderer = _braille_ascii
                elif mode == "half":
                    canvas_w = cols
                    canvas_h = avail_rows * 2
                    renderer = _halfblock_ascii
                else:
                    canvas_w = cols
                    canvas_h = avail_rows
                    renderer = _full_ascii
                if fit_mode == "cover":
                    scale = max(max(1, canvas_w) / max(1, src_w), max(1, canvas_h) / max(1, src_h))
                else:
                    scale = min(max(1, canvas_w) / max(1, src_w), max(1, canvas_h) / max(1, src_h))
                scaled_w = max(1, int(src_w * scale))
                scaled_h = max(1, int(src_h * scale))
                scaled_w = min(canvas_w, scaled_w)
                scaled_h = min(canvas_h, scaled_h)
                x_off = (canvas_w - scaled_w) // 2
                y_off = (canvas_h - scaled_h) // 2

                for fr in frames:
                    canvas = Image.new('L', (canvas_w, canvas_h), color=255)
                    g = fr.convert('L').resize((scaled_w, scaled_h), Image.NEAREST)
                    canvas.paste(g, (x_off, y_off))
                    cached_ascii.append(renderer(canvas, cols, avail_rows))
                cached_info = (scaled_w, scaled_h, x_off, y_off, mode, avail_rows)
                try:
                    curses.resizeterm(rows, cols)
                except curses.error:
                    pass

            stdscr.erase()
            if cached_ascii and row_pairs:
                lines = cached_ascii[idx]
                for r in range(min(len(lines), avail_rows)):
                    try:
                        attr = curses.color_pair(row_pairs[r]) if r < len(row_pairs) else 0
                        stdscr.addnstr(r, 0, lines[r], cols, attr)
                    except curses.error:
                        pass

            if debug and cached_info is not None:
                sw, sh, xo, yo, mode, avail_rows = cached_info
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
                right = min(cols - 1, left + (sw // (2 if mode == "braille" else 1)) - 1)
                bottom = min(avail_rows - 1, top + scaled_rows - 1)
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
                status = (
                    f"term {cols}x{rows} | src {src_w}x{src_h} | "
                    f"scaled {sw}x{sh} px | fit {fit_mode} | mode {mode} | "
                    f"theme {theme} | off {xo},{yo}"
                )
                try:
                    status_attr = curses.color_pair(row_pairs[-1]) if row_pairs else 0
                    stdscr.addnstr(rows - 1, 0, status.ljust(cols), cols, status_attr)
                except curses.error:
                    pass

            stdscr.refresh()

            next_time += durations[idx] / 1000.0
            sleep_for = max(0, next_time - time.time())
            time.sleep(sleep_for)
            idx = (idx + 1) % len(frames)
    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.curs_set(1)


# ── CLI entry point ───────────────────────────────────────────────────

def main():
    debug = False
    fit_mode = "contain"
    pixel_mode = "auto"
    theme = "classic"
    list_themes = False

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
        elif arg.startswith("--theme="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in THEMES:
                theme = val
        elif arg == "--list-themes":
            list_themes = True

    if list_themes:
        print("Available themes:\n")
        for name, info in THEMES.items():
            fg_s, fg_e = info["fg"]
            bg_s, bg_e = info["bg"]
            style = "gradient" if (fg_s != fg_e or bg_s != bg_e) else "solid"
            print(f"  {name:<12} {info['desc']}")
            print(f"  {'':<12} harmony: {info['harmony']}  |  style: {style}")
        print(f"\nUsage: meow --theme=<name>")
        return

    curses.wrapper(lambda stdscr: _tui(
        stdscr, debug=debug, fit_mode=fit_mode,
        pixel_mode=pixel_mode, theme=theme,
    ))
