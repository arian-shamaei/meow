#!/bin/sh
# install.sh -- resilient installer for silly-catui.
#
# Gate-probes the machine and installs the right cat, or fails loudly with
# instructions for the branches a locally-run script cannot handle.
#
# Population, split by the gate that actually matters to an installer
# (shell + compiler), not by memory or output channel:
#
#   (a) shell + C compiler   -> build from source here, install.   [DONE]
#   (b) shell, no compiler   -> need a prebuilt binary per arch.    [instruct]
#   (c) no shell (bare MCU)  -> cannot run here; cross-compile+flash from a host.
#
# Usage:
#   ./install.sh              build+install the full cat (auto-detects look)
#   ./install.sh --min        build+install the 2.3 KB stripped cat
#   ./install.sh --dry-run    print the decision + commands, change nothing
#   ./install.sh --help
#
# Testing closed gates (the whole point of a gate-prober):
#   MEOW_UNAME=Redox ./install.sh --dry-run      # unknown OS   -> branch (c)
#   MEOW_CC=/nonexistent ./install.sh --dry-run  # no compiler  -> branch (b)
#   MEOW_UNAME / MEOW_CC override the probes so closed states are reachable.

set -eu

VARIANT=full
DRYRUN=0
SETPATH=1

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
}

for a in "$@"; do
    case "$a" in
        --min)     VARIANT=min ;;
        --dry-run) DRYRUN=1 ;;
        --no-path) SETPATH=0 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "install.sh: unknown option: $a" >&2; exit 64 ;;
    esac
done

log()  { echo "install.sh: $*"; }
die()  { echo "install.sh: $*" >&2; exit 1; }
run()  { if [ "$DRYRUN" -eq 1 ]; then echo "  + $*"; else eval "$*"; fi; }

# Idempotent: append $2 to file $1 only if our marker isn't already there.
ensure_line() {
    _f=$1; _l=$2
    [ -e "$_f" ] || : > "$_f" || return 1
    grep -Fq 'silly-catui: adds meow to PATH' "$_f" 2>/dev/null && return 0
    printf '%s\n' "$_l" >> "$_f" && log "updated $_f"
}

# Make $bindir a permanent part of PATH for all shells. Prefers the system-wide
# mechanism (all users) when writable, else edits the user's shell startup files.
persist_path() {
    _bindir=$1
    case ":$PATH:" in
        *":$_bindir:"*) log "PATH already includes $_bindir (nothing to persist)"; return 0 ;;
    esac
    _marker='silly-catui: adds meow to PATH'
    _exp="export PATH=\"$_bindir:\$PATH\"  # $_marker"

    if [ "$DRYRUN" -eq 1 ]; then
        log "would persist PATH so future shells find 'meow' (target: $_bindir)"
        return 0
    fi

    # System-wide first (all users, every shell), if we can write there.
    if [ "$UNAME_S" = Darwin ] && { [ -w /etc/paths.d ] || [ -w /etc ]; } 2>/dev/null; then
        mkdir -p /etc/paths.d 2>/dev/null || true
        if printf '%s\n' "$_bindir" > /etc/paths.d/meow 2>/dev/null; then
            log "persisted PATH via /etc/paths.d/meow (all users, all shells)"; return 0
        fi
    fi
    if [ -w /etc/profile.d ] 2>/dev/null; then
        if printf '%s\n' "$_exp" > /etc/profile.d/meow.sh 2>/dev/null; then
            log "persisted PATH via /etc/profile.d/meow.sh (all users, login shells)"; return 0
        fi
    fi

    # Per-user fallback. ~/.profile is the POSIX baseline, but the default
    # login shell may ignore it (zsh does NOT read ~/.profile — the macOS trap).
    # So ALSO create the startup file the user's actual $SHELL reads.
    ensure_line "$HOME/.profile" "$_exp"
    case "$(basename "${SHELL:-sh}")" in
        zsh)  ensure_line "$HOME/.zprofile" "$_exp"     # login shells (Terminal)
              ensure_line "$HOME/.zshrc"    "$_exp" ;;  # interactive shells
        bash) ensure_line "$HOME/.bash_profile" "$_exp" # macOS login bash
              ensure_line "$HOME/.bashrc"      "$_exp" ;;  # Linux interactive bash
        ksh)  ensure_line "$HOME/.kshrc" "$_exp" ;;
    esac
    # Also top up any OTHER interactive rc files that already exist.
    for _rc in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.kshrc"; do
        [ -e "$_rc" ] && ensure_line "$_rc" "$_exp"
    done
    if command -v fish >/dev/null 2>&1 || [ -e "$HOME/.config/fish/config.fish" ]; then
        mkdir -p "$HOME/.config/fish" 2>/dev/null || true
        ensure_line "$HOME/.config/fish/config.fish" "fish_add_path $_bindir  # $_marker"
    fi
    log "persisted PATH in your shell startup files (open a new shell to pick it up)"
}

# --- locate the repo (this script's directory) ---
DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd)
[ -f "$DIR/c/meow.c" ] || die "must run from the silly-catui checkout (c/meow.c not found)"

# --- overridable probes ---
UNAME_S="${MEOW_UNAME:-$(uname -s 2>/dev/null || echo unknown)}"
UNAME_M="$(uname -m 2>/dev/null || echo unknown)"

