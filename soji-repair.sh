#!/bin/sh
# Repairs what the Nov 8 Sōji cleanups broke (the Trash was emptied, so
# we reinstall instead of restoring).
#
#   sh ~/Documents/Github/soji/soji-repair.sh
#
# Every folder this script removes is already broken (its contents were
# trashed); removing it lets the owning app download a clean copy.
set -u

H="$HOME"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

remove() {  # remove a broken folder if it exists
  if [ -e "$1" ]; then
    rm -rf "$1" && ok "Removed $1" || warn "Could not remove $1"
  else
    ok "Already gone: $1"
  fi
}

cat <<EOF
Sōji repair. This will:
  1. Quit Codex, VS Code, Zed, Discord and Raycast
  2. Remove the broken Codex runtime (Codex downloads a new one)
  3. Reinstall 5 VS Code extensions
  4. Remove Zed's broken html/emmet extension work folders
  5. Remove Discord's broken spellcheck module
  6. Remove the broken expo-device-hub tool (t3)
  7. Tell you which 2 Raycast extensions to reinstall
EOF
printf '\nContinue? [y/N] '
read -r answer
case "$answer" in y|Y|yes|YES) ;; *) echo "Nothing done."; exit 0 ;; esac

step "1. Quitting apps"
for id in com.openai.codex com.microsoft.VSCode dev.zed.Zed com.hnc.Discord com.raycast.macos; do
  if [ "$(osascript -e "application id \"$id\" is running" 2>/dev/null)" = true ]; then
    osascript -e "tell application id \"$id\" to quit" >/dev/null 2>&1 && ok "Quit $id"
  fi
done
sleep 3

step "2. Codex runtime"
remove "$H/.cache/codex-runtimes/codex-runtime-install-L2Mqle"

step "3. VS Code extensions"
CODE=$(command -v code 2>/dev/null || true)
[ -z "$CODE" ] && [ -x "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" ] \
  && CODE="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
if [ -z "$CODE" ]; then
  warn "VS Code's 'code' command not found. In VS Code: Cmd+Shift+P > 'Shell Command: Install code command in PATH', then run this script again."
else
  for pair in \
    "ritwickdey.LiveServer:ritwickdey.liveserver-" \
    "oderwat.indent-rainbow:oderwat.indent-rainbow-" \
    "esbenp.prettier-vscode:esbenp.prettier-vscode-" \
    "pranaygp.vscode-css-peek:pranaygp.vscode-css-peek-" \
    "ms-python.python:ms-python.python-"
  do
    id=${pair%%:*}; prefix=${pair#*:}
    "$CODE" --uninstall-extension "$id" >/dev/null 2>&1
    # If the uninstall left a broken folder behind, remove it.
    for dir in "$H/.vscode/extensions/$prefix"*; do
      [ -d "$dir" ] && rm -rf "$dir"
    done
    if "$CODE" --install-extension "$id" --force >/dev/null 2>&1; then
      ok "Reinstalled $id"
    else
      warn "Could not reinstall $id (install it from VS Code's Extensions panel)"
    fi
  done
fi

step "4. Zed extensions"
remove "$H/Library/Application Support/Zed/extensions/work/html"
remove "$H/Library/Application Support/Zed/extensions/work/emmet"
warn "Zed rebuilds these on next launch. If HTML/Emmet still fail, reinstall them in Zed > Extensions."

step "5. Discord"
remove "$H/Library/Application Support/discord/app-0.0.411/modules/discord_spellcheck-1"

step "6. t3 expo-device-hub"
remove "$H/.t3/tools/expo-device-hub/0.15.3"

step "7. Raycast (needs you)"
for uuid in 112ad714-bf10-4ccc-a70f-4232bb2241a5 7122ec68-495a-428d-9dc2-7a120818c8f6; do
  manifest="$H/.config/raycast/extensions/$uuid/package.json"
  if [ -f "$manifest" ]; then
    title=$(sed -n 's/^  "title": *"\(.*\)".*/\1/p' "$manifest" | head -n 1)
    name=$(sed -n 's/^  "name": *"\(.*\)".*/\1/p' "$manifest" | head -n 1)
    warn "Reinstall from the Raycast Store: ${title:-$name} ($uuid)"
  else
    warn "Extension $uuid: no manifest found (it may already be gone)"
  fi
done
echo "   In Raycast: open the extension in the Store, uninstall, then install."

step "Done"
echo "Open Codex, VS Code, Zed and Discord again; they'll download what's missing."
echo "You can delete soji-restore.sh and this script afterwards."
