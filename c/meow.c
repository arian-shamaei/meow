/*
 * meow.c  --  silly-cat, the native edition.
 *
 * One C89 source file. Standard library only. No external assets: the
 * whole animation is embedded (see meow_frames.h). Compile it and it
 * LIVES on the machine -- a native program, no interpreter, no browser,
 * no network. The aim is maximum reach: anything with a C compiler and a
 * text display, from a 1980s terminal to a modern laptop.
 *
 * Build:   cc -O2 -o meow meow.c        (or any C89 compiler)
 *          cl meow.c                    (MSVC)
 * Run:     ./meow                       (Ctrl-C to quit)
 *          ./meow 120 40                (force WIDTHxHEIGHT in chars)
 *          ./meow --loops 3             (play 3 times then exit)
 *          ./meow --scroll              (no cursor control; for teletypes)
 *
 * Output is printable ASCII shaded with " .:-=+*#%@". Frame redraw uses
 * the near-universal ANSI "home" escape; --scroll avoids even that.
 */

#if defined(__unix__) || defined(__APPLE__)
#  define _POSIX_C_SOURCE 199309L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>

#include "meow_frames.h"

#if defined(__unix__) || defined(__APPLE__)
#  include <sys/ioctl.h>
#  include <unistd.h>
#endif

/* ---- portable millisecond sleep ----------------------------------- */
#if defined(_WIN32)
#  include <windows.h>
static void sleep_ms(unsigned ms) { Sleep(ms); }
/* Win10+ consoles need VT processing turned on for ANSI escapes to work;
 * harmless no-op (returns failure) on older consoles -- use --scroll there. */
static void enable_vt(void)
{
#  ifdef ENABLE_VIRTUAL_TERMINAL_PROCESSING
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD mode = 0;
    if (h != INVALID_HANDLE_VALUE && GetConsoleMode(h, &mode)) {
        SetConsoleMode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);
    }
#  endif
}
#elif defined(__unix__) || defined(__APPLE__)
static void sleep_ms(unsigned ms)
{
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000U);
    ts.tv_nsec = (long)(ms % 1000U) * 1000000L;
    nanosleep(&ts, (struct timespec *)0);
}
static void enable_vt(void) { }
#else
/* last-resort pure-C89 wait: busy-loop on clock() (burns CPU, but runs
 * absolutely everywhere a hosted C implementation does). */
static void sleep_ms(unsigned ms)
{
    clock_t target = clock() + (clock_t)((double)ms / 1000.0 * CLOCKS_PER_SEC);
    while (clock() < target) {
        /* spin */
    }
}
static void enable_vt(void) { }
#endif

/* ---- clean shutdown on Ctrl-C -------------------------------------- */
static volatile int g_running = 1;
static int g_use_cursor = 1;

static void on_sigint(int sig)
{
    (void)sig;
    g_running = 0;
}

/* Expand one RLE frame into dst (MEOW_SIZE*MEOW_SIZE level bytes). */
static void decode_frame(int f, unsigned char *dst)
{
    unsigned long r;
    unsigned long start = meow_frame_off[f];
    unsigned long end = meow_frame_off[f + 1];
    unsigned long p = 0;
    for (r = start; r < end; r++) {
        unsigned char v = meow_rle_value[r];
        int c = (int)meow_rle_count[r];
        while (c-- > 0) {
            dst[p++] = v;
        }
    }
}

/* Decide output WIDTH x HEIGHT (chars) honouring the ~2:1 cell aspect so
 * the square cat does not look vertically stretched. Fit inside term. */
static void pick_size(int term_cols, int term_rows, int *out_w, int *out_h)
{
    int w, h;
    if (term_cols < 1) term_cols = 80;
    if (term_rows < 1) term_rows = 24;
    /* square cat: a cell is ~twice as tall as wide, so W ~= 2*H. */
    w = term_cols;
    if (w > 2 * term_rows) w = 2 * term_rows;
    h = w / 2;
    if (h < 1) h = 1;
    if (h > term_rows) h = term_rows;
    if (w < 1) w = 1;
    *out_w = w;
    *out_h = h;
}

static int env_int(const char *name)
{
    const char *s = getenv(name);
    if (!s || !*s) return 0;
    return atoi(s);
}

/* Ask the OS for the real terminal size. Returns 1 on success. */
static int query_term_size(int *cols, int *rows)
{
#if defined(_WIN32)
    CONSOLE_SCREEN_BUFFER_INFO csbi;
    HANDLE hh = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hh != INVALID_HANDLE_VALUE && GetConsoleScreenBufferInfo(hh, &csbi)) {
        int c = csbi.srWindow.Right - csbi.srWindow.Left + 1;
        int r = csbi.srWindow.Bottom - csbi.srWindow.Top + 1;
        if (c > 0 && r > 0) { *cols = c; *rows = r; return 1; }
    }
    return 0;
