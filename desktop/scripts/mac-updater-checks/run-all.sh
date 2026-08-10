#!/bin/bash
# Runs every macOS updater check. See README.md.
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(uname)" != "Darwin" ]; then
  echo "macOS only — these use hdiutil, ditto and PlistBuddy. Skipping."
  exit 0
fi

status=0
for check in "$HERE/swap-script.sh" "$HERE/persistence.mjs" "$HERE/installer.mjs"; do
  echo
  echo "──────────────────────────────────────────────────────────"
  echo "  $(basename "$check")"
  echo "──────────────────────────────────────────────────────────"
  case "$check" in
    *.sh)  bash "$check" || status=1 ;;
    *.mjs) node "$check" || status=1 ;;
  esac
done

echo
if [ "$status" -eq 0 ]; then echo "All macOS updater checks passed."
else echo "SOME CHECKS FAILED."; fi
exit "$status"
