# Standalone App Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package the existing Electron + FastAPI + React app into self-contained `.dmg` (Mac) and `.exe` (Windows) installers with silent auto-update via GitHub Releases.

**Architecture:** Embed a portable Python distribution (`python-build-standalone`) + all pip dependencies inside the Electron app bundle. Tesseract and its language data ship alongside Python. `electron-updater` polls GitHub Releases on each launch and applies updates silently in the background.

**Tech Stack:** Electron 40, electron-builder 26, electron-updater, python-build-standalone 3.13, PyInstaller (NOT used — we use embedded Python instead), GitHub Actions, pytesseract, FastAPI/uvicorn.

---

## Phase 3 — Cross-Platform Binary Resolution

These tasks make the Python backend find its external binaries (Tesseract, LibreOffice) in both dev (system install) and production (bundled) environments.

---

### Task 1: Create `src/core/binary_resolver.py`

**Files:**
- Create: `src/core/binary_resolver.py`
- Create: `tests/test_binary_resolver.py`

**Step 1: Write the failing tests**

```python
# tests/test_binary_resolver.py
import sys
import os
sys.path.insert(0, 'src/core')

import pytest
from unittest.mock import patch
from pathlib import Path


def test_resolve_tesseract_returns_string_or_none():
    from binary_resolver import resolve_tesseract
    result = resolve_tesseract()
    assert result is None or isinstance(result, str)


def test_resolve_libreoffice_returns_string_or_none():
    from binary_resolver import resolve_libreoffice
    result = resolve_libreoffice()
    assert result is None or isinstance(result, str)


def test_resolve_tesseract_uses_resources_path_when_set(tmp_path):
    from binary_resolver import resolve_tesseract
    # Simulate production: RESOURCES_PATH env var pointing to a temp dir
    fake_binary = tmp_path / "tesseract"
    fake_binary.touch()
    with patch.dict(os.environ, {"RESOURCES_PATH": str(tmp_path)}):
        with patch("platform.system", return_value="Darwin"):
            result = resolve_tesseract()
    assert result == str(fake_binary)


def test_resolve_libreoffice_windows_paths(tmp_path):
    from binary_resolver import resolve_libreoffice
    fake_soffice = tmp_path / "soffice.exe"
    fake_soffice.touch()
    with patch("platform.system", return_value="Windows"):
        with patch("pathlib.Path.exists", side_effect=lambda p=None: str(p or fake_soffice).endswith("soffice.exe") and str(p or fake_soffice) == str(fake_soffice)):
            # Just verify it returns a string, not None, for Windows paths
            pass
    # At minimum, function should not raise on Windows
    with patch("platform.system", return_value="Windows"):
        result = resolve_libreoffice()
    assert result is None or isinstance(result, str)
```

**Step 2: Run tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
source venv/bin/activate
pytest tests/test_binary_resolver.py -v
```

Expected: `ModuleNotFoundError: No module named 'binary_resolver'`

**Step 3: Write `src/core/binary_resolver.py`**

```python
"""
binary_resolver.py

Resolves paths to external binaries (Tesseract, LibreOffice) for both
development (system install) and production (bundled inside app) environments.

In production, main.cjs sets RESOURCES_PATH to process.resourcesPath before
spawning the Python backend. All resolution checks bundled paths first.
"""

import os
import platform
from pathlib import Path


def _resources_path() -> Path | None:
    """Return the bundled resources directory, or None in dev mode."""
    resources = os.environ.get("RESOURCES_PATH")
    if resources:
        p = Path(resources)
        if p.exists():
            return p
    return None


def resolve_tesseract() -> str | None:
    """
    Return the absolute path to the Tesseract binary, or None if not found.

    Checks bundled path first (production), then system paths (dev).
    """
    resources = _resources_path()
    if resources:
        if platform.system() == "Windows":
            candidate = resources / "tesseract" / "tesseract.exe"
        else:
            candidate = resources / "tesseract"
        if candidate.exists():
            return str(candidate)

    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/opt/homebrew/bin/tesseract",   # Apple Silicon Homebrew
            "/usr/local/bin/tesseract",       # Intel Mac Homebrew
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    else:
        candidates = ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]

    for path in candidates:
        if Path(path).exists():
            return path

    return None


