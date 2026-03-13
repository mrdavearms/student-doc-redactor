# Mac DMG Packaging & GitHub Release (v0.1.0) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a ~300-350MB Mac .dmg installer and publish it as a GitHub pre-release.

**Architecture:** Slim the Python bundle by removing Streamlit and GLiNER dependencies (desktop uses FastAPI). Fix path mismatches between electron-builder's `extraResources`, Electron's `main.cjs`, and `binary_resolver.py`. Build locally, smoke test, then publish to GitHub Releases.

**Tech Stack:** electron-builder, python-build-standalone (3.13.12), pip, iconutil, GitHub Releases

---

### Task 1: Create `requirements-desktop.txt`

**Files:**
- Create: `requirements-desktop.txt`

**Step 1: Create the slimmed requirements file**

```
pymupdf>=1.23.0
pytesseract>=0.3.10
Pillow>=10.2.0
python-docx>=1.1.0
presidio-analyzer>=2.2.0
spacy>=3.7.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
```

This excludes `streamlit` (28MB), `gliner` (5MB + 630MB transitive deps: torch, transformers, sympy, onnxruntime), `pyarrow` (120MB), `pandas` (70MB), and their exclusive dependencies.

Keeps: pymupdf (core redaction), pytesseract (OCR), Pillow (image handling), python-docx (Word files), presidio-analyzer + spacy (NER detection), fastapi + uvicorn (desktop API server).

**Step 2: Verify no missing imports**

Run (in venv, not bundled):
```bash
grep -rh "^import\|^from" src/core/ backend/ | sort -u
```
Cross-check that every imported package is either in `requirements-desktop.txt` or is a stdlib/transitive dependency. Key check: `phonenumbers` is a transitive dep of `presidio-analyzer` — no need to list explicitly.

**Step 3: Commit**

```bash
git add requirements-desktop.txt
git commit -m "feat: add requirements-desktop.txt for slimmed Electron bundle"
```

---

### Task 2: Update `bundle-python-mac.sh`

**Files:**
- Modify: `scripts/bundle-python-mac.sh:44-55` (pip install + GLiNER sections)

**Step 1: Change pip install to use desktop requirements**

Replace line 45:
```bash
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet
```
With:
```bash
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/requirements-desktop.txt" --quiet
```

**Step 2: Remove GLiNER pre-warming block**

Delete lines 50-55 (the entire `echo "==> Pre-warming GLiNER model..."` block):
```bash
echo "==> Pre-warming GLiNER model (urchade/gliner_multi_pii-v1)..."
"$PYTHON_BIN" -c "
from gliner import GLiNER
model = GLiNER.from_pretrained('urchade/gliner_multi_pii-v1')
print('GLiNER model cached.')
"
```

**Step 3: Add site-packages cleanup step**

After the spaCy download (line 48), add:
```bash
echo "==> Cleaning up site-packages (removing __pycache__, .dist-info, tests)..."
find "$PYTHON_DEST/lib" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DEST/lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
```

**Step 4: Run the script and verify size**

```bash
rm -rf bundled-python  # Force re-bundle
bash scripts/bundle-python-mac.sh
du -sh bundled-python/
```

Expected: ~800-900MB (uncompressed — DMG compression brings this down to ~300-350MB).

**Step 5: Commit**

```bash
git add scripts/bundle-python-mac.sh
git commit -m "feat: slim bundle script — remove Streamlit/GLiNER deps, add cleanup"
```

---

### Task 3: Fix `extraResources` in `package.json`

**Files:**
- Modify: `desktop/package.json:62-73` (the `extraResources` array)

**Step 1: Add bundled-python and bundled-tesseract to extraResources**

The current `extraResources` only copies `backend/` and `src/`. electron-builder needs to also include the portable Python and Tesseract. Replace the `extraResources` array (lines 62-73) with:

