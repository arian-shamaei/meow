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

int main(int argc, char **argv)
{
    static unsigned char frame[MEOW_SIZE * MEOW_SIZE];
    const char *ramp = MEOW_RAMP;
    char *line;
    int force_w = 0, force_h = 0;
    int loops = 0;          /* 0 = forever */
    int played = 0;
    int term_cols, term_rows, w, h;
    int i, x, y, f;

    /* ---- args ---- */
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--scroll") == 0) {
            g_use_cursor = 0;
        } else if (strcmp(argv[i], "--once") == 0) {
            loops = 1;
        } else if (strcmp(argv[i], "--loops") == 0 && i + 1 < argc) {
            loops = atoi(argv[++i]);
        } else if (argv[i][0] >= '0' && argv[i][0] <= '9') {
            if (!force_w) force_w = atoi(argv[i]);
            else if (!force_h) force_h = atoi(argv[i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("usage: meow [--loops N] [--once] [--scroll] [WIDTH HEIGHT]\n");
            return 0;
        }
    }

    /* ---- output size ---- */
    term_cols = force_w ? force_w : env_int("COLUMNS");
    term_rows = force_h ? force_h : env_int("LINES");
    if (force_w && force_h) {
        w = force_w;
        h = force_h;
    } else {
        pick_size(term_cols, term_rows, &w, &h);
    }
    if (w > MEOW_SIZE * 4) w = MEOW_SIZE * 4;   /* sanity cap */
    if (h > MEOW_SIZE * 4) h = MEOW_SIZE * 4;

    line = (char *)malloc((size_t)w + 1);
    if (!line) return 1;
    line[w] = '\0';

    signal(SIGINT, on_sigint);

    if (g_use_cursor) {
        enable_vt();                         /* Win10+: make ANSI work */
        fputs("\033[2J\033[?25l", stdout);   /* clear + hide cursor */
    }

    /* ---- animation loop ---- */
    while (g_running) {
        for (f = 0; f < MEOW_NFRAMES && g_running; f++) {
            decode_frame(f, frame);
            if (g_use_cursor) {
                fputs("\033[H", stdout);      /* cursor home */
            } else {
                fputc('\f', stdout);          /* form feed (teletype) */
            }
            for (y = 0; y < h; y++) {
                int sy = (int)((long)y * MEOW_SIZE / h);
                const unsigned char *srow = frame + (long)sy * MEOW_SIZE;
                for (x = 0; x < w; x++) {
                    int sx = (int)((long)x * MEOW_SIZE / w);
                    unsigned char lv = srow[sx];
                    line[x] = ramp[lv < MEOW_LEVELS ? lv : MEOW_LEVELS - 1];
                }
                fputs(line, stdout);
                fputc('\n', stdout);
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