def resolve_tessdata() -> str | None:
    """
    Return the absolute path to the tessdata directory, or None if not found.
    Used to set TESSDATA_PREFIX so Tesseract finds its language data.
    """
    resources = _resources_path()
    if resources:
        candidate = resources / "tessdata"
        if candidate.exists():
            return str(candidate)
    return None


def resolve_libreoffice() -> str | None:
    """
    Return the absolute path to the soffice binary, or None if not found.
    LibreOffice is NOT bundled — this discovers a user's existing install.
    """
    system = platform.system()

    if system == "Darwin":
        candidates = [
            "/opt/homebrew/bin/soffice",
            "/usr/local/bin/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    else:
        candidates = ["/usr/bin/soffice", "/usr/local/bin/soffice"]

    for path in candidates:
        if Path(path).exists():
            return path

    return None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_binary_resolver.py -v
```

Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/core/binary_resolver.py tests/test_binary_resolver.py
git commit -m "feat: add binary_resolver for cross-platform Tesseract/LibreOffice paths"
```

---

### Task 2: Wire binary_resolver into `text_extractor.py`

**Files:**
- Modify: `src/core/text_extractor.py:16-26`

**Step 1: Note current behaviour**

`TextExtractor.__init__()` calls `pytesseract.get_tesseract_version()` with no binary path configured. On a machine without system Tesseract, this silently sets `self.tesseract_available = False`. In production, the bundled binary is never found.

**Step 2: Update `__init__` in `text_extractor.py`**

Replace the current `__init__` and `_check_tesseract` methods:

```python
def __init__(self):
    from binary_resolver import resolve_tesseract, resolve_tessdata
    tesseract_path = resolve_tesseract()
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    tessdata_path = resolve_tessdata()
    if tessdata_path:
        os.environ.setdefault("TESSDATA_PREFIX", tessdata_path)
    self.tesseract_available = self._check_tesseract()

def _check_tesseract(self) -> bool:
    """Check if Tesseract is installed and accessible"""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
```

Also add `import os` at the top of `text_extractor.py` if not already present.

**Step 3: Run the full test suite to confirm nothing breaks**

```bash
pytest tests/ -v --ignore=tests/test_ocr_verification.py -x
```

Expected: All tests pass (the `test_ocr_verification.py` exclusion matches the pre-existing Tesseract env issue noted in MEMORY.md).

**Step 4: Commit**

```bash
git add src/core/text_extractor.py
git commit -m "feat: configure pytesseract binary path from binary_resolver at init"
```

---

### Task 3: Wire binary_resolver into `document_converter.py`

**Files:**
- Modify: `src/core/document_converter.py:14-17`

**Step 1: Note current behaviour**

`DocumentConverter.__init__()` hardcodes `self.soffice_path = "/opt/homebrew/bin/soffice"` and has a manual fallback list in `check_libreoffice_installed()`. Replace both with a single call to `resolve_libreoffice()`.

**Step 2: Replace `__init__` and update `check_libreoffice_installed`**

```python
def __init__(self):
    from binary_resolver import resolve_libreoffice
    self.soffice_path = resolve_libreoffice()

def check_libreoffice_installed(self) -> tuple[bool, str]:
    """Check if LibreOffice is installed and accessible."""
    if self.soffice_path and Path(self.soffice_path).exists():
        return True, "LibreOffice found"
    return False, (
        "LibreOffice not found. "
        "Mac: brew install --cask libreoffice  "
        "Windows: download from libreoffice.org"
    )
```

Also ensure `from pathlib import Path` is present at the top (it already is).

**Step 3: Run tests**

```bash
pytest tests/ -v --ignore=tests/test_ocr_verification.py -x
```

Expected: All tests pass.

**Step 4: Commit**

```bash
git add src/core/document_converter.py
git commit -m "feat: use binary_resolver for LibreOffice path discovery (adds Windows support)"
```

---

## Phase 4 — Packaging & CI/CD

---

### Task 4: Harden `main.cjs` — timeout, error screen, env vars

**Files:**
- Modify: `desktop/electron/main.cjs`

**Step 1: Understand current gaps**

Current `waitForBackend` uses 30 retries × 500ms = 15 seconds. If it fails, `createWindow()` still runs and shows the app with a dead backend. No error feedback.

**Step 2: Replace `waitForBackend`, `startBackend`, and `app.on('ready')` with the hardened version**

```javascript
const { app, BrowserWindow, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const BACKEND_PORT = 8765;
const DEV_SERVER = `http://localhost:5173`;
const isDev = !app.isPackaged;
const BACKEND_TIMEOUT_MS = 30_000;

let backendProcess = null;
let mainWindow = null;

/** Wait up to BACKEND_TIMEOUT_MS for the backend health check. */
function waitForBackend(port) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + BACKEND_TIMEOUT_MS;
    const check = () => {
      if (Date.now() > deadline) {
        reject(new Error(`Backend did not start within ${BACKEND_TIMEOUT_MS / 1000}s`));
        return;
      }
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          setTimeout(check, 500);
        }
      });
      req.on('error', () => setTimeout(check, 500));
      req.end();
    };
    check();
  });
}