#elif defined(__unix__) || defined(__APPLE__)
    struct winsize ws;
    if (ioctl(1, TIOCGWINSZ, &ws) == 0 && ws.ws_col > 0 && ws.ws_row > 0) {
        *cols = ws.ws_col;
        *rows = ws.ws_row;
        return 1;
    }
    return 0;
#else
    (void)cols; (void)rows;
    return 0;            /* no portable way -> caller falls back */
#endif
}

/* Effective terminal size: forced args win, else ask the OS, else the
 * COLUMNS/LINES env vars, else a sane default. */
static void get_size(int force_w, int force_h, int *cols, int *rows)
{
    int c = 0, r = 0;
    if (!query_term_size(&c, &r)) {
        c = env_int("COLUMNS");
        r = env_int("LINES");
    }
    if (c < 1) c = 80;
    if (r < 1) r = 24;
    *cols = force_w ? force_w : c;
    *rows = force_h ? force_h : r;
}

/* Any frame level >= this counts as "ink" for the braille silhouette.
 * The frames are quantised 0 (background) .. MEOW_LEVELS-1 (darkest); a low
 * cut keeps thin lines, matching the cleaned-up original look. */
#define MEOW_INK 2

/* Braille dot bit per (row 0..3, col 0..1), Unicode U+28xx layout. */
static const unsigned char MEOW_DOT[4][2] = {
    { 0x01, 0x08 },
    { 0x02, 0x10 },
    { 0x04, 0x20 },
    { 0x40, 0x80 }
};

/* Write one cat row (image row y of h) as glyph bytes; return new ptr. */
static char *render_row(char *p, int y, int w, int h, int braille,
                        const unsigned char *frame, const char *ramp)
{
    int x;
    if (braille) {
        for (x = 0; x < w; x++) {
            int bits = 0, dy, dx;
            for (dy = 0; dy < 4; dy++) {
                int sy = (int)((long)(y * 4 + dy) * MEOW_SIZE / (h * 4));
                const unsigned char *srow = frame + (long)sy * MEOW_SIZE;
                for (dx = 0; dx < 2; dx++) {
                    int sx = (int)((long)(x * 2 + dx) * MEOW_SIZE / (w * 2));
                    if (srow[sx] >= MEOW_INK) bits |= MEOW_DOT[dy][dx];
                }
            }
            if (bits == 0) {
                *p++ = ' ';
            } else {
                *p++ = (char)0xE2;
                *p++ = (char)(0xA0 | (bits >> 6));
                *p++ = (char)(0x80 | (bits & 0x3F));
            }
        }
    } else {
        int sy = (int)((long)y * MEOW_SIZE / h);
        const unsigned char *srow = frame + (long)sy * MEOW_SIZE;
        for (x = 0; x < w; x++) {
            int sx = (int)((long)x * MEOW_SIZE / w);
            unsigned char lv = srow[sx];
            *p++ = ramp[lv < MEOW_LEVELS ? lv : MEOW_LEVELS - 1];
        }
    }
    return p;
}

/* Capability check: does this environment support UTF-8 (and therefore the
 * sharper braille cat)? We can't read "firmware" directly, so we use the
 * locale -- the portable proxy every Unix-ish system exposes. LC_ALL beats
 * LC_CTYPE beats LANG; the first one that's set decides. No locale at all
 * (typical of old/bare systems) -> assume limited -> ASCII. */
static int supports_unicode(void)
{
    const char *names[3];
    int i, j;
    names[0] = "LC_ALL";
    names[1] = "LC_CTYPE";
    names[2] = "LANG";
    for (i = 0; i < 3; i++) {
        const char *v = getenv(names[i]);
        if (!v || !v[0]) continue;
        for (j = 0; v[j] && v[j + 1] && v[j + 2]; j++) {
            if ((v[j] == 'u' || v[j] == 'U') &&
                (v[j + 1] == 't' || v[j + 1] == 'T') &&
                (v[j + 2] == 'f' || v[j + 2] == 'F')) {
                return 1;            /* "utf" found -> UTF-8 */
            }
        }
        return 0;                    /* locale set but not UTF-8 */
    }
    return 0;                        /* no locale -> assume ASCII */
}

