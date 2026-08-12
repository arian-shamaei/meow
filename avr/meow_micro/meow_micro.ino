/*
 * meow_micro.ino -- silly-cat on an Arduino Micro (ATmega32U4), over USB serial.
 *
 * This is the min/ core with its two hooks pointed at the board:
 *
 *     cat_putbyte  -> Serial.write   (USB CDC; needs no display hardware)
 *     cat_delay_ms -> delay
 *
 * The one thing that is NOT just a hook swap is where the frames live. AVR is
 * a Harvard machine: `const` alone still copies an array into SRAM at startup,
 * and the 2304-byte frame blob does not fit the 32U4's 2560 bytes of SRAM. So
 * the data is kept in flash (PROGMEM) and read a byte at a time -- see
 * CAT_STORE / CAT_RD_BYTE in catmin_avr.h. No frame buffer is allocated at all.
 *
 * Output is 24x12 characters: each character is a 2x4 block of pixels shaded
 * by how many are lit. Plain ASCII, so any serial monitor renders it, and the
 * frames scroll rather than needing cursor control (the teletype-safe mode).
 *
 * Regenerate catmin_avr.h after changing c/meow_frames.h:
 *     python3 avr/gen_catmin_avr.py
 */

#include "catmin_avr.h"

#define BAUD_RATE 115200

/* ---- platform hooks: the only board-specific code ---------------------- */
static void cat_putbyte(unsigned char b) { Serial.write(b); }
static void cat_delay_ms(unsigned int ms) { delay(ms); }
/* ----------------------------------------------------------------------- */

/* 9 shades for the 0..8 pixels that can be lit in one 2x4 block. */
static const char RAMP[] = " .:-=+*#@";

/* One pixel of the frame starting at byte `base` in cat_bits. */
static unsigned char getpx(unsigned int base, unsigned char y, unsigned char x)
{
    unsigned int i = (unsigned int)y * CAT_D + x;
    unsigned char byte = CAT_RD_BYTE(&cat_bits[base + (i >> 3)]);
    return (byte >> (7 - (i & 7))) & 1;
}

/* Draw one frame as 24x12 shaded ASCII, straight from flash. */
static void render(unsigned int base)
{
    unsigned char cy, cx, dy, dx;
    for (cy = 0; cy < CAT_D / 4; cy++) {
        for (cx = 0; cx < CAT_D / 2; cx++) {
            unsigned char lit = 0;
            for (dy = 0; dy < 4; dy++) {
                for (dx = 0; dx < 2; dx++) {
                    lit += getpx(base, cy * 4 + dy, cx * 2 + dx);
                }
            }
            cat_putbyte((unsigned char)RAMP[lit]);
        }
        cat_putbyte('\r');
        cat_putbyte('\n');
    }
}

void setup()
{
    /* Deliberately no `while (!Serial)`: the board must keep running when no
     * monitor is attached, not block forever waiting for one. */
    Serial.begin(BAUD_RATE);
}

void loop()
{
    for (unsigned char f = 0; f < CAT_NF; f++) {
        /* F() keeps the literal in flash too. The heartbeat line makes
         * liveness checkable by reading the port back. */
        Serial.print(F("-- meow frame "));
        Serial.print(f);
        Serial.println(F(" --"));
        render((unsigned int)f * CAT_BPF);
        cat_delay_ms(CAT_RD_WORD(&cat_ms[f]));
    }
}
