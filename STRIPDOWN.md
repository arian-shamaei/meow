# silly-catui strip-down study

*How far can `meow` be stripped toward the machine while still running on the
majority of the world's embedded systems? Numbers below are **measured** from
the actual frame data in `c/meow_frames.h`, not estimated.*

## Bottom line

`meow` is already at the **C-source floor**: one C89 file, standard library
only. It is nowhere near the **embedded floor**. Two independent walls stop it
from running on the numeric majority of deployed machines (small
microcontrollers). Only one is about code; the bigger one is the 45 frames of
animation data, whose measured floor is **~1 KB** — a ~190x reduction.

## Footprint today

The `meow` binary is 249 KB. ~95% of it is the cat, not the program.

| component            | size    |
|----------------------|---------|
| frame RLE data       | 191 KB  |
| program code         | ~18 KB  |
| RAM decode buffer    | 12 KB (110x110, runtime) |
| timing tables        | 0.5 KB  |

## Wall 1 — environment (small job)

The program assumes a *hosted* C runtime and a text terminal. Most MCUs are
*freestanding* with neither. Four dependencies carry the whole assumption:

| dependency       | used for          | freestanding replacement    | code cost |
|------------------|-------------------|-----------------------------|-----------|
| stdio (`fputs`)  | pixels -> console | `putbyte()` hook (UART/fb)  | ~0        |
| nanosleep/Sleep  | frame timing      | `delay_ms()` hook (timer)   | ~0        |
| `malloc`         | line/prev buffers | static arrays               | shrinks   |
| `signal(SIGINT)` | Ctrl-C quit       | drop (no console)           | shrinks   |
| ioctl / locale   | term size + UTF-8 | fixed size, compile-time    | shrinks   |

Removing these *reduces* size and adds no logic — the `--scroll` path already
avoids cursor escapes. Cheap wall. It buys little reach alone because Wall 2
still stands.

## Wall 2 — size (the real research)

The cat is **only 12.8% ink** — mostly empty space, stored at 10 gray levels
via per-run RLE, a poor fit for a sparse silhouette. Measured floors from the
actual frame data:

| representation                    | size    | fits 32 KB flash?     |
|-----------------------------------|---------|-----------------------|
| raw 10-level 110^2 x45            | 532 KB  | no                    |
| current RLE (val+cnt)             | 191 KB  | no  <- HERE           |
| 1-bit silhouette 110^2 x45        | 66 KB   | no                    |
| 1-bit silhouette + gzip           | 9.5 KB  | yes                   |
| 1-bit 48x48 x8 frames (raw)       | 2.2 KB  | yes, even on 8-bit    |
| 1-bit 48x48 x8 frames + gzip      | 0.9 KB  | yes                   |

Two levers do almost all the work: **drop grayscale -> 1 bit** (10 levels are
invisible on a mono OLED) and **drop resolution/frame-count** (48x48x8 still
reads as the cat). Below ~2 KB, ship the data *raw* — a gzip decompressor costs
more code (~1-2 KB) than it saves at that scale.

## The purest form that reaches the majority

Runs on an 8-bit ATtiny-class part:

```
DATA   48x48 x 8 frames, 1-bit, stored raw ......... 2,304 B flash
CODE   bit-blit loop + delay + putbyte hook ........ ~750 B
RAM    no frame buffer; pixels read from flash ..... see the AVR caveat below
-----------------------------------------------------------------
TOTAL  3,051 B code+data (measured, `size meow_min.o`) — no OS, no libc
```

### Confirmed on real hardware (Arduino Micro, ATmega32U4)

Not a projection any more — `avr/meow_micro` runs the same 8 frames on a real
8-bit AVR with 32 KB flash and 2.5 KB SRAM, rendering over USB serial:

| measure | value | headroom |
|---------|-------|----------|
| flash (program + frames) | 6,330 B | 22% of 28,672 B |
| **SRAM (global variables)** | **161 B** | **6% of 2,560 B** |

**The AVR caveat, which cost a working flash:** "renders straight from flash"
is not automatic on a Harvard-architecture chip. `const` alone does NOT keep an
array in flash — avr-gcc copies it into SRAM at startup, so the 2,304-byte blob
would have consumed ~90% of the 32U4's SRAM before `Serial`'s buffers and the
stack, and the board would compile fine and then hang. The data must be marked
`PROGMEM` and read with `pgm_read_byte()`. With that, SRAM use drops to 161 B.
See `avr/meow_micro/catmin_avr.h`, which stores the blob in flash on AVR and as
a normal array everywhere else.

**This is built and verified in `min/`.** `meow_min.c` bakes in the 2,304-byte
data blob and renders the animated cat through a single `cat_putbyte()` hook
(wired to stdout here; swap for UART or a framebuffer on a real MCU). The core
`cat_play`/`render` path touches no libc at all. Measured on this machine:

| artifact                     | size        |
|------------------------------|-------------|
| original `meow` binary       | 248,936 B   |
| stripped `meow_min` (Mach-O) | 33,496 B    |
| **object code+data floor**   | **3,051 B** |
| frame data: 195,440 -> 2,304 | **85x smaller** |

The 33 KB Mach-O figure is almost all macOS runtime and startup a freestanding
target never links; the 3,051 B object floor is what actually lands in flash.

The same core scales back up to a desktop terminal by swapping the one output
hook. Mac / Windows / Linux fall out for free — they are the *easy* targets,
not the constraint.

## Two findings worth flagging

- **XOR inter-frame delta backfired.** Measured: 14.0 KB vs 9.5 KB for plain
  gzip. Motion between frames is large enough that XOR shatters the long
  zero-runs gzip relies on. The obvious temporal-delta idea is *wrong* here.
- **Frame selection matters as much as frame count.** 8 of the 45 frames are
  near-duplicate held frames (~0 pixel motion). Sampling 8 frames evenly *by
  index* lands on some of these and the spin looks stuck. Sampling evenly along
  cumulative *motion* (arc length) instead spreads the 8 picks across the full
  rotation — same 2,304 bytes, but the cat actually spins. Picked frames:
  `[0, 9, 13, 19, 24, 30, 36, 40]`.
- **The 12.8% ink density is the whole story.** Every good lever (1-bit, gzip,
  low-res) works because the image is sparse. Any scheme that ignores sparsity
  (like the current fixed-cost RLE) leaves ~20x on the table.

## Reproducing the numbers

The measurements come from expanding the RLE arrays in `c/meow_frames.h` back
to raw frames, then re-encoding under each scheme (1-bit threshold at level >=2,
nearest-neighbour downscale, gzip -9). See `min/` for a live stripped build that
bakes in the 48x48x8x1-bit data and renders the cat with a single output hook.
