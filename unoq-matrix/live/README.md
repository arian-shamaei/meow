# Uno Q Matrix — Live kaleidoscope (on-board rendering)

Mirrored geometric patterns on the 8×13 LED matrix, controlled from a web page,
optionally driven by a live audio/CPU signal.

## Why the board is authoritative (this fixed "web page ≠ board")

Measured on this core: **`Serial.read()` costs ~6 ms per BYTE**
(round-trip: 1 B = 8 ms, 8 B = 90 ms, 104 B = 1173 ms). So streaming 104-byte
frames could never exceed **~1.6 fps** — the host kept stuffing the USB buffer
and the panel displayed frames many seconds stale, which is exactly the
mismatch that was observed.

Meanwhile the MCU is enormously fast: **200 `matrix.draw()` calls in ~1 ms**,
and 200 full kaleidoscope frames computed in 29 ms (~6900 fps).

So the animation now runs **on the STM32**, and the host sends only ~10 bytes
of parameters. Reactive (sensor) updates are **fire-and-forget at 10 Hz** —
verified working; it was the *ack round-trip* (~670 ms) that was slow, not the
writes.

## Files
- `kaleido_fw/` — firmware: renders all 7 patterns on-board at ~60 fps.
- `kaleido_server.py` — bridge + web UI (current).
- `matrix_serial_slave/`, `board_server.py` — the older frame-streaming
  approach. Superseded (that is what hit the 1.6 fps wall); kept for reference.

## Run
```
arduino-cli compile -b arduino:zephyr:unoq kaleido_fw
arduino-cli upload  -b arduino:zephyr:unoq -p <PORT> kaleido_fw
python3 kaleido_server.py          # needs: pip install pyserial
open http://localhost:8080
```

**Uploads are flaky on this board** (the Linux side flashes the STM32 over
SWD). A failed upload is silent — the board just keeps running the previous
sketch. Always verify: the firmware prints `KFW lvl=<n>` every 500 ms. Retry
the upload until you see it. If the USB device disappears entirely, wait ~20 s;
it re-enumerates on its own.

## Two display modes
- **Kaleidoscope** — mirrored procedural patterns (below).
- **Scrolling text** — paste any text, hit *Send to board*, and it scrolls
  across the panel in a 5x7 font. Up to **1400 characters**, stored in the
  MCU's RAM and scrolled locally, so it keeps running with no host attached.
  Font is **ArduinoGraphics' hand-designed `Font_5x7`** (`arduino-cli lib
  install ArduinoGraphics`) — a downscaled system font produced uneven,
  wonky glyphs. The browser preview embeds the same font data, so it matches
  the panel.

  Smoothness (all three were needed):
  1. Scroll uses **real elapsed time** (`micros()`), not an assumed 16 ms
     frame — serial work makes the loop period vary, and a fixed step turned
     that into stutter.
  2. **Sub-pixel anti-aliased motion**: each column blends the two neighbouring
     source columns by the fractional offset, so text glides instead of
     jumping a whole LED at a time.
  3. **Staged upload + atomic commit** (`0xA7` appends to a shadow buffer,
     `0xA8` swaps it in). Appending live meant the text length changed
     mid-scroll on every chunk — the longer the text, the worse the glitching.

  Measured ~55 fps on-board with 1200 characters loaded.

  Text upload is chunked (32 bytes/packet, ~0.3 s each) because of the
  ~6 ms/byte serial cost — roughly 1 s per 100 characters. It is a one-time
  upload, not a per-frame stream.

## Controls
- **Pattern**: spin, rings, star, rays, diamond, grid, plasma — all mirrored
  about both axes, with N-fold rotational symmetry.
- **Speed / Segments / Scale / Brightness / Contrast**.
- **Reactive**: Off · Audio · CPU load. Audio input = **Mic** or
  **System audio** (BlackHole 2ch — route your music to it to make the
  pattern dance to what is playing). macOS will ask for mic permission.
- **Drives**: which parameters the live level modulates — Brightness, Scale,
  Speed, Segments (any combination).

## Sensors ON the board (verified against the device tree, not the manual)

No *discrete* sensors — the compiled device tree
(`firmwares/zephyr-arduino_uno_q_stm32u585xx.dts`) has no I2C sensor children,
so there is no IMU, microphone, or light sensor.

But the STM32U585 itself has two internal sensors, both `status = "okay"`,
and **both are working here**:

| Sensor | Node | Channel | Reads |
|---|---|---|---|
| Die temperature (factory calibrated) | `die_temp` / `st,stm32-temp-cal` | ADC1 ch19 | ~33 °C |
| Internal reference → real VDDA rail | `vref1` / `st,stm32-vref` | ADC1 ch0 | ~3317 mV |

`vbat1` also exists but is `status = "disabled"`.

Reading them took three non-obvious steps (all in `kaleido_fw.ino`):
1. `CONFIG_SENSOR` is **not** compiled into this core, so Zephyr's sensor API
   is unavailable — read the channels through the raw ADC API instead
   (`z_impl_adc_read` *is* an exported symbol, so sketches may call it).
2. `adc1` is marked **`zephyr,deferred-init`**, so it is not ready at boot.
   Call `analogRead(A0)` once to bring the device up.
3. Nothing enables the internal analog paths without the sensor driver — set
   **VREFEN (bit 22) and VSENSESEL (bit 23)** in the ADC common `CCR`
   (`ADC1_BASE + 0x308`) by hand.
   Then scale the raw sample by `VDDA/3000` before applying TS_CAL, because
   the factory calibration was taken at 3.0 V.

Select **Reactive → Board temp** in the UI and the board drives the pattern
from its own die temperature (25–45 °C → full range), with no host involvement.

Other inputs available: **6 ADC pins** (D14–D19) for external sensors, USB
camera / mic via a dongle, and host-side signals (mic, system audio, CPU load).

## Persistence — unplug and replug, it keeps running

The **sketch** always lived in flash (`user_sketch` @0x100000), so the program
itself was already non-volatile. What was volatile was the *content*: uploaded
text and slider settings sat in RAM and died on power-off.

Hit **Save to board** and both are written to the MCU's dedicated
`storage_partition` (@0x1C0000, 256 KB) via Zephyr's `flash_area_*` API, then
restored automatically in `setup()` on every boot. **Forget** erases it.

Verified: 132 chars saved, board reset with the host sending nothing, and it
came back up with `n=132 saved=1` still scrolling.

Notes:
- STM32U5 flash writes are 16-byte quad-words, so the record is padded to a
  16-byte multiple; the header holds a `KFW1` magic so an unwritten partition
  is detected and ignored.
- Once saved you don't need the computer at all — power it from any USB
  charger and it starts scrolling on its own.

## Protocol (host → board, every packet checksummed)
```
0xA5 pattern speed segments scale bright gamma react flags sum   -> params
0xA6 level bass sum                                              -> reactive
0xA8 sum(=0)                                                     -> commit staged text
0xA9 sum(=0)                                                     -> clear staging
0xAA sum(=0)                                                     -> save to flash
0xAB sum(=0)                                                     -> erase saved data
ack: 'K' good, 'X' bad checksum
react bitmask: 1=brightness 2=scale 4=speed 8=segments
```