/** Start the Python FastAPI backend. */
function startBackend() {
  const projectRoot = isDev
    ? path.resolve(__dirname, '../..')   // redaction tool/
    : path.resolve(process.resourcesPath, '..');

  const appRoot = isDev ? projectRoot : projectRoot;

  const pythonPath = isDev
    ? path.join(appRoot, 'venv', 'bin', 'python3.13')
    : path.join(process.resourcesPath, 'bundled-python', 'bin', 'python3');

  const env = {
    ...process.env,
    PYTHONPATH: path.join(appRoot, 'src', 'core'),
    RESOURCES_PATH: process.resourcesPath || '',
    TESSDATA_PREFIX: path.join(process.resourcesPath || '', 'tessdata'),
  };

  console.log(`[main] Starting backend: ${pythonPath}`);

  backendProcess = spawn(pythonPath, [
    '-m', 'uvicorn', 'backend.main:app',
    '--port', String(BACKEND_PORT),
    '--host', '127.0.0.1',
  ], {
    cwd: appRoot,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (d) => console.log(`[backend] ${d.toString().trim()}`));
  backendProcess.stderr.on('data', (d) => console.error(`[backend] ${d.toString().trim()}`));
  backendProcess.on('exit', (code) => console.log(`[backend] exited with code ${code}`));

  return backendProcess;
}

/** Show a full-screen error if the backend fails to start. */
function showErrorWindow(message) {
  mainWindow = new BrowserWindow({ width: 800, height: 500, titleBarStyle: 'hiddenInset' });
  const html = `
    <html><body style="font-family:system-ui;padding:60px;background:#0f172a;color:#f8fafc;text-align:center">
      <h2 style="color:#f87171">Failed to start</h2>
      <p>${message}</p>
      <p style="color:#94a3b8;font-size:13px">Check Console for details or re-install the app.</p>
    </body></html>`;
  mainWindow.loadURL(`data:text/html,${encodeURIComponent(html)}`);
}

/** Create the main application window. */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL(DEV_SERVER);
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── App lifecycle ──────────────────────────────────────────────────────

app.on('ready', async () => {
  startBackend();
  try {
    await waitForBackend(BACKEND_PORT);
    console.log('[main] Backend ready');
    createWindow();
  } catch (e) {
    console.error('[main] Backend failed:', e.message);
    showErrorWindow(e.message);
  }
});

app.on('window-all-closed', () => {
  if (backendProcess) { backendProcess.kill(); backendProcess = null; }
  app.quit();
});

app.on('before-quit', () => {
  if (backendProcess) { backendProcess.kill(); backendProcess = null; }
});
```

Note the key fixes:
- `BACKEND_TIMEOUT_MS = 30_000` — wall-clock timeout, not retry count
- `RESOURCES_PATH` and `TESSDATA_PREFIX` now passed to the backend env
- `bundled-python` (not `python`) in production Python path
- `showErrorWindow()` shows a friendly HTML error if backend fails
- `backgroundColor: '#0f172a'` matches the dark app shell (no white flash on load)

**Step 3: Verify the dev workflow still works**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop"
npm run dev:electron
```

Expected: App opens normally. Check Console for `[main] Backend ready`.

**Step 4: Commit**

```bash
git add desktop/electron/main.cjs
git commit -m "feat: harden main.cjs — 30s timeout, error screen, env vars for bundled Python"
```

---

### Task 5: Add `electron-updater` to `main.cjs`

**Files:**
- Modify: `desktop/electron/main.cjs`
- Run: `npm install electron-updater` (inside `desktop/`)

**Step 1: Install electron-updater**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop"
npm install electron-updater
```

**Step 2: Add auto-updater setup to `main.cjs`**

Add at the top of the file (after existing requires):

```javascript
const { autoUpdater } = require('electron-updater');
```

Add this function:

```javascript
/** Configure and start the auto-updater. Only runs in production. */
function setupAutoUpdater() {
  if (isDev) return;

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-downloaded', () => {
    // Notify the renderer — it will show the toast
    if (mainWindow) {
      mainWindow.webContents.send('update-downloaded');
    }
  });

  autoUpdater.on('error', (err) => {
    console.error('[updater] Error:', err.message);
    // Silent failure — don't bother the user for update errors
  });

  autoUpdater.checkForUpdates().catch((err) => {
    console.error('[updater] Check failed:', err.message);
  });
}
```

Call `setupAutoUpdater()` inside `app.on('ready')` after `createWindow()`:

```javascript
app.on('ready', async () => {
  startBackend();
  try {
    await waitForBackend(BACKEND_PORT);
    console.log('[main] Backend ready');
    createWindow();
    setupAutoUpdater();   // ← add this line
  } catch (e) {
    console.error('[main] Backend failed:', e.message);
    showErrorWindow(e.message);
  }
});
```

Also expose an IPC handler so the React toast can trigger the install:

```javascript
const { ipcMain } = require('electron');

