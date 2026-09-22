#!/usr/bin/env bash
# bundle-python-mac.sh
#
# Downloads a portable Python (python-build-standalone) and installs all
# project dependencies into it. Run from the repo root before `npm run dist:mac`.
#
# Output:
#   bundled-python/   — portable Python installation
#   bundled-tesseract/ — Tesseract binary + tessdata (eng) + lib/ (its dylibs,
#                        relinked to @executable_path/lib and self-checked)
#
# Requirements: curl, tar, brew (for tesseract source only if not cached)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_DEST="$REPO_ROOT/bundled-python"
TESSERACT_DEST="$REPO_ROOT/bundled-tesseract"

# ── Python version and release ────────────────────────────────────────
PYTHON_VERSION="3.13.12"
PBS_TAG="20260310"
PBS_FILENAME="cpython-${PYTHON_VERSION}+${PBS_TAG}-aarch64-apple-darwin-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_FILENAME}"

# ── Flags ─────────────────────────────────────────────────────────────
PACKAGES_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --packages-only) PACKAGES_ONLY=true ;;
  esac
done

# ── Python interpreter ─────────────────────────────────────────────────
if [ "$PACKAGES_ONLY" = true ]; then
  if [ ! -d "$PYTHON_DEST" ]; then
    echo "ERROR: --packages-only requires bundled-python to already exist."
    exit 1
  fi
  echo "==> --packages-only: skipping Python download, rebuilding site-packages only."
else
  echo "==> Bundling portable Python ${PYTHON_VERSION}..."
  if [ -d "$PYTHON_DEST" ]; then
    echo "    $PYTHON_DEST already exists — remove it to re-bundle."
    echo "    Skipping Python download."
  else
    TMPFILE="$(mktemp /tmp/pbs-XXXX.tar.gz)"
    echo "    Downloading $PBS_URL ..."
    curl -fsSL --retry 3 -o "$TMPFILE" "$PBS_URL"
    echo "    Extracting..."
    tar -xzf "$TMPFILE" -C "$REPO_ROOT"
    mv "$REPO_ROOT/python" "$PYTHON_DEST"
    rm "$TMPFILE"
    echo "    Python extracted to $PYTHON_DEST"
  fi
fi

PYTHON_BIN="$PYTHON_DEST/bin/python3"

# ── Wipe site-packages before installing (ensures no stale deps) ───────
SITE_PACKAGES="$PYTHON_DEST/lib/python3.13/site-packages"
echo "==> Clearing site-packages..."
rm -rf "$SITE_PACKAGES"
mkdir -p "$SITE_PACKAGES"

echo "==> Bootstrapping pip into clean site-packages..."
"$PYTHON_BIN" -m ensurepip --upgrade

echo "==> Installing pip dependencies into bundled Python..."
"$PYTHON_BIN" -m pip install --upgrade pip --quiet
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/requirements-desktop.txt" --quiet

echo "==> Downloading spaCy model (en_core_web_lg)..."
"$PYTHON_BIN" -m spacy download en_core_web_lg --quiet

echo "==> Cleaning up site-packages (removing __pycache__, .dist-info, tests)..."
find "$PYTHON_DEST/lib" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
# Note: .dist-info dirs are intentionally kept — packages like transformers and
# spacy use importlib.metadata at import time to check dependency versions.
find "$PYTHON_DEST/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true

echo "==> Pruning unused stdlib modules..."
STDLIB="$PYTHON_DEST/lib/python3.13"

# GUI / IDE tools — not needed in a FastAPI headless process
# Note: ensurepip is intentionally kept — it's needed to re-bootstrap pip
# if --packages-only is run after a previous prune wiped site-packages.
for module in tkinter idlelib turtle turtledemo pydoc_data; do
  if [ -e "$STDLIB/$module" ]; then
    rm -rf "$STDLIB/$module"
    echo "    Removed stdlib: $module"
  fi
done

# tcl/tk shared libraries (only needed by tkinter)
LIB="$PYTHON_DEST/lib"
for item in tcl9.0 tk9.0 itcl4.3.5 tcl9 thread3.0.4 libtcl9.0.dylib libtcl9tk9.0.dylib; do
  if [ -e "$LIB/$item" ]; then
    rm -rf "$LIB/$item"
    echo "    Removed lib: $item"
  fi
done

# ── Bundle Tesseract ──────────────────────────────────────────────────
echo "==> Bundling Tesseract..."

TESS_LIB="$TESSERACT_DEST/lib"

# Print the non-system libraries a Mach-O file links against, one per line.
# /usr/lib and /System ship with every Mac; everything else must be bundled.
_nonsystem_deps() {
  otool -L "$1" | tail -n +2 | sed -E 's/^[[:space:]]+//; s/ \(compatibility.*$//' |
    while IFS= read -r dep; do
      case "$dep" in
        /usr/lib/*|/System/*) ;;
        *) echo "$dep" ;;
      esac
    done
}

# Print the LC_RPATH entries of a Mach-O file, one per line.
_rpaths() {
  otool -l "$1" | awk '/cmd LC_RPATH/ { getline; getline; print $2 }'
}

# Resolve a load-command reference to the file on disk it refers to.
# $1 = the reference, $2 = the ORIGINAL (Homebrew) file that contains it.
_resolve_dep() {
  case "$1" in
    /opt/homebrew/*|/usr/local/*) echo "$1" ;;
    @rpath/*|@loader_path/*)
      # Homebrew uses these only for siblings in the same keg (libwebp ->
      # libsharpyuv), so the referencing file's own directory is the answer.
      echo "$(dirname "$(realpath "$2")")/${1#*/}" ;;
    *) return 1 ;;
  esac
}

