#!/usr/bin/env bash
# bundle-python-mac.sh
#
# Downloads a portable Python (python-build-standalone) and installs all
# project dependencies into it. Run from the repo root before `npm run dist:mac`.
#
# Output:
#   bundled-python/   — portable Python installation
#   bundled-tesseract/ — Tesseract binary + tessdata (eng)
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

echo "==> Bundling portable Python ${PYTHON_VERSION} (universal2)..."

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

PYTHON_BIN="$PYTHON_DEST/bin/python3"

echo "==> Installing pip dependencies into bundled Python..."
"$PYTHON_BIN" -m pip install --upgrade pip --quiet
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet

echo "==> Downloading spaCy model (en_core_web_lg)..."
"$PYTHON_BIN" -m spacy download en_core_web_lg --quiet

echo "==> Pre-warming GLiNER model (urchade/gliner_multi_pii-v1)..."
"$PYTHON_BIN" -c "
from gliner import GLiNER
model = GLiNER.from_pretrained('urchade/gliner_multi_pii-v1')
print('GLiNER model cached.')
"

# ── Bundle Tesseract ──────────────────────────────────────────────────
echo "==> Bundling Tesseract..."

if [ -d "$TESSERACT_DEST" ]; then
  echo "    $TESSERACT_DEST already exists — skipping."
else
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

  echo "    Tesseract bundled to $TESSERACT_DEST"
fi

echo ""
echo "✓ Bundle complete."
echo "  Python: $PYTHON_DEST"
echo "  Tesseract: $TESSERACT_DEST"
echo ""
echo "Next: cd desktop && npm run dist:mac"