int main(int argc, char **argv)
{
    static unsigned char frame[MEOW_SIZE * MEOW_SIZE];
    const char *ramp = MEOW_RAMP;
    char *line;
    size_t line_cap;
    int force_w = 0, force_h = 0;
    int loops = 0;          /* 0 = forever */
    int played = 0;
    int term_cols, term_rows, w, h;
    int i, y, f;
    int braille = -1;       /* -1 = auto-detect, 0 = ascii, 1 = braille */

    /* ---- args ---- */
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--scroll") == 0) {
            g_use_cursor = 0;
        } else if (strcmp(argv[i], "--once") == 0) {
            loops = 1;
        } else if (strcmp(argv[i], "--loops") == 0 && i + 1 < argc) {
            loops = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--ascii") == 0) {
            braille = 0;
        } else if (strcmp(argv[i], "--unicode") == 0 ||
                   strcmp(argv[i], "--braille") == 0) {
            braille = 1;
        } else if (strcmp(argv[i], "--auto") == 0) {
            braille = -1;
        } else if (argv[i][0] >= '0' && argv[i][0] <= '9') {
            if (!force_w) force_w = atoi(argv[i]);
            else if (!force_h) force_h = atoi(argv[i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("usage: meow [--loops N] [--once] [--scroll]"
                   " [--ascii|--unicode] [WIDTH HEIGHT]\n");
            return 0;
        }
    }

    /* Choose the cat the machine can show: braille where UTF-8 is
     * supported (the cleaned-up original look), ASCII everywhere else. */
    if (braille < 0) braille = supports_unicode();

    /* ---- initial size (real terminal, auto-scaled) ---- */
    {
        int cc, rr;
        get_size(force_w, force_h, &cc, &rr);
        term_cols = cc;
        term_rows = rr;
        if (force_w && force_h) { w = force_w; h = force_h; }
        else pick_size(cc, rr, &w, &h);
    }
    if (w > MEOW_SIZE * 4) w = MEOW_SIZE * 4;   /* sanity cap */
    if (h > MEOW_SIZE * 4) h = MEOW_SIZE * 4;

    /* line holds left padding + a full row of braille (3 bytes/cell) */
    line_cap = (size_t)term_cols * 4 + 16;
    line = (char *)malloc(line_cap);
    if (!line) return 1;

    signal(SIGINT, on_sigint);

    if (g_use_cursor) {
        enable_vt();                         /* Win10+: make ANSI work */
        fputs("\033[2J\033[?25l", stdout);   /* clear + hide cursor */
    }

    /* ---- animation loop ---- */
    while (g_running) {
        for (f = 0; f < MEOW_NFRAMES && g_running; f++) {
            int top_pad, left_pad, sr, nrows;
            decode_frame(f, frame);

            /* live re-scale on terminal resize (skip if size forced) */
            if (g_use_cursor && !(force_w && force_h)) {
                int cc, rr;
                get_size(force_w, force_h, &cc, &rr);
                if (cc != term_cols || rr != term_rows) {
                    term_cols = cc;
                    term_rows = rr;
                    pick_size(cc, rr, &w, &h);
                    if (w > MEOW_SIZE * 4) w = MEOW_SIZE * 4;
                    if (h > MEOW_SIZE * 4) h = MEOW_SIZE * 4;
                    if ((size_t)cc * 4 + 16 > line_cap) {
                        char *nl = (char *)realloc(line, (size_t)cc * 4 + 16);
                        if (nl) { line = nl; line_cap = (size_t)cc * 4 + 16; }
                    }
                    fputs("\033[2J", stdout);          /* clear on resize */
                }
            }

            top_pad = g_use_cursor ? (term_rows - h) / 2 : 0;
            left_pad = g_use_cursor ? (term_cols - w) / 2 : 0;
            if (top_pad < 0) top_pad = 0;
            if (left_pad < 0) left_pad = 0;
            nrows = g_use_cursor ? term_rows : h;

            if (g_use_cursor) fputs("\033[H", stdout);   /* cursor home */
            else fputc('\f', stdout);                    /* form feed */

            for (sr = 0; sr < nrows; sr++) {
                char *p = line;
                y = sr - top_pad;
                if (y >= 0 && y < h) {
                    int lp;
                    for (lp = 0; lp < left_pad; lp++) *p++ = ' ';
                    p = render_row(p, y, w, h, braille, frame, ramp);
                }
                *p = '\0';
                fputs(line, stdout);
                if (g_use_cursor) fputs("\033[K", stdout);   /* clear to EOL */
                if (sr < nrows - 1 || !g_use_cursor) fputc('\n', stdout);
            }
            fflush(stdout);
            sleep_ms(meow_duration_ms[f]);
        }
        played++;
        if (loops > 0 && played >= loops) break;
    }

    if (g_use_cursor) {
        fputs("\033[?25h\n", stdout);          /* show cursor */
        fflush(stdout);
    }
    free(line);
    return 0;
}
