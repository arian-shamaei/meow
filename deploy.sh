#!/bin/sh
# deploy.sh -- one command: a change here, running on the Arduino Micro that is
# plugged into the Windows machine `meow`.
#
#     ./deploy.sh                 regenerate, copy, compile, upload, prove it runs
#     ./deploy.sh --compile-only  stop after compiling (no board needed)
#     ./deploy.sh --no-read       upload but skip the serial read-back
#
# What it does, in order:
#   1. regenerate avr/meow_micro/catmin_avr.h from c/meow_frames.h
#   2. copy the sketch + the PowerShell helper to `meow`
#   3. on `meow`: arduino-cli compile
#   4. on `meow`: detect the board's COM port (it moves -- see the .ps1) + upload
#   5. on `meow`: read the port back and print the frames as proof
#
# Deliberately NOT git-based, and deliberately NOT written into
# C:\Users\arian\ai\silly-catui: that directory holds an unrelated Python
# project that shares this repo's name, remote, and branch name. Copying over
# SSH into its own directory keeps the two from ever touching.
#
# Overridable:  MEOW_HOST (ssh host, default "meow")
#               MEOW_REMOTE (dir on the Windows box)

set -eu

HOST="${MEOW_HOST:-meow}"
REMOTE="${MEOW_REMOTE:-C:/Users/arian/meow-deploy}"
DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd)

PS_ARGS=""
for a in "$@"; do
    case "$a" in
        --compile-only) PS_ARGS="$PS_ARGS -NoUpload" ;;
        --no-read)      PS_ARGS="$PS_ARGS -NoRead" ;;
        --help|-h)      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "deploy.sh: unknown option: $a" >&2; exit 64 ;;
    esac
done

say() { echo "deploy: $*"; }

# --- 1. regenerate the frame header from the master data ------------------
say "1/4 regenerating frame header from c/meow_frames.h"
python3 "$DIR/avr/gen_catmin_avr.py"

# --- 2. copy to the Windows machine ---------------------------------------
say "2/4 copying sketch to $HOST:$REMOTE"
ssh -o ConnectTimeout=20 "$HOST" \
    "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '$REMOTE' | Out-Null\""
scp -q -r "$DIR/avr/meow_micro" "$HOST:$REMOTE/"
scp -q "$DIR/avr/meow_deploy.ps1" "$HOST:$REMOTE/"

# --- 3/4/5. compile, upload, read back (all on the Windows side) ----------
say "3/4 compile + upload on $HOST"
# shellcheck disable=SC2086  # PS_ARGS is a deliberate list of flags
ssh -o ConnectTimeout=30 "$HOST" \
    "powershell -NoProfile -ExecutionPolicy Bypass -File $REMOTE/meow_deploy.ps1$PS_ARGS"

say "4/4 done"