```json
    "extraResources": [
      {
        "from": "../backend",
        "to": "app/backend",
        "filter": ["**/*.py"]
      },
      {
        "from": "../src",
        "to": "app/src",
        "filter": ["**/*.py"]
      },
      {
        "from": "../bundled-python",
        "to": "bundled-python"
      },
      {
        "from": "../bundled-tesseract",
        "to": "bundled-tesseract"
      }
    ],
```

Note: `bundled-python` and `bundled-tesseract` go directly under `resourcesPath` (not `app/`) because `main.cjs:64` looks for `resourcesPath/bundled-python/bin/python3`.

**Step 2: Commit**

```bash
git add desktop/package.json
git commit -m "fix: add bundled-python and bundled-tesseract to extraResources"
```

---

### Task 4: Fix path alignment between `main.cjs` and `binary_resolver.py`

**Files:**
- Modify: `desktop/electron/main.cjs:78` (TESSDATA_PREFIX)
- Modify: `src/core/binary_resolver.py:37` (tesseract binary path)

**Step 1: Fix TESSDATA_PREFIX in main.cjs**

The bundle script puts tessdata at `bundled-tesseract/tessdata/` but `main.cjs:78` sets `TESSDATA_PREFIX` to `resourcesPath/tessdata`. Fix line 78 in `main.cjs`:

Replace:
```javascript
      TESSDATA_PREFIX: path.join(resourcesPath, 'tessdata'),
```
With:
```javascript
      TESSDATA_PREFIX: path.join(resourcesPath, 'bundled-tesseract', 'tessdata'),
```

**Step 2: Fix tesseract binary path in binary_resolver.py**

The bundle script puts the binary at `bundled-tesseract/tesseract` but `binary_resolver.py:37` looks for `resources / "tesseract"` (which resolves to `{resourcesPath}/tesseract` — a file directly in resources root). Fix the Mac production path in `resolve_tesseract()`.

Replace lines 36-37:
```python
        else:
            candidate = resources / "tesseract"
```
With:
```python
        else:
            candidate = resources / "bundled-tesseract" / "tesseract"
```

**Step 3: Verify dev mode still works**

```bash
cd desktop && npm run dev:electron
```

In dev mode, `RESOURCES_PATH` is not set, so `_resources_path()` returns `None` and the code falls through to system Homebrew paths. Verify Tesseract is found.

**Step 4: Commit**

```bash
git add desktop/electron/main.cjs src/core/binary_resolver.py
git commit -m "fix: align Tesseract paths between bundle script, Electron, and resolver"
```

---

### Task 5: Bump version to 0.1.0

**Files:**
- Modify: `desktop/package.json:4`

**Step 1: Change version**

Replace line 4:
```json
  "version": "2.0.0",
```
With:
```json
  "version": "0.1.0",
```

**Step 2: Commit**

```bash
git add desktop/package.json
git commit -m "chore: bump version to 0.1.0 for Mac preview release"
```

---

### Task 6: Create `THIRD_PARTY_LICENSES.md`

**Files:**
- Create: `THIRD_PARTY_LICENSES.md`

**Step 1: Write the licenses file**

```markdown
# Third-Party Licenses

This application bundles the following open-source software:

## AGPL-3.0

### PyMuPDF (fitz)
- License: GNU Affero General Public License v3.0
- URL: https://github.com/pymupdf/PyMuPDF/blob/main/COPYING
- **Source code availability**: The complete source code for this application
  is available on request. Contact: [your email address]

## MIT License

### Presidio Analyzer
- URL: https://github.com/microsoft/presidio

### spaCy
- URL: https://github.com/explosion/spaCy

### en_core_web_lg (spaCy model)
- URL: https://github.com/explosion/spacy-models

### python-docx
- URL: https://github.com/python-openxml/python-docx

### FastAPI
- URL: https://github.com/tiangolo/fastapi

### uvicorn
- URL: https://github.com/encode/uvicorn

### Electron
- URL: https://github.com/electron/electron

### React
- URL: https://github.com/facebook/react

## Apache 2.0

### Tesseract OCR
- URL: https://github.com/tesseract-ocr/tesseract

## HPND (Historical Permission Notice and Disclaimer)

### Pillow
- URL: https://github.com/python-pillow/Pillow

## PSF License

### Python 3.13 (python-build-standalone)
- URL: https://github.com/astral-sh/python-build-standalone
- Python itself is distributed under the PSF License Agreement.
  The standalone build is provided by Astral under compatible open-source terms.

## pytesseract
- License: Apache 2.0
- URL: https://github.com/madmaze/pytesseract
```

