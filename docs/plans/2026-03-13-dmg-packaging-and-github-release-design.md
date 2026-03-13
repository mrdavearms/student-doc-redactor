# Design: Mac DMG Packaging & GitHub Release (v0.1.0)

**Date**: 2026-03-13
**Status**: Approved
**Builds on**: `2026-03-12-standalone-app-design.md`, `2026-03-12-standalone-app-packaging.md`

---

## Goal

Produce a slimmed Mac `.dmg` installer (~300-350MB) and publish it as a
GitHub pre-release (v0.1.0) with clear documentation for non-technical users.

---

## 1. Bundle Slimming (Approach B)

The Electron app uses FastAPI, not Streamlit. GLiNER is experimental and its
dependency tree is massive. Both are removed from the desktop bundle.

### New file: `requirements-desktop.txt`

A curated subset of `requirements.txt` that **excludes**:

| Package | Size | Why removable |
|---------|------|---------------|
| `streamlit` | 28MB | Desktop uses FastAPI, not Streamlit |
| `pyarrow` | 120MB | Streamlit dataframe rendering only |
| `pandas` | 70MB | Streamlit dataframe rendering only |
| `pydeck` | 14MB | Streamlit map widgets |
| `altair` | 9.5MB | Streamlit chart widgets |
| `gliner` | ~5MB | Optional zero-shot NER |
| `torch` | 397MB | GLiNER's ML backend |
| `transformers` | 94MB | GLiNER model loading |
| `sympy` | 72MB | torch dependency |
| `onnxruntime` | 68MB | GLiNER inference |

**Kept**: `pymupdf`, `pytesseract`, `Pillow`, `python-docx`, `presidio-analyzer`,
`spacy`, `phonenumbers`, `fastapi`, `uvicorn`, and all their real dependencies.

### Changes to `bundle-python-mac.sh`

- Use `requirements-desktop.txt` instead of `requirements.txt`
- Remove the GLiNER pre-warming step (`python -c "from gliner import GLiNER..."`)
- Keep spaCy `en_core_web_lg` download (Presidio depends on it)
- Add post-install cleanup: strip `__pycache__/`, `*.dist-info/`, `tests/` from site-packages

### Detection impact

None for regex + Presidio + spaCy. The orchestrator already degrades gracefully
when GLiNER is absent (`_init_gliner()` catches all exceptions, sets detector to
`None`). No code changes needed in the detection pipeline.

---

## 2. Version & Build Configuration

- **Version**: `0.1.0` (bump from `1.0.0` in `package.json`)
- **Target**: macOS arm64 (Apple Silicon). Intel Macs supported via Rosetta 2.
- **Code signing**: Unsigned for v0.1.0. Users right-click -> Open on first launch.
- **App icon**: Custom icon created (`icon.icns` + `icon.ico`) — redacted document
  on navy background with teal lock accent.
- **Entitlements**: Verify `entitlements.mac.plist` includes
  `com.apple.security.cs.allow-unsigned-executable-memory` for bundled Python.

---

## 3. Build Process (Local)

No CI for v0.1.0 — GitHub Actions runners lack Homebrew/Tesseract.

```bash
# 1. Bundle portable Python + Tesseract
bash scripts/bundle-python-mac.sh

# 2. Build React frontend
cd desktop && npm run build

# 3. Package into DMG
npm run dist:mac
```

**Output**: `desktop/dist/Redaction Tool-0.1.0-arm64.dmg` (~300-350MB)

### Smoke test before release

- [ ] App window opens
- [ ] Backend health check passes (Python spawns correctly)
- [ ] Folder selection works
- [ ] PII detection runs (regex + Presidio + spaCy)
- [ ] Redaction produces output files
- [ ] Audit log generates

---

## 4. GitHub Release

**Process**: Manual release via GitHub web UI.

1. `git tag v0.1.0 && git push origin v0.1.0`
2. GitHub -> Releases -> "Draft a new release"
3. Select `v0.1.0` tag
4. Paste release notes (see below)
5. Upload `.dmg` as release asset
6. Mark as **pre-release**
7. Publish

### Release notes

```markdown
# Redaction Tool v0.1.0 (Mac Preview)

Bulk PII redaction for student assessment PDFs and Word documents.
Built for Australian teachers and school psychologists. All processing
is local — no internet required at runtime.

## System Requirements
- macOS 12 (Monterey) or later
- Apple Silicon (M1/M2/M3/M4) — Intel Macs work via Rosetta 2
- ~1GB disk space

## Installation
1. Download `Redaction-Tool-0.1.0-arm64.dmg` below
2. Open the DMG and drag **Redaction Tool** to Applications
3. On first launch: right-click the app -> **Open** -> click **Open**
   in the dialog (required once for unsigned apps)

## What's Included
- Regex PII detection (Australian patterns: phone, Medicare, CRN, etc.)
- Presidio + spaCy NER detection (names, organisations, dates)
- PDF text-layer and OCR image redaction
- Word document conversion and redaction
- Signature detection (heuristic)
- Header/footer zone blanking
- Metadata stripping and audit logging

## Known Limitations
- **Mac only** — Windows support planned for a future release
- **No auto-update** — check this page for new versions
- **GLiNER model not included** — enhanced zero-shot NER will be
  available as an optional download in a future release
- **Unsigned app** — requires the right-click -> Open workaround
  on first launch

## Feedback
File issues at https://github.com/mrdavearms/student-doc-redactor/issues
```

---

## 5. License Compliance

### PyMuPDF (AGPL-3.0)

AGPL requires source availability when distributing binaries. The repo is
currently private. For v0.1.0, include a written source-code offer in the
release notes and in `THIRD_PARTY_LICENSES.md`:

> "Source code is available on request — contact [email]."

Before v1.0.0, either make the repo public (after replacing sample/ with
synthetic data) or evaluate Artifex's commercial PyMuPDF license.

### Other dependencies

All MIT, BSD, Apache 2.0, or PSF licensed. Attribution provided in
`THIRD_PARTY_LICENSES.md`.

### New file: `THIRD_PARTY_LICENSES.md`

Lists every bundled dependency, its license, and a link to the license text.
Includes the AGPL source-code offer for PyMuPDF.

---

## 6. Explicitly Out of Scope (v0.1.0)

- Windows build
- Auto-update (electron-updater)
- CI/CD build pipeline
- GLiNER bundling or lazy-download UI
- Code signing / notarisation
- Custom DMG background image
- App icon polish beyond v0.1.0 placeholder

---

## Deliverables Summary

| Deliverable | Purpose |
|-------------|---------|
| `requirements-desktop.txt` | Slimmed pip deps (no Streamlit, no GLiNER) |
| Updated `bundle-python-mac.sh` | Uses desktop requirements, strips cache, removes GLiNER warm |
| `icon.icns` + `icon.ico` | App icons (done) |
| `THIRD_PARTY_LICENSES.md` | License attribution + AGPL source offer |
| `package.json` version bump | `1.0.0` -> `0.1.0` |
| Entitlements verification | Ensure bundled Python can execute |
| Local DMG build + smoke test | Verify app works from packaged DMG |
| GitHub Release | Tag v0.1.0, upload DMG, release notes, pre-release |
