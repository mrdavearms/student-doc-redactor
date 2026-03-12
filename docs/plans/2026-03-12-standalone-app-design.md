# Standalone Desktop App — Design Document

**Date:** 2026-03-12
**Status:** Approved
**Scope:** Package the existing Electron + FastAPI + React app into self-contained installers for Mac and Windows, with auto-update via GitHub Releases and a polished UI.

---

## Context

The Redaction Tool currently exists in two forms:

1. **Streamlit app** (`app.py`) — the developer's personal test/dev harness. Stays as-is.
2. **Electron + FastAPI + React app** (`desktop/`, `backend/`) — Phase 2 build, fully functional but not yet packaged for distribution.

The goal is to produce installers that a non-technical teacher can download and run on their Mac or Windows machine, with no Python install required, and that self-update silently when new versions are released.

---

## Approach: Embedded Real Python Distribution

Rather than freezing Python via PyInstaller (fragile with ML packages), we embed a complete portable Python distribution inside the app bundle. Packages are pre-installed into a `bundled-python/` directory during the CI build. At runtime, Electron spawns this bundled Python directly.

**Why not PyInstaller:** spaCy, GLiNER, and PyMuPDF all use C extensions and dynamic imports that confuse PyInstaller's dependency tracer. Debugging `.spec` files for a 500MB+ ML stack would consume weeks, and frozen executables frequently trigger antivirus false positives on Windows.

**Why not lean installer + first-run download:** Requires internet on first launch — a dealbreaker for schools with restrictive network policies.

---

## Section 1 — Bundle Architecture

```
Redaction Tool.app/
└── Contents/
    └── Resources/
        ├── bundled-python/          # Portable Python environment
        │   ├── bin/python3          # Python 3.13 interpreter (Mac)
        │   └── lib/python3.13/
        │       └── site-packages/   # All pip dependencies
        ├── tessdata/                # Tesseract language data
        ├── tesseract                # Tesseract binary (Mac)
        └── app/                    # Electron + React built assets
```

Windows equivalent uses `bundled-python\python.exe` and `tesseract.exe`.

**Key runtime change in `main.cjs`:**
- Development: uses system Python via `which python3`
- Production: uses `path.join(process.resourcesPath, 'bundled-python', 'bin', 'python3')`
- `TESSERACT_CMD` environment variable is set to the bundled binary path before spawning the backend

**LibreOffice:** Not bundled (350MB, separate installer). On first launch the app checks known paths. If not found, a friendly modal offers a "Download LibreOffice" button. Word-to-PDF conversion is disabled until installed. Teachers working PDF-only never see this modal.

---

## Section 2 — CI/CD Pipeline

Triggered by pushing a version tag: `git tag v2.1.0 && git push origin v2.1.0`

### `build-mac` job (`macos-latest`)
1. Checkout repo
2. Download `python-build-standalone` for both `aarch64-apple-darwin` and `x86_64-apple-darwin`
3. `pip install -r requirements.txt --target bundled-python/lib/python3.13/site-packages/`
4. Download pinned Tesseract binary + `tessdata/` from community release
5. `npm run build` in `desktop/`
6. `electron-builder --mac --publish always` → builds universal `.dmg`, uploads to GitHub Release

### `build-windows` job (`windows-latest`)
1. Checkout repo
2. Download Windows embeddable Python 3.13 from python.org
3. Same `pip install` into bundle
4. Download Tesseract Windows binary + `tessdata/`
5. `electron-builder --win --publish always` → builds NSIS `.exe` installer, uploads to GitHub Release

### GitHub Release artifacts
```
Redaction-Tool-2.1.0.dmg         ← Mac installer
Redaction-Tool-Setup-2.1.0.exe   ← Windows installer
latest-mac.yml                    ← Mac update metadata (read by electron-updater)
latest.yml                        ← Windows update metadata
```

Both jobs run in parallel. A release is created automatically when the tag is pushed.

---

## Section 3 — Auto-Update Flow

`electron-updater` is configured in `main.cjs` to point at the GitHub repo. No update server required — it polls the GitHub Releases API directly.