**Step 2: Update the email placeholder**

Replace `[your email address]` with the actual contact email.

**Step 3: Commit**

```bash
git add THIRD_PARTY_LICENSES.md
git commit -m "docs: add THIRD_PARTY_LICENSES.md with AGPL source-code offer"
```

---

### Task 7: Verify entitlements

**Files:**
- Read: `desktop/assets/entitlements.mac.plist` (already correct — no changes needed)

**Step 1: Confirm entitlements are correct**

The current entitlements.mac.plist already contains the three required keys:
- `com.apple.security.cs.allow-jit` — needed for V8/Node
- `com.apple.security.cs.allow-unsigned-executable-memory` — needed for bundled Python
- `com.apple.security.cs.disable-library-validation` — needed for loading bundled .dylib/.so files

No changes needed. Confirm by reading the file and verifying all three keys are present with `<true/>` values.

---

### Task 8: Build the DMG

**Step 1: Ensure bundled-python and bundled-tesseract exist**

```bash
ls -d bundled-python bundled-tesseract
```

If either is missing, run `bash scripts/bundle-python-mac.sh`.

**Step 2: Build the DMG**

```bash
cd desktop && npm run dist:mac
```

This runs `vite build` (React frontend) then `electron-builder --mac --universal`.

**Step 3: Verify output**

```bash
ls -lh desktop/dist/*.dmg
```

Expected: `Redaction Tool-0.1.0-arm64.dmg` at ~300-350MB.

---

### Task 9: Smoke test the DMG

**Step 1: Mount the DMG**

```bash
hdiutil attach "desktop/dist/Redaction Tool-0.1.0-arm64.dmg"
```

**Step 2: Copy to a temp location and launch**

```bash
cp -R "/Volumes/Redaction Tool 0.1.0/Redaction Tool.app" /tmp/
open "/tmp/Redaction Tool.app"
```

**Step 3: Verify checklist**

- [ ] App window opens (Electron window with React UI)
- [ ] Backend health check passes (no error dialog on startup)
- [ ] Can select a folder containing sample PDFs
- [ ] PII detection runs and finds matches (regex + Presidio + spaCy active)
- [ ] Redaction produces output files in the `_redacted` folder
- [ ] Audit log generates

**Step 4: Unmount**

```bash
hdiutil detach "/Volumes/Redaction Tool 0.1.0"
rm -rf "/tmp/Redaction Tool.app"
```

---

### Task 10: Publish GitHub Release

**Step 1: Push all commits and tag**

```bash
git push origin test
git checkout main && git merge test && git push origin main
git tag v0.1.0
git push origin v0.1.0
git checkout test
```

**Step 2: Create GitHub Release**

Go to: https://github.com/mrdavearms/student-doc-redactor/releases/new

- **Tag**: `v0.1.0`
- **Target**: `main`
- **Title**: `Redaction Tool v0.1.0 (Mac Preview)`
- **Description**: Paste the release notes from the design doc (Section 4)
- **Attach**: Upload `desktop/dist/Redaction Tool-0.1.0-arm64.dmg`
- **Check**: "Set as a pre-release"
- **Publish**

**Step 3: Verify**

Visit the release page and confirm:
- DMG downloads successfully
- Release notes render correctly
- Pre-release badge is shown
