# Bundle Size Reduction — Option A Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce the macOS DMG from ~734 MB to ~450 MB by cleaning Streamlit's leftover dependencies out of bundled-python and pruning unused stdlib modules — zero quality or behaviour changes.

**Architecture:** `scripts/bundle-python-mac.sh` already does the right thing conceptually but has two gaps: it never clears existing site-packages before reinstalling (so Streamlit's deps linger), and it never prunes unused stdlib modules that ship with python-build-standalone (tkinter, idlelib, tcl/tk etc.). We fix both gaps in the script, then run it in `--packages-only` mode so the existing Python interpreter is reused (no re-download) and only site-packages is rebuilt.

**Tech Stack:** Bash, python-build-standalone (Python 3.13), pip, electron-builder

---

## Background / What's in the bundle

Current `bundled-python` was populated from a full `venv` rather than a clean run of `bundle-python-mac.sh`. These packages are present but should never be there:

| Package | Size | Why it's wrong |
|---|---|---|
| `pyarrow` | 114 MB | Streamlit dep only |
| `streamlit` | 24 MB | Legacy Streamlit app — not used in desktop |
| `pandas` | 26 MB | Streamlit dep only |
| `sympy` | 18 MB | torch/Streamlit transitive dep |
| `pydeck` | 14 MB | Streamlit dep only |
| `altair` | 5.7 MB | Streamlit dep only |

Additionally, python-build-standalone ships these stdlib modules we never use:

| Module/Lib | Size | Why it's safe to remove |
|---|---|---|
| `tkinter/` | 316 KB | GUI toolkit — FastAPI app has no Tk UI |
| `idlelib/` | 1.3 MB | Python IDE — not needed at runtime |
| `ensurepip/` | 1.7 MB | pip bootstrapper — pip already installed |
| `turtle`/`turtledemo` | ~200 KB | Graphics — unused |
| `pydoc_data/` | 544 KB | pydoc HTML templates — unused |
| `tcl9.0/`, `tk9.0/`, `itcl4.3.5/`, `thread3.0.4/` | ~7 MB | tcl/tk — only needed by tkinter |
| `libtcl9.0.dylib`, `libtcl9tk9.0.dylib` | ~3.7 MB | tcl/tk shared libs |

**Expected saving: ~215–230 MB uncompressed, ~280–290 MB off the final DMG.**

---

### Task 1: Add `--packages-only` flag and site-packages cleanup to `bundle-python-mac.sh`

**Files:**
- Modify: `scripts/bundle-python-mac.sh`

The current script skips the Python download if `bundled-python/` already exists — but still runs `pip install` on top of whatever is already in site-packages. We need a `--packages-only` mode that clears site-packages before reinstalling, for when the Python interpreter is fine but the packages need a clean rebuild.

**Step 1: Read the current script**

```bash
cat scripts/bundle-python-mac.sh
```

**Step 2: Add the `--packages-only` flag and site-packages wipe**

Replace the section from `echo "==> Bundling portable Python..."` down to `PYTHON_BIN=...` with the following. The key change is the new `PACKAGES_ONLY` flag and the site-packages wipe block:

```bash
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
```

**Step 3: Verify the diff looks right**

```bash
git diff scripts/bundle-python-mac.sh
```

Expected: `PACKAGES_ONLY` flag parsing added, site-packages wipe block added before `pip install`.

**Step 4: Commit**

```bash
git add scripts/bundle-python-mac.sh
git commit -m "build: add --packages-only flag and site-packages wipe to bundle script"
```

---

### Task 2: Add stdlib pruning to `bundle-python-mac.sh`

**Files:**
- Modify: `scripts/bundle-python-mac.sh`

python-build-standalone ships tkinter, idlelib, tcl/tk and other modules the desktop app never uses. These should be stripped after every bundle. Add a pruning step after the existing `__pycache__` cleanup.

**Step 1: Add the stdlib pruning block**

Find this section in the script:

```bash
echo "==> Cleaning up site-packages (removing __pycache__, .dist-info, tests)..."
find "$PYTHON_DEST/lib" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
```

Add the following **immediately after** it:

```bash
echo "==> Pruning unused stdlib modules..."
STDLIB="$PYTHON_DEST/lib/python3.13"

# GUI / IDE tools — not needed in a FastAPI headless process
for module in tkinter idlelib turtle turtledemo pydoc_data ensurepip; do
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
```

**Step 2: Verify the diff**

```bash
git diff scripts/bundle-python-mac.sh
```

Expected: pruning loop for stdlib modules and tcl/tk libs added after existing cleanup block.

**Step 3: Commit**

```bash
git add scripts/bundle-python-mac.sh
git commit -m "build: prune unused stdlib modules and tcl/tk libs from bundle"
```

---

### Task 3: Run the updated script in `--packages-only` mode

This rebuilds site-packages from `requirements-desktop.txt` (clean — no Streamlit deps) and runs the new stdlib pruning. The Python interpreter is reused; no re-download required.

**Step 1: Check current bundled-python size (baseline)**

```bash
du -sh bundled-python
du -sh bundled-python/lib/python3.13/site-packages
```

Note the numbers. Expected baseline: ~1.3 GB total, ~1.3 GB site-packages.

**Step 2: Run the script**

This will take 5–15 minutes (pip downloads GLiNER's torch + spaCy model).

```bash
bash scripts/bundle-python-mac.sh --packages-only
```

Expected output:
```
==> --packages-only: skipping Python download, rebuilding site-packages only.
==> Clearing site-packages...
==> Installing pip dependencies into bundled Python...
==> Downloading spaCy model (en_core_web_lg)...
==> Cleaning up site-packages (removing __pycache__, .dist-info, tests)...
==> Pruning unused stdlib modules...
    Removed stdlib: tkinter
    Removed stdlib: idlelib
    Removed stdlib: turtle
    Removed stdlib: turtledemo
    Removed stdlib: pydoc_data
    Removed stdlib: ensurepip
    Removed lib: tcl9.0
    Removed lib: tk9.0
    ...
✓ Bundle complete.
```

**Step 3: Verify the size reduction**

```bash
du -sh bundled-python
du -sh bundled-python/lib/python3.13/site-packages
```

Expected: total ~1.05–1.1 GB (down from ~1.3 GB). Specifically, confirm these are gone:

```bash
ls bundled-python/lib/python3.13/site-packages/streamlit 2>/dev/null && echo "FAIL: streamlit still present" || echo "OK: streamlit removed"
ls bundled-python/lib/python3.13/site-packages/pyarrow 2>/dev/null && echo "FAIL: pyarrow still present" || echo "OK: pyarrow removed"
ls bundled-python/lib/python3.13/site-packages/pandas 2>/dev/null && echo "FAIL: pandas still present" || echo "OK: pandas removed"
ls bundled-python/lib/python3.13/tkinter 2>/dev/null && echo "FAIL: tkinter still present" || echo "OK: tkinter removed"
ls bundled-python/lib/tcl9.0 2>/dev/null && echo "FAIL: tcl9.0 still present" || echo "OK: tcl9.0 removed"
```

All five should print `OK`.

**Step 4: Confirm required packages are present**

```bash
bundled-python/bin/python3 -c "import pymupdf; print('pymupdf OK')"
bundled-python/bin/python3 -c "import fastapi; print('fastapi OK')"
bundled-python/bin/python3 -c "import spacy; nlp = spacy.load('en_core_web_lg'); print('spacy OK')"
bundled-python/bin/python3 -c "import gliner; print('gliner OK')"
bundled-python/bin/python3 -c "import PIL; print('PIL OK')"
```

All five should print their `OK` line without errors.

---

### Task 4: Build the DMG and verify final size

**Step 1: Build the DMG**

```bash
cd desktop && npm run dist:mac
```

This will take 2–5 minutes.

**Step 2: Check the DMG size**

```bash
ls -lh desktop/release/*.dmg
```

Expected: ~450–480 MB (down from ~734 MB).

**Step 3: Smoke test — mount the DMG and launch the app**

```bash
open desktop/release/*.dmg
```

Drag to Applications, launch. Verify:
- App opens (Electron window appears)
- Backend starts (no "backend failed to start" error)
- Folder selection screen loads
- Dependencies check screen shows spaCy and GLiNER as available

**Step 4: Commit the final state**

The `bundled-python/` directory is not tracked in git (it's a build artefact). Commit only the script changes (already done in Tasks 1–2). No additional commit needed here.

**Step 5: Push to test**

```bash
git push origin test
```

---

## Rollback

If anything breaks, the old `bundled-python` can be restored by re-running the original script without `--packages-only`:

```bash
rm -rf bundled-python
bash scripts/bundle-python-mac.sh
```

This re-downloads Python and reinstalls cleanly from scratch (~20 min).

---

## Expected outcome

| Metric | Before | After |
|---|---|---|
| `bundled-python` size | ~1.3 GB | ~1.05–1.1 GB |
| DMG size | ~734 MB | ~450–480 MB |
| Streamlit in bundle | Yes | No |
| pyarrow in bundle | Yes | No |
| tkinter/tcl/tk in bundle | Yes | No |
| App behaviour | — | Unchanged |
| Detection quality | — | Unchanged |