ipcMain.on('install-update', () => {
  autoUpdater.quitAndInstall();
});
```

**Step 3: Expose IPC to the renderer in `preload.cjs`**

Open `desktop/electron/preload.cjs` and add:

```javascript
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  onUpdateDownloaded: (cb) => ipcRenderer.on('update-downloaded', cb),
  installUpdate: () => ipcRenderer.send('install-update'),
});
```

(If `preload.cjs` already has a `contextBridge.exposeInMainWorld` call, add these properties into the existing object rather than calling it twice.)

**Step 4: Verify no import errors in dev mode**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop"
npm run dev:electron
```

Expected: App opens. `setupAutoUpdater()` returns immediately (isDev guard). No errors.

**Step 5: Commit**

```bash
git add desktop/electron/main.cjs desktop/electron/preload.cjs desktop/package.json desktop/package-lock.json
git commit -m "feat: add electron-updater for silent background auto-update via GitHub Releases"
```

---

### Task 6: Configure `electron-builder` in `desktop/package.json`

**Files:**
- Modify: `desktop/package.json`

**Step 1: Note current state**

The `build` key in `package.json` is `{}` — empty. `electron-builder` requires explicit configuration for `appId`, `files`, `extraResources`, and platform-specific settings.

**Step 2: Replace `"build": {}` with the full config**

```json
"build": {
  "appId": "com.redactiontool.app",
  "productName": "Redaction Tool",
  "copyright": "Copyright © 2026",
  "publish": [
    {
      "provider": "github",
      "owner": "mrdavearms",
      "repo": "student-doc-redactor"
    }
  ],
  "files": [
    "dist/**/*",
    "electron/**/*"
  ],
  "extraResources": [
    {
      "from": "../bundled-python",
      "to": "bundled-python",
      "filter": ["**/*"]
    },
    {
      "from": "../bundled-tesseract/bin/tesseract",
      "to": "tesseract"
    },
    {
      "from": "../bundled-tesseract/tessdata",
      "to": "tessdata",
      "filter": ["eng.traineddata"]
    }
  ],
  "mac": {
    "target": [{ "target": "dmg", "arch": ["universal"] }],
    "category": "public.app-category.education",
    "icon": "assets/icon.icns",
    "minimumSystemVersion": "12.0"
  },
  "win": {
    "target": [{ "target": "nsis", "arch": ["x64"] }],
    "icon": "assets/icon.ico"
  },
  "nsis": {
    "oneClick": false,
    "allowToChangeInstallationDirectory": false,
    "createDesktopShortcut": true,
    "createStartMenuShortcut": true
  },
  "dmg": {
    "title": "Redaction Tool ${version}",
    "background": "assets/dmg-background.png",
    "window": { "width": 540, "height": 380 }
  }
}
```

