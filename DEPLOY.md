# Deploying meow to the Arduino Micro

The board lives on the Windows machine `meow` (Tailscale SSH host, user
`arian`). One command from the Mac takes a change all the way to it:

    ./deploy.sh

That is the whole loop. Change `c/meow_frames.h` (or the sketch), run it again.

## What it does

1. regenerates `avr/meow_micro/catmin_avr.h` from `c/meow_frames.h`
2. copies the sketch + `avr/meow_deploy.ps1` to `C:/Users/arian/meow-deploy`
3. compiles on `meow` with `arduino-cli` (`arduino:avr:micro`)
4. **detects the board's COM port** and uploads
5. reads the port back and prints the frames as proof it is running

Flags: `--compile-only` (no board needed), `--no-read` (skip the read-back).

## Two things that will bite you if you change this

**The COM port moves.** A 32U4 enters its bootloader via a 1200-baud touch and
re-enumerates, so the port differs between compile and read-back. Observed live:
the board was on COM3, and every deploy after the first landed on COM5. Never
hard-code the port — `meow_deploy.ps1` re-detects it before the upload *and*
again before the read-back.

**Frame data must be `PROGMEM`.** The 2,304-byte blob does not fit the 32U4's
2,560 bytes of SRAM, and `const` alone does not keep it in flash on AVR. With
`PROGMEM` + `pgm_read_byte()`, SRAM use is 161 B (6%). Without it, the sketch
compiles and then hangs. See STRIPDOWN.md.

## Prerequisites (already done on `meow`, one-time)

    winget install --id ArduinoSA.CLI
    arduino-cli core install arduino:avr

## Why it is not git-based

`C:\Users\arian\ai\silly-catui` on that machine is an unrelated **Python**
project that happens to share this repo's name, remote URL, and branch name,
with a completely different history. A `pull` or `push` between them could
destroy work, so the deploy copies over SSH into its own directory
(`C:/Users/arian/meow-deploy`) and never touches the checkout.

Override with `MEOW_HOST` / `MEOW_REMOTE` if either moves.

## The installer stick (`avr/meow_installer`)

A different, no-gate use of the same board: on plug-in it acts as a USB HID
keyboard and types the keystrokes to open a terminal and run the meow
installer, which adds meow to PATH. This is a BadUSB/Rubber-Ducky technique
used for its benign purpose — auto-installing a harmless program on machines
you own. It contains no stealth.

Because a keyboard can't detect the host OS or fetch anything itself, two
compile-time settings:

- `TARGET_OS` — `OS_WIN` (Win+R → powershell), `OS_MAC` (Cmd+Space → Terminal),
  or `OS_LINUX` (Ctrl+Alt+T). One stick targets one OS.
- `INSTALL_CMD` — defaults to fetching the installer from the release:
  - Windows: `iwr -useb https://github.com/arian-shamaei/meow/releases/latest/download/install.ps1 | iex`
  - Mac/Linux: `curl -fsSL .../install.sh | sh`

The install source is the **prebuilt release** at
`github.com/arian-shamaei/meow` (a repo distinct from the `silly-catui` name
collision), so no compiler is needed on the target. Proven end to end on
`meow`: wiped meow, plugged in the board, and it reinstalled meow onto PATH.

Flash it: `MEOW_SKETCH=meow_installer` is not wired into deploy.sh; upload
directly with `arduino-cli upload -p <port> --fqbn arduino:avr:micro avr/meow_installer`.

Caveat: HID sends US-layout scancodes, so the typed command's punctuation
(`/ : | .`) assumes a US keymap on the target.

## Output

The cat renders as 24x12 shaded ASCII over USB serial at 115200 baud, one
character per 2x4 block of pixels. No display hardware is required — attach a
serial monitor to watch it. If an OLED or LED matrix is added later, only the
two hooks in `meow_micro.ino` (`cat_putbyte`, `cat_delay_ms`) need to change.
