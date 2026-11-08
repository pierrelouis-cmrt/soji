#!/bin/sh
# Sōji installer for macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/pierrelouis-cmrt/soji/main/install.sh | sh
#
# Installs the single-file build (soji.pyz, native helper included) to
# ~/.local/share/soji and a `soji` command to ~/.local/bin. Nothing is written
# outside your home folder and no admin password is needed.
#
# Options (after `sh -s --`):  --version X.Y.Z   --uninstall
# Environment: SOJI_REPO (owner/repo), SOJI_PREFIX (default ~/.local),
#              SOJI_NO_MODIFY_PATH=1 (leave shell startup files alone),
#              SOJI_DOWNLOAD_URL (folder holding soji.pyz, for mirrors and tests).
set -eu

REPO=${SOJI_REPO:-pierrelouis-cmrt/soji}
PREFIX=${SOJI_PREFIX:-$HOME/.local}
SHARE="$PREFIX/share/soji"
BIN="$PREFIX/bin"
VERSION=latest
ACTION=install

while [ $# -gt 0 ]; do
  case $1 in
    --version) VERSION=${2:?--version needs a value}; shift 2 ;;
    --uninstall) ACTION=uninstall; shift ;;
    -h|--help) sed -n '2,14p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
fail() { printf 'soji install: %s\n' "$*" >&2; exit 1; }

if [ "$ACTION" = uninstall ]; then
  rm -f "$BIN/soji"
  rm -rf "$SHARE"
  say "Removed $BIN/soji and $SHARE."
  say "Your scan index and journal stay in ~/Library/Application Support/Soji (delete that folder to remove them)."
  exit 0
fi

[ "$(uname -s)" = Darwin ] || fail "Sōji runs on macOS only."
command -v curl >/dev/null 2>&1 || fail "curl is required."

# A Python 3.9+ interpreter. /usr/bin/python3 is only a stub that opens an
# install dialog until the Command Line Tools are present, so check for those
# before trying it.
find_python() {
  for candidate in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3 \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    path=$(command -v "$candidate" 2>/dev/null) || continue
    if [ "$path" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    if "$path" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

PYTHON=$(find_python) || {
  say "Sōji needs Python 3.9 or later, and none was found."
  say "The quickest fix is Apple's Command Line Tools (they include Python 3.9):"
  say ""
  say "    xcode-select --install"
  say ""
  say "Then run this installer again. (With Homebrew, 'brew install pierrelouis-cmrt/tap/soji' handles Python for you.)"
  exit 1
}

if [ -n "${SOJI_DOWNLOAD_URL:-}" ]; then
  BASE=${SOJI_DOWNLOAD_URL%/}
elif [ "$VERSION" = latest ]; then
  BASE="https://github.com/$REPO/releases/latest/download"
else
  BASE="https://github.com/$REPO/releases/download/v${VERSION#v}"
fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/soji-install.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

say "Downloading Sōji ($VERSION) from github.com/${REPO}…"
curl -fsSL "$BASE/soji.pyz" -o "$TMP/soji.pyz" || fail "download failed ($BASE/soji.pyz)."
curl -fsSL "$BASE/soji.pyz.sha256" -o "$TMP/soji.pyz.sha256" || fail "checksum download failed."
expected=$(awk '{print $1; exit}' "$TMP/soji.pyz.sha256")
actual=$(shasum -a 256 "$TMP/soji.pyz" | awk '{print $1}')
[ -n "$expected" ] && [ "$expected" = "$actual" ] || fail "checksum mismatch; nothing was installed."

"$PYTHON" "$TMP/soji.pyz" --version >/dev/null 2>&1 || fail "the downloaded build does not start with $PYTHON."

mkdir -p "$SHARE" "$BIN"
mv -f "$TMP/soji.pyz" "$SHARE/soji.pyz"
cat > "$BIN/soji" <<EOF
#!/bin/sh
# Installed by the Sōji installer; remove with: curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sh -s -- --uninstall
PY="$PYTHON"
[ -x "\$PY" ] || PY=python3
exec "\$PY" "$SHARE/soji.pyz" "\$@"
EOF
chmod 755 "$BIN/soji"

say "Installed $("$BIN/soji" --version) to $BIN/soji (Python: $PYTHON)."

case ":$PATH:" in
  *":$BIN:"*) say "Run it with:  soji" ;;
  *)
    if [ "${SOJI_NO_MODIFY_PATH:-0}" != 1 ]; then
      case ${SHELL:-} in
        */bash) rc="$HOME/.bash_profile" ;;
        *) rc="$HOME/.zshrc" ;;
      esac
      line="export PATH=\"$BIN:\$PATH\""
      if ! grep -qsF "$line" "$rc"; then
        printf '\n# Added by the Sōji installer\n%s\n' "$line" >> "$rc"
        say "Added $BIN to PATH in $rc."
      fi
      say "Open a new Terminal window, then run:  soji"
    else
      say "$BIN is not on your PATH. Run it with:  $BIN/soji"
    fi
    ;;
esac