# Run a command quietly, but show its output and fail if it fails.
# install_name_tool and codesign print routine notices on every success.
_quiet() {
  local out
  if ! out="$("$@" 2>&1)"; then
    echo "$out" >&2
    return 1
  fi
}

# The bundle must also have lib/ — a bundle from before the dylibs were
# copied has only the binary, which links to Homebrew and must be rebuilt.
if [ -f "$TESSERACT_DEST/tesseract" ] && [ -d "$TESS_LIB" ]; then
  echo "    $TESSERACT_DEST already exists — skipping."
else
  rm -rf "$TESSERACT_DEST"
  # Use the Homebrew-installed tesseract as the source binary
  BREW_TESS="$(brew --prefix tesseract 2>/dev/null)/bin/tesseract"
  if [ ! -f "$BREW_TESS" ]; then
    echo "ERROR: Tesseract not found via Homebrew. Install with: brew install tesseract"
    exit 1
  fi

  mkdir -p "$TESSERACT_DEST/tessdata"
  cp "$BREW_TESS" "$TESSERACT_DEST/tesseract"
  chmod +x "$TESSERACT_DEST/tesseract"

  # Copy English language data only (keeps bundle small)
  BREW_TESSDATA="$(brew --prefix tesseract)/share/tessdata"
  if [ -f "$BREW_TESSDATA/eng.traineddata" ]; then
    cp "$BREW_TESSDATA/eng.traineddata" "$TESSERACT_DEST/tessdata/"
    echo "    Copied eng.traineddata"
  else
    echo "WARNING: eng.traineddata not found at $BREW_TESSDATA"
  fi

  # Copy every non-system dylib the binary needs, recursively. Without this
  # the binary keeps pointing at the CI runner's /opt/homebrew paths and OCR
  # fails on any Mac without the same Homebrew Tesseract version.
  mkdir -p "$TESS_LIB"
  QUEUE="$(mktemp)"
  echo "$BREW_TESS" > "$QUEUE"
  while [ -s "$QUEUE" ]; do
    src="$(head -n 1 "$QUEUE")"
    sed -i '' 1d "$QUEUE"
    while IFS= read -r dep; do
      name="$(basename "$dep")"
      [ -f "$TESS_LIB/$name" ] && continue
      if ! dep_file="$(_resolve_dep "$dep" "$src")" || [ ! -f "$dep_file" ]; then
        echo "ERROR: cannot resolve $dep (needed by $src)"
        exit 1
      fi
      cp -L "$dep_file" "$TESS_LIB/$name"
      chmod u+w "$TESS_LIB/$name"
      echo "    Copied $name"
      echo "$dep_file" >> "$QUEUE"
    done < <(_nonsystem_deps "$src")
  done
  rm -f "$QUEUE"

  # Point every reference at the bundled copies. install_name_tool breaks
  # the code signature, so each file is re-signed ad hoc afterwards —
  # hardened runtime refuses to load a dylib whose signature is invalid.
  chmod u+w "$TESSERACT_DEST/tesseract"
  for f in "$TESSERACT_DEST/tesseract" "$TESS_LIB"/*.dylib; do
    if [ "$f" != "$TESSERACT_DEST/tesseract" ]; then
      _quiet install_name_tool -id "@executable_path/lib/$(basename "$f")" "$f"
    fi
    while IFS= read -r dep; do
      _quiet install_name_tool -change "$dep" "@executable_path/lib/$(basename "$dep")" "$f"
    done < <(_nonsystem_deps "$f")
    while IFS= read -r rp; do
      _quiet install_name_tool -delete_rpath "$rp" "$f"
    done < <(_rpaths "$f")
    _quiet codesign -s - -f "$f"
  done

  echo "    Tesseract bundled to $TESSERACT_DEST"
fi

# ── Self-check: the Tesseract bundle must not reach outside itself ─────
# Runs even when the bundle step was skipped, so a stale bundle fails too.
echo "==> Checking Tesseract bundle is self-contained..."
TESS_BAD=0
for f in "$TESSERACT_DEST/tesseract" "$TESS_LIB"/*.dylib; do
  [ -e "$f" ] || continue
  while IFS= read -r dep; do
    case "$dep" in
      @executable_path/lib/*)
        if [ ! -f "$TESS_LIB/${dep#@executable_path/lib/}" ]; then
          echo "    FAIL: $(basename "$f") needs $dep, which is not in the bundle"
          TESS_BAD=1
        fi ;;
      *)
        echo "    FAIL: $(basename "$f") still links to $dep"
        TESS_BAD=1 ;;
    esac
  done < <(_nonsystem_deps "$f")
  if [ -n "$(_rpaths "$f")" ]; then
    echo "    FAIL: $(basename "$f") still has an rpath: $(_rpaths "$f" | tr '\n' ' ')"
    TESS_BAD=1
  fi
  if ! codesign --verify --strict "$f" 2>/dev/null; then
    echo "    FAIL: $(basename "$f") has an invalid code signature"
    TESS_BAD=1
  fi
done
if ! "$TESSERACT_DEST/tesseract" --version >/dev/null 2>&1; then
  echo "    FAIL: bundled tesseract does not run"
  TESS_BAD=1
fi
if [ "$TESS_BAD" -ne 0 ]; then
  echo "ERROR: Tesseract bundle is not self-contained. Delete $TESSERACT_DEST and re-run."
  exit 1
fi
echo "    OK: $(ls "$TESS_LIB" | wc -l | tr -d ' ') dylibs, no Homebrew references."

echo ""
echo "✓ Bundle complete."
echo "  Python: $PYTHON_DEST"
echo "  Tesseract: $TESSERACT_DEST"
echo ""
echo "Next: cd desktop && npm run dist:mac"
