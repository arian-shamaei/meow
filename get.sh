#!/bin/sh
# get.sh -- download-and-install meow from the latest release.
#
# curl|sh-safe: no checkout, no compiler, no git. Detects the OS and CPU,
# downloads the matching prebuilt binary, and adds meow to PATH. This is the
# script the USB stick runs on macOS/Linux (the release serves it as
# install.sh); the repo's build-from-source install.sh is for developers.
#
#   curl -fsSL https://github.com/arian-shamaei/meow/releases/latest/download/install.sh | sh
#
# The Linux binaries are static, so one binary per arch runs on every distro
# (alpine/musl, debian, ubuntu, fedora, arch -- all the same file).

set -eu

REPO="${MEOW_REPO:-arian-shamaei/meow}"
OS="${MEOW_UNAME:-$(uname -s 2>/dev/null || echo unknown)}"
ARCH="${MEOW_ARCH:-$(uname -m 2>/dev/null || echo unknown)}"

asset=""
case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64|aarch64) asset="meow-macos-arm64" ;;
            x86_64)        asset="meow-macos-x86_64" ;;
        esac ;;
    Linux)
        case "$ARCH" in
            x86_64|amd64)  asset="meow-linux-amd64" ;;
            aarch64|arm64) asset="meow-linux-arm64" ;;
        esac ;;
esac
[ -n "$asset" ] || { echo "meow: no prebuilt binary for $OS/$ARCH" >&2; exit 1; }
url="https://github.com/$REPO/releases/latest/download/$asset"

# best writable bin dir, no root needed
if [ -w /usr/local/bin ] 2>/dev/null; then bindir="/usr/local/bin"; else bindir="$HOME/.local/bin"; fi
mkdir -p "$bindir"

tmp="$bindir/.meow.dl.$$"
echo "meow: downloading $asset"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp" "$url"
else
    echo "meow: need curl or wget" >&2; exit 1
fi
[ -s "$tmp" ] || { echo "meow: download failed ($url)" >&2; rm -f "$tmp"; exit 1; }
chmod 755 "$tmp"
mv -f "$tmp" "$bindir/meow"
echo "meow: installed $bindir/meow"

# --- add to PATH permanently (idempotent) ---
case ":$PATH:" in
    *":$bindir:"*) echo "meow: PATH already includes $bindir"; echo "meow: run:  meow"; exit 0 ;;
esac
line="export PATH=\"$bindir:\$PATH\"  # meow"
ensure() {
    f=$1
    [ -e "$f" ] || : > "$f" || return 0
    grep -Fq '# meow' "$f" 2>/dev/null && return 0
    printf '%s\n' "$line" >> "$f" && echo "meow: updated $f"
}
ensure "$HOME/.profile"
case "$(basename "${SHELL:-sh}")" in
    zsh)  ensure "$HOME/.zprofile"; ensure "$HOME/.zshrc" ;;
    bash) ensure "$HOME/.bashrc";   ensure "$HOME/.bash_profile" ;;
esac
echo "meow: added $bindir to PATH -- open a new shell, then run:  meow"