### User experience
- **On every launch:** Silent background check. If no update, nothing happens.
- **Update available:** A non-intrusive toast in the bottom corner — *"An update is ready. Restart to install."* — with **Restart Now** and dismiss options. The update has already been downloaded in the background.
- **Restart:** ~5 seconds. New version running.
- **First install:** No update check (version is already current).

### Developer workflow
1. Bump version in `desktop/package.json`
2. `git tag v2.1.0 && git push origin v2.1.0`
3. CI builds and publishes
4. Every installed copy picks it up on next launch

### Edge cases
- No internet → update check fails silently, app works normally
- Download interrupted → old version stays installed, retry on next launch
- Corrupt download → `electron-updater` verifies checksum before applying

---

## Section 4 — Visual Design Direction

The existing React frontend uses Tailwind utility classes without a cohesive design language. Three specific changes make it "visually stunning":

### 1. Design system
- **Accent colour:** Deep teal (`#0d9488` / `teal-600`)
- **Backgrounds:** Near-black app shell (`#0f172a`), white card surfaces
- **Typography:** Consistent scale, Inter or system-ui font stack
- **Spacing/radius/shadow:** Single shared scale across all screens — consistency is polish

### 2. Motion via `framer-motion` (already installed, currently unused)
- Screen transitions: slide-in on navigation
- PII detection results: fade in as matches are found
- Progress bar: smooth animated fill
- Completion screen: satisfying reveal animation
- All motion communicates state, not decoration

### 3. Document review screen redesign
The screen where teachers spend the most time gets a two-panel layout:
- **Left:** Rendered PDF page (`pdfjs-dist`) with detected PII highlighted in-context
- **Right:** Detection result cards — PII text, category, confidence indicator, accept/reject toggle
- **Top:** "Accept All & Continue" for the fast path
- **Bottom:** Per-document navigation

The `frontend-design` skill handles implementation of this section.

---

## Section 5 — Error Handling

### Backend fails to start
Current behaviour: health check waits indefinitely.
New behaviour: 30-second timeout → full-screen error page with crash log path and "Send log to developer" button (opens pre-filled email).

### Bundled Python corrupt
Checked at startup by verifying the interpreter exists and is executable. If not → modal prompts re-download from latest GitHub Release URL (hardcoded in app).

### Disk write failure
Redacted PDF write failure surfaces as a friendly message on the final confirmation screen rather than a silent Python exception.

### Gatekeeper / SmartScreen (first install only)
A one-page PDF installation guide ships with every GitHub Release, with annotated screenshots showing:
- Mac: right-click → Open (bypasses Gatekeeper)
- Windows: "More info" → "Run anyway" (bypasses SmartScreen)

Teachers should be briefed on this before downloading.

---

## Implementation Phases

### Phase 3 — Windows Support
- Bundle Tesseract binary + `tessdata/` for Windows
- Adjust LibreOffice path discovery for Windows paths
- Validate all Python dependencies install cleanly on Windows

### Phase 4 — Packaging & CI/CD
- Configure `electron-builder` in `desktop/package.json` (currently `{}`)
- Write Python bundling build script (`scripts/bundle-python.sh` / `.ps1`)
- Write GitHub Actions workflow (`.github/workflows/release.yml`)
- Integrate `electron-updater` into `main.cjs`
- Update `main.cjs` production Python path to `process.resourcesPath`
- Test full build locally before CI

### Phase 5 — Visual Redesign
- Design system tokens (colours, spacing, shadows) in Tailwind config
- `framer-motion` transitions on all screen changes
- Document review two-panel layout with PDF preview
- PII result cards with confidence indicators
- Completion screen reveal animation
- Toast notification component for auto-update

---

## Key Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| spaCy/GLiNER model too large for bundle | Medium | Test bundle size early; GLiNER downloads on first run if > 700MB threshold |
| Windows pip install fails for a dependency | Medium | Test `build-windows` job early in Phase 4 |
| Gatekeeper friction causes teacher confusion | High | Installation guide PDF + pre-briefing |
| LibreOffice not installed on teacher machines | Medium | Graceful modal, PDF-only teachers unaffected |