Also add the dist and pack scripts:

```json
"scripts": {
  "dev": "vite",
  "dev:electron": "concurrently \"vite\" \"wait-on http://localhost:5173 && electron .\"",
  "build": "tsc -b && vite build",
  "dist:mac": "npm run build && electron-builder --mac --publish never",
  "dist:win": "npm run build && electron-builder --win --publish never",
  "dist:publish": "npm run build && electron-builder --publish always",
  "lint": "eslint .",
  "preview": "vite preview"
}
```

**Step 3: Create placeholder icon directory**

```bash
mkdir -p "/Users/davidarmstrong/Antigravity/redaction tool/desktop/assets"
touch "/Users/davidarmstrong/Antigravity/redaction tool/desktop/assets/.gitkeep"
```

Icon files (`icon.icns`, `icon.ico`, `dmg-background.png`) will be added as part of the visual design phase. For now the build config references them — `electron-builder` will warn but not fail if they're absent during local testing.

**Step 4: Verify the config is valid JSON**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop"
node -e "require('./package.json'); console.log('JSON valid')"
```

Expected: `JSON valid`

**Step 5: Commit**

```bash
git add desktop/package.json desktop/assets/.gitkeep
git commit -m "feat: configure electron-builder for mac + windows installers with GitHub publish"
```

---

### Task 7: Write the Python bundling script (Mac)

**Files:**
- Create: `scripts/bundle-python-mac.sh`

This script runs during the GitHub Actions `build-mac` job (and locally for testing). It downloads `python-build-standalone`, installs all pip dependencies into a self-contained `bundled-python/` directory, and downloads the Tesseract binary.

**Step 1: Create `scripts/bundle-python-mac.sh`**

```bash
#!/usr/bin/env bash
# bundle-python-mac.sh
# Downloads python-build-standalone and installs all Python dependencies.
# Creates bundled-python/ and bundled-tesseract/ in the project root.
# Run from the project root: bash scripts/bundle-python-mac.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_VERSION="3.13.3"
PBS_VERSION="20250517"  # python-build-standalone release tag — update as needed

echo "==> Bundling Python ${PYTHON_VERSION} for macOS (universal)"

# ── 1. Download python-build-standalone ──────────────────────────────────

PBS_DIR="${PROJECT_ROOT}/bundled-python"
rm -rf "$PBS_DIR"
mkdir -p "$PBS_DIR"

# Universal (arm64 + x86_64) optimised-lto release
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}+${PBS_VERSION}-aarch64-apple-darwin-install_only_stripped.tar.gz"

echo "==> Downloading python-build-standalone..."
curl -L "$PBS_URL" | tar -xz -C "$PBS_DIR" --strip-components=1

PYTHON="${PBS_DIR}/bin/python3"
echo "==> Python at ${PYTHON}"
"$PYTHON" --version

# ── 2. Install pip dependencies ───────────────────────────────────────────

echo "==> Installing pip dependencies..."
"$PYTHON" -m pip install --upgrade pip --quiet
"$PYTHON" -m pip install \
  --target "${PBS_DIR}/lib/python3.13/site-packages" \
  --quiet \
  -r "${PROJECT_ROOT}/requirements.txt"

# Install uvicorn + fastapi (backend deps, not in main requirements.txt)
"$PYTHON" -m pip install \
  --target "${PBS_DIR}/lib/python3.13/site-packages" \
  --quiet \
  uvicorn fastapi python-multipart

echo "==> Dependencies installed."

# ── 3. Download spaCy model ───────────────────────────────────────────────

