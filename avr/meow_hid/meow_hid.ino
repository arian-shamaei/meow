/*
 * meow_hid.ino -- silly-cat as a USB HID keyboard (Arduino Micro / 32U4).
 *
 * The point: plug the board into ANY computer (Mac/Windows/Linux) and it types
 * the cat into whatever text field has focus -- zero host software, because
 * every OS accepts a USB keyboard with no driver. It is ALSO a serial port
 * (composite USB), which this sketch uses for two things:
 *   - timing telemetry (how long a frame takes to "type")
 *   - a safety gate: it does NOT type on boot, only on a serial command, so
 *     testing it on a live machine can't spray keystrokes into random windows.
 *
 * Honest limits, by construction:
 *   - HID sends US-layout scancodes; punctuation (@ # = etc.) lands on
 *     different glyphs on AZERTY/QWERTZ hosts. This is US-layout-primary.
 *   - a keyboard can't address the screen, so "animation" = clear the field
 *     (Ctrl+A, Delete) and retype. Throughput is the whole question -> measure.
 *
 * Serial commands (115200):
 *   'm'  type ONE frame, report "typed N chars in T ms"
 *   'a'  animate: clear+retype frames until any other byte arrives
 *   's'  stop
 */

#include "catmin_avr.h"
#include <Keyboard.h>

#define ROWS (CAT_D / 4)   /* 12 */
#define COLS (CAT_D / 2)   /* 24 */

/* US-layout ramp, 9 shades for the 0..8 pixels lit in a 2x4 block. */
static const char RAMP[9] = { ' ', '.', ':', '-', '=', '+', '*', '#', '@' };

static unsigned char getpx(unsigned int base, unsigned char y, unsigned char x)
{
    unsigned int i = (unsigned int)y * CAT_D + x;
    unsigned char byte = CAT_RD_BYTE(&cat_bits[base + (i >> 3)]);
    return (byte >> (7 - (i & 7))) & 1;
}

/* Type one frame into the focused field. Returns keystrokes sent. */
static unsigned int type_frame(unsigned int base)
{
    unsigned char cy, cx, dy, dx;
    unsigned int keys = 0;
    for (cy = 0; cy < ROWS; cy++) {
        for (cx = 0; cx < COLS; cx++) {
            unsigned char lit = 0;
            for (dy = 0; dy < 4; dy++)
                for (dx = 0; dx < 2; dx++)
                    lit += getpx(base, cy * 4 + dy, cx * 2 + dx);
            Keyboard.write(RAMP[lit]);
            keys++;
        }
        Keyboard.write('\n');
        keys++;
    }
    return keys;
}

/* Clear the text field so the next frame overwrites in place. */
static void clear_field(void)
{
    Keyboard.press(KEY_LEFT_CTRL);
    Keyboard.press('a');
    delay(15);
    Keyboard.releaseAll();
    delay(15);
    Keyboard.write(KEY_DELETE);
}

/* Product mode: type the cat on boot into whatever window has focus, with no
 * serial command -- the actual "plug into any computer and it appears" build.
 * Left OFF by default so testing on a live machine can't spray keystrokes.
 * Flip to 1 (or compile with -DTYPE_ON_BOOT=1) for the deployable version. */
#ifndef TYPE_ON_BOOT
#define TYPE_ON_BOOT 0
#endif

static void animate(void)
{
    unsigned char f = 0;
    while (!Serial.available()) {          /* any serial byte stops it */
        clear_field();
        type_frame((unsigned int)f * CAT_BPF);
        delay(CAT_RD_WORD(&cat_ms[f]));
        f = (f + 1) % CAT_NF;
    }
    Serial.println(F("stopped"));
}

void setup(void)
{
    Serial.begin(115200);
    Keyboard.begin();
#if TYPE_ON_BOOT
    delay(3000);      /* let USB enumerate + the user focus a text field */
    animate();
#endif
}

void loop(void)
{
    if (!Serial.available()) return;
    char c = Serial.read();

    if (c == 'm') {
        unsigned long t0 = millis();
        unsigned int keys = type_frame(0);
        unsigned long dt = millis() - t0;
        Serial.print(F("typed "));
        Serial.print(keys);
        Serial.print(F(" chars in "));
        Serial.print(dt);
        Serial.print(F(" ms  -> "));
        Serial.print((unsigned int)((unsigned long)keys * 1000UL / (dt ? dt : 1)));
        Serial.println(F(" chars/s"));
    } else if (c == 'a') {
        animate();
    }
}