# --- gate 1: is this an OS a locally-run script can install on? ---
WIN=0
case "$UNAME_S" in
    Darwin|Linux|*BSD|DragonFly|SunOS|GNU|Haiku) HOSTED=1 ;;
    MINGW*|MSYS*|CYGWIN*)                        HOSTED=1; WIN=1 ;;
    *)                                           HOSTED=0 ;;
esac

log "target: $UNAME_S ($UNAME_M)"

if [ "$HOSTED" -eq 0 ]; then
    cat >&2 <<EOF
install.sh: '$UNAME_S' is not a shell-hosted OS this script can install on.

This is branch (c): a bare microcontroller has no shell to run me in. Install
it from a HOST machine instead:
  1. Build the stripped cat freestanding:  min/meow_min.c + min/catmin.h
     (swap the cat_putbyte/cat_delay_ms hooks in meow_min.c for your UART or
      framebuffer; the core render loop needs no libc).
  2. Cross-compile with your board's toolchain and flash it
     (e.g. esptool.py for ESP32, avrdude for AVR, openocd for ARM Cortex-M).
See STRIPDOWN.md for the ~3 KB code+data floor this targets.
EOF
    exit 2
fi

# --- gate 2: is there a C compiler? ---
CC=""
if [ -n "${MEOW_CC:-}" ]; then
    command -v "$MEOW_CC" >/dev/null 2>&1 && CC="$MEOW_CC"
else
    for c in cc clang gcc tcc; do
        if command -v "$c" >/dev/null 2>&1; then CC="$c"; break; fi
    done
fi

if [ -z "$CC" ]; then
    hint="install a C compiler and re-run"
    case "$UNAME_S" in
        Darwin)      hint="run: xcode-select --install" ;;
        Linux)       hint="e.g. apt install gcc  |  apk add build-base  |  dnf install gcc" ;;
        MINGW*|MSYS*|CYGWIN*) hint="pacman -S gcc  (or install MSYS2/WSL)" ;;
    esac
    cat >&2 <<EOF
install.sh: no C compiler found (looked for cc, clang, gcc, tcc).

This is branch (b): shell present, no compiler. Two ways forward:
  - Install a compiler: $hint
  - Or build 'meow' on another machine of the same arch ($UNAME_M) and copy
    the binary here. Prebuilt releases are not published yet; once they are,
    this branch will fetch one automatically.
EOF
    exit 3
fi
log "compiler: $CC"

# --- gate 2 open: build + install (branch a) ---
if [ "$WIN" -eq 1 ]; then
    log "note: on Windows this needs Git Bash / MSYS2 / WSL; native cmd/PowerShell is not supported (yet)."
fi

# Best writable install prefix, same rule the Makefile uses: /usr/local when
# writable, else ~/.local. Computed once so the install target and the PATH
# persistence below always agree.
if [ -w /usr/local/bin ] 2>/dev/null; then PREFIX=/usr/local; else PREFIX="$HOME/.local"; fi
BINDIR="$PREFIX/bin"

if [ "$VARIANT" = min ]; then
    log "variant: stripped meow_min (2.3 KB data, 1-bit)"
    log "building min/meow_min -> $BINDIR/meow"
    run "$CC -O2 -std=c11 -o '$DIR/min/meow_min' '$DIR/min/meow_min.c'"
    run "mkdir -p '$BINDIR'"
    run "cp '$DIR/min/meow_min' '$BINDIR/meow'"
    run "chmod 755 '$BINDIR/meow'"
    INSTALLED="$BINDIR/meow"
else
    log "variant: full meow (auto-detects braille / ascii / scroll at runtime)"
    if command -v make >/dev/null 2>&1; then
        # Delete any prebuilt/committed binary first: a fresh `git clone` gives
        # meow and its sources near-equal mtimes, so make may judge the shipped
        # (possibly wrong-arch) binary "up to date" and install it without ever
        # rebuilding. Removing it forces a real compile for THIS machine.
        run "rm -f '$DIR/meow'"
        # Delegate the build+install to the Makefile (it owns the platform
        # CFLAGS). Pass PREFIX so the install dir matches BINDIR deterministically.
        run "make -C '$DIR' CC='$CC' PREFIX='$PREFIX' install"
        INSTALLED="$BINDIR/meow"
    else
        # No make (minimal device): compile directly with the one platform flag
        # the Makefile would have added.
        log "no 'make' found; compiling directly"
        EXTRA=""
        [ "$UNAME_S" = Linux ] && EXTRA="-D_DEFAULT_SOURCE"
        run "$CC -O2 -std=c11 $EXTRA -o '$DIR/meow' '$DIR/c/meow.c'"
        run "mkdir -p '$BINDIR'"
        run "cp '$DIR/meow' '$BINDIR/meow'"
        run "chmod 755 '$BINDIR/meow'"
        INSTALLED="$BINDIR/meow"
    fi
fi

# Make 'meow' permanently reachable from every shell (unless --no-path).
if [ "$SETPATH" -eq 1 ]; then
    persist_path "$BINDIR"
fi

if [ "$DRYRUN" -eq 1 ]; then
    log "dry run: nothing was changed."
    exit 0
fi

log "done. installed: $INSTALLED"
if command -v meow >/dev/null 2>&1; then
    log "run:  meow        (Ctrl-C to quit)"
else
    log "run:  $INSTALLED   (or open a new shell so PATH picks up 'meow')"
fi