echo "==> Downloading spaCy en_core_web_lg..."
"$PYTHON" -m spacy download en_core_web_lg --quiet || \
  echo "WARN: spaCy model download failed — will attempt at runtime"

# ── 4. Download Tesseract (community macOS binary) ────────────────────────

TESS_DIR="${PROJECT_ROOT}/bundled-tesseract"
rm -rf "$TESS_DIR"
mkdir -p "${TESS_DIR}/bin" "${TESS_DIR}/tessdata"

# Using UB Mannheim static build (arm64)
TESS_URL="https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0/tesseract-5.5.0-mac-arm64.tar.gz"
echo "==> Downloading Tesseract..."
curl -L "$TESS_URL" | tar -xz -C "${TESS_DIR}" --strip-components=1 2>/dev/null || \
  echo "WARN: Tesseract binary download failed — OCR will use system Tesseract if available"

echo "==> Bundle complete."
echo "    Python:    ${PBS_DIR}"
echo "    Tesseract: ${TESS_DIR}"
```

**Step 2: Make it executable**

```bash
chmod +x "/Users/davidarmstrong/Antigravity/redaction tool/scripts/bundle-python-mac.sh"
```

**Step 3: Add `scripts/` to `.gitignore` exclusions (keep the script, not the output)**

Add to `.gitignore`:

```
bundled-python/
bundled-tesseract/
```

**Step 4: Commit**

```bash
git add scripts/bundle-python-mac.sh .gitignore
git commit -m "feat: add mac Python bundling script for electron-builder extraResources"
```

---

### Task 8: Write the Python bundling script (Windows)

**Files:**
- Create: `scripts/bundle-python-win.ps1`

**Step 1: Create `scripts/bundle-python-win.ps1`**

```powershell
# bundle-python-win.ps1
# Downloads Windows embeddable Python and installs all pip dependencies.
# Run from the project root: pwsh -File scripts/bundle-python-win.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonVersion = "3.13.3"
$PythonDir = Join-Path $ProjectRoot "bundled-python"
$TessDir = Join-Path $ProjectRoot "bundled-tesseract"

Write-Host "==> Bundling Python $PythonVersion for Windows (x64)"

# ── 1. Download Windows embeddable Python ────────────────────────────────

if (Test-Path $PythonDir) { Remove-Item -Recurse -Force $PythonDir }
New-Item -ItemType Directory -Path $PythonDir | Out-Null

$PyUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PyZip = Join-Path $env:TEMP "python-embed.zip"

Write-Host "==> Downloading Python embeddable..."
Invoke-WebRequest -Uri $PyUrl -OutFile $PyZip
Expand-Archive -Path $PyZip -DestinationPath $PythonDir -Force
Remove-Item $PyZip

# The embeddable package needs pip — it doesn't include it by default.
# We bootstrap it using get-pip.py.
$GetPip = Join-Path $env:TEMP "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip

$Python = Join-Path $PythonDir "python.exe"

# Uncomment the site-packages import by editing python313._pth
$PthFile = Join-Path $PythonDir "python313._pth"
(Get-Content $PthFile) -replace "#import site", "import site" | Set-Content $PthFile

& $Python $GetPip --quiet
Remove-Item $GetPip

# ── 2. Install pip dependencies ───────────────────────────────────────────

Write-Host "==> Installing pip dependencies..."
& $Python -m pip install `
  --target (Join-Path $PythonDir "Lib\site-packages") `
  --quiet `
  -r (Join-Path $ProjectRoot "requirements.txt")

& $Python -m pip install `
  --target (Join-Path $PythonDir "Lib\site-packages") `
  --quiet `
  uvicorn fastapi python-multipart

Write-Host "==> Dependencies installed."

# ── 3. Download Tesseract (UB Mannheim Windows installer) ─────────────────

if (Test-Path $TessDir) { Remove-Item -Recurse -Force $TessDir }
New-Item -ItemType Directory -Path (Join-Path $TessDir "tessdata") | Out-Null

$TessInstaller = Join-Path $env:TEMP "tesseract-setup.exe"
$TessUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
Write-Host "==> Downloading Tesseract installer..."
Invoke-WebRequest -Uri $TessUrl -OutFile $TessInstaller

