# meow on the Arduino Uno Q 8x13 LED matrix

Runs the silly-cat animation (`../c/meow_frames.h`) on the Uno Q's onboard
8x13 blue LED matrix, driven by the STM32 MCU.

## How it works
- The 8x13 matrix is controlled by the STM32 via `Arduino_LED_Matrix.h`
  (NOT `/sys/class/leds`, which is only the RGB status LEDs).
- `gen_v2.py` (final pipeline) + `meowlib.py` (decode + digital-twin renderer) decode the RLE grayscale frames from `meow_frames.h`,
  downsamples each 110x110 frame to an upright portrait image (8 wide x 13 tall,
  fills all 104 LEDs), contrast-stretches + gamma 0.65, then rotates 90 deg into
  the physical 8-row x 13-col array. It emits `meowmatrix/meowmatrix.ino`.
- The sketch plays all 45 frames with their original per-frame durations, and
  prints a serial heartbeat ("meow frame N") for liveness checks.

## Orientation
Board is meant to be viewed in PORTRAIT (turned 90 deg). If the cat is
upside-down/mirrored, regenerate with `--flip`:
    python3 gen_meow_matrix.py --flip --out meowmatrix/meowmatrix.ino

## Build + flash (macOS, arduino-cli)
    brew install arduino-cli
    arduino-cli config add board_manager.additional_urls https://downloads.arduino.cc/packages/package_zephyr_index.json
    arduino-cli core update-index
    arduino-cli core install arduino:zephyr
    arduino-cli compile -b arduino:zephyr:unoq meowmatrix
    arduino-cli upload  -b arduino:zephyr:unoq -p <PORT> meowmatrix
    # FQBN + port come from: arduino-cli board list
    # ("verify failed" warnings during upload are a benign STM32U5 dual-bank quirk; exit 0 = flashed)

## Preview the frames as ASCII (no hardware)
    python3 gen_meow_matrix.py --preview