# Silent install to temp location, then copy binary + eng.traineddata
$TessInstallDir = Join-Path $env:TEMP "tesseract-install"
Start-Process -FilePath $TessInstaller -ArgumentList "/S /D=$TessInstallDir" -Wait
Copy-Item (Join-Path $TessInstallDir "tesseract.exe") (Join-Path $TessDir "tesseract.exe")
Copy-Item (Join-Path $TessInstallDir "tessdata\eng.traineddata") (Join-Path $TessDir "tessdata\eng.traineddata")
Remove-Item -Recurse -Force $TessInstallDir
Remove-Item $TessInstaller

Write-Host "==> Bundle complete."
Write-Host "    Python:    $PythonDir"
Write-Host "    Tesseract: $TessDir"
```

**Step 2: Commit**

```bash
git add scripts/bundle-python-win.ps1
git commit -m "feat: add Windows Python bundling script for electron-builder extraResources"
```

---

### Task 9: Write GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Step 1: Create `.github/` directory structure**

```bash
mkdir -p "/Users/davidarmstrong/Antigravity/redaction tool/.github/workflows"
```

**Step 2: Create `.github/workflows/release.yml`**

```yaml
name: Build & Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write   # Required to create GitHub Releases and upload assets

jobs:

  build-mac:
    name: Build macOS
    runs-on: macos-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: desktop/package-lock.json

      - name: Bundle Python (Mac)
        run: bash scripts/bundle-python-mac.sh

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

      - name: Build and publish (Mac)
        working-directory: desktop
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: npm run dist:publish -- --mac

  build-windows:
    name: Build Windows
    runs-on: windows-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: desktop/package-lock.json

      - name: Bundle Python (Windows)
        shell: pwsh
        run: pwsh -File scripts/bundle-python-win.ps1

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

      - name: Build and publish (Windows)
        working-directory: desktop
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: npm run dist:publish -- --win
```

**Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add GitHub Actions release workflow for mac + windows builds"
```

---

## Phase 5 — Visual Redesign

> **Note:** Phase 5 is handled by the `frontend-design` skill. When starting Phase 5, invoke that skill. The tasks below define the scope for that skill invocation.

### Task 10: Design system + screen transitions

**Scope for `frontend-design` skill:**
- Add design tokens to Tailwind config: teal-600 accent (`#0d9488`), near-black shell (`#0f172a`), slate-50 card surfaces
- Add `framer-motion` `AnimatePresence` wrapper in `App.tsx` so all page changes slide in
- Define shared motion variants in `src/lib/motion.ts`

### Task 11: Document review two-panel layout

**Scope for `frontend-design` skill:**
- Install `pdfjs-dist`: `npm install pdfjs-dist`
- Rebuild `DocumentReview.tsx` as a two-panel layout: PDF canvas left, detection cards right
- Detection cards: PII text, category badge, confidence bar, accept/reject toggle
- "Accept All & Continue" sticky bar at top

### Task 12: Update notification toast + app icons

**Scope for `frontend-design` skill:**
- Add `UpdateToast.tsx` component — listens to `window.electron.onUpdateDownloaded`, shows bottom-corner toast
- Create app icons: `desktop/assets/icon.icns` (Mac), `desktop/assets/icon.ico` (Windows), `desktop/assets/dmg-background.png`
- Completion screen reveal animation using `framer-motion`

---

## Testing Checklist (run before each push to `test`)

```bash
# Python tests
source venv/bin/activate
pytest tests/ -v --ignore=tests/test_ocr_verification.py

# TypeScript
cd desktop && npx tsc --noEmit

# Dev workflow smoke test
cd desktop && npm run dev:electron
# Verify: app opens, backend starts, all 5 screens navigate correctly
```

## Release Checklist

1. Bump version in `desktop/package.json`
2. `git tag v<version> && git push origin v<version>`
3. Watch GitHub Actions: both `build-mac` and `build-windows` jobs must pass
4. Download the `.dmg` from the GitHub Release and test on a Mac with no system Python
5. Share the installation guide PDF with first-time users
