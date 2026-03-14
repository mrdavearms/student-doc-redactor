# First-Run Setup & Cross-Platform Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a first-run setup screen for missing LibreOffice, fix cross-platform bugs so both Mac and Windows builds work correctly, and make "Check for Updates" more prominent.

**Architecture:** A new `Setup` screen gates the app when LibreOffice is missing. Bug fixes touch `binary_resolver.py` (Tesseract path), `main.cjs` (Python paths, titleBarStyle), `FolderSelection.tsx` (placeholder), and `AboutModal.tsx` (update button). All changes are platform-aware using `process.platform` (Electron) or `platform.system()` (Python).

**Tech Stack:** React + TypeScript (frontend), Python (backend), Electron (main process)

---

### Task 1: Fix Tesseract bundled path on Windows

**Files:**
- Modify: `src/core/binary_resolver.py:34-35`

**Step 1: Fix the path**

In `src/core/binary_resolver.py`, change line 35 from:
```python
            candidate = resources / "tesseract" / "tesseract.exe"
```
to:
```python
            candidate = resources / "bundled-tesseract" / "tesseract.exe"
```

This matches the actual bundle location created by `scripts/bundle-python-win.ps1` and the `extraResources` config in `package.json` which maps `../bundled-tesseract` to `bundled-tesseract`.

**Step 2: Run tests**

Run: `pytest tests/test_binary_resolver.py -v`
Expected: All 6 tests PASS (tests mock paths, so this validates no import errors)

**Step 3: Commit**

```bash
git add src/core/binary_resolver.py
git commit -m "fix: correct Tesseract bundled path for Windows

The binary resolver looked for resources/tesseract/tesseract.exe on Windows
but the bundle script places it at resources/bundled-tesseract/tesseract.exe."
```

---

### Task 2: Fix Python spawn paths in Electron main process

**Files:**
- Modify: `desktop/electron/main.cjs:52-94`

**Step 1: Replace the `startBackend()` function's path resolution**

In `desktop/electron/main.cjs`, replace lines 53-64:
```javascript
  const resourcesPath = isDev
    ? path.resolve(__dirname, '..', '..')   // redaction tool/ in dev
    : process.resourcesPath;

  const appRoot = isDev
    ? resourcesPath                          // redaction tool/
    : path.join(resourcesPath, 'app');

  // Find the Python executable
  const pythonPath = isDev
    ? path.join(appRoot, 'venv', 'bin', 'python3.13')
    : path.join(resourcesPath, 'bundled-python', 'bin', 'python3');
```

with:
```javascript
  const resourcesPath = isDev
    ? path.resolve(__dirname, '..', '..')   // repo root in dev
    : process.resourcesPath;

  const appRoot = isDev
    ? resourcesPath
    : path.join(resourcesPath, 'app');

  const isWin = process.platform === 'win32';

  // Find the Python executable (platform-aware)
  let pythonPath;
  if (isDev) {
    pythonPath = isWin
      ? path.join(appRoot, 'venv', 'Scripts', 'python.exe')
      : path.join(appRoot, 'venv', 'bin', 'python3.13');
  } else {
    pythonPath = isWin
      ? path.join(resourcesPath, 'bundled-python', 'python.exe')
      : path.join(resourcesPath, 'bundled-python', 'bin', 'python3');
  }
```

**Step 2: Verify no syntax errors**

Run: `node -c "F:/antigravity/doc redactor/desktop/electron/main.cjs"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add desktop/electron/main.cjs
git commit -m "fix: platform-aware Python paths in Electron main process

Dev mode now uses venv/Scripts/python.exe on Windows and
venv/bin/python3.13 on Mac. Prod uses bundled-python/python.exe
on Windows and bundled-python/bin/python3 on Mac."
```

---

### Task 3: Fix titleBarStyle and window options

**Files:**
- Modify: `desktop/electron/main.cjs:97-121`

**Step 1: Gate titleBarStyle behind macOS check**

In `desktop/electron/main.cjs`, replace the `createWindow()` function's BrowserWindow options (lines 98-110):
```javascript
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
```

with:
```javascript
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 900,
    minHeight: 600,
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset' } : {}),
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
```

**Step 2: Verify no syntax errors**

Run: `node -c "F:/antigravity/doc redactor/desktop/electron/main.cjs"`
Expected: No output (valid syntax)

**Step 3: Commit**

```bash
git add desktop/electron/main.cjs
git commit -m "fix: gate titleBarStyle behind macOS platform check"
```

---

### Task 4: Fix folder placeholder for Windows

**Files:**
- Modify: `desktop/src/pages/FolderSelection.tsx:68`

**Step 1: Replace hardcoded Mac placeholder**

In `desktop/src/pages/FolderSelection.tsx`, replace line 68:
```tsx
            placeholder="/Users/username/Documents/Student_Docs"
```

with:
```tsx
            placeholder={window.electronAPI?.platform === 'win32'
              ? 'C:\\Users\\username\\Documents\\Student_Docs'
              : '/Users/username/Documents/Student_Docs'}
```

**Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add desktop/src/pages/FolderSelection.tsx
git commit -m "fix: platform-aware folder placeholder path"
```

---

### Task 5: Add 'setup' to Screen type

**Files:**
- Modify: `desktop/src/types.ts:1-7`

**Step 1: Add setup to the Screen union**

In `desktop/src/types.ts`, replace lines 1-7:
```typescript
/** Screens in the wizard flow */
export type Screen =
  | 'folder_selection'
  | 'conversion_status'
  | 'document_review'
  | 'final_confirmation'
  | 'completion';
```

with:
```typescript
/** Screens in the wizard flow */
export type Screen =
  | 'setup'
  | 'folder_selection'
  | 'conversion_status'
  | 'document_review'
  | 'final_confirmation'
  | 'completion';
```

Do NOT add `'setup'` to the `SCREENS` array — it should not appear in the sidebar.

**Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors (or errors about missing `case 'setup'` in App.tsx, which we fix in Task 7)

**Step 3: Commit**

```bash
git add desktop/src/types.ts
git commit -m "feat: add setup screen to Screen type"
```

---

### Task 6: Create Setup screen component

**Files:**
- Create: `desktop/src/pages/Setup.tsx`

**Step 1: Create the component**

Create `desktop/src/pages/Setup.tsx`:

```tsx
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, RefreshCw, CheckCircle, ArrowRight, FileText } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import type { DependencyStatus } from '../types';

export default function Setup() {
  const navigateTo = useStore((s) => s.navigateTo);
  const [checking, setChecking] = useState(false);
  const [deps, setDeps] = useState<DependencyStatus | null>(null);
  const [allReady, setAllReady] = useState(false);

  const handleCheckAgain = async () => {
    setChecking(true);
    try {
      const result = await api.checkDependencies();
      setDeps(result);
      if (result.libreoffice_ok) {
        setAllReady(true);
        // Auto-advance after 2 seconds
        setTimeout(() => navigateTo('folder_selection'), 2000);
      }
    } catch {
      // Silently fail — the Check Again button stays available
    } finally {
      setChecking(false);
    }
  };

  const handleDownload = () => {
    window.electronAPI?.openExternal('https://www.libreoffice.org/download/download-libreoffice/');
  };

  if (allReady) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center justify-center min-h-[400px] space-y-6"
      >
        <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center">
          <CheckCircle size={32} className="text-emerald-600" />
        </div>
        <div className="text-center">
          <h2 className="text-2xl font-bold text-slate-800">You're All Set</h2>
          <p className="text-sm text-slate-400 mt-1">Everything is ready to go.</p>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2 text-emerald-700">
            <CheckCircle size={16} /> LibreOffice — Installed
          </div>
          <div className="flex items-center gap-2 text-emerald-700">
            <CheckCircle size={16} /> Tesseract OCR — Built-in
          </div>
        </div>
        <button
          onClick={() => navigateTo('folder_selection')}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          Get Started <ArrowRight size={16} />
        </button>
      </motion.div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Almost Ready</h2>
        <p className="text-sm text-slate-400 mt-1">One quick setup step before you start.</p>
      </div>

      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-amber-50 border border-amber-200 rounded-xl p-6 space-y-4"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
            <FileText size={20} className="text-amber-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-amber-900">Install LibreOffice</h3>
            <p className="text-sm text-amber-800 mt-1 leading-relaxed">
              LibreOffice is a free app that lets this tool read Word documents
              (.doc and .docx files). It takes a couple of minutes to install.
            </p>
          </div>
        </div>

        <button
          onClick={handleDownload}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium
                     bg-amber-600 text-white hover:bg-amber-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <Download size={16} /> Download LibreOffice
        </button>

        <p className="text-xs text-amber-700">
          After installing, click <span className="font-medium">Check Again</span> below — no need to restart this app.
        </p>
      </motion.section>

      {/* Status after checking */}
      <AnimatePresence>
        {deps && !deps.libreoffice_ok && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700"
          >
            LibreOffice was not detected. Make sure the installation is complete, then try again.
          </motion.div>
        )}
      </AnimatePresence>

      {/* Actions */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={() => navigateTo('folder_selection')}
          className="text-sm text-slate-400 hover:text-slate-600 transition-colors"
        >
          Skip for now — I only have PDFs
        </button>

        <button
          onClick={handleCheckAgain}
          disabled={checking}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 disabled:bg-slate-300
                     disabled:cursor-not-allowed shadow-sm hover:shadow transition-all btn-press"
        >
          <RefreshCw size={16} className={checking ? 'animate-spin' : ''} />
          {checking ? 'Checking...' : 'Check Again'}
        </button>
      </div>

      <p className="text-xs text-slate-400 text-center">
        LibreOffice is only needed for Word documents. If you only work with PDFs, you can skip this step.
      </p>
    </div>
  );
}
```

**Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors (or errors about App.tsx not importing Setup yet — fixed in Task 7)

**Step 3: Commit**

```bash
git add desktop/src/pages/Setup.tsx
git commit -m "feat: add Setup screen for first-run LibreOffice check"
```

---

### Task 7: Wire Setup screen into App.tsx

**Files:**
- Modify: `desktop/src/App.tsx`

**Step 1: Add import and dep check logic**

Replace the entire `desktop/src/App.tsx` with:

```tsx
import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import UpdateBanner from './components/UpdateBanner';
import { useStore } from './store';
import { useUpdater } from './hooks/useUpdater';
import { api } from './api';
import Setup from './pages/Setup';
import FolderSelection from './pages/FolderSelection';
import ConversionStatus from './pages/ConversionStatus';
import DocumentReview from './pages/DocumentReview';
import FinalConfirmation from './pages/FinalConfirmation';
import Completion from './pages/Completion';

function App() {
  const currentScreen = useStore((s) => s.currentScreen);
  const navigateTo = useStore((s) => s.navigateTo);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const { updateState, checkForUpdates, restartAndInstall, dismiss } = useUpdater();
  const [depsChecked, setDepsChecked] = useState(false);

  // On mount: check dependencies and redirect to setup if LibreOffice is missing
  useEffect(() => {
    api.checkDependencies()
      .then((deps) => {
        if (!deps.libreoffice_ok && currentScreen === 'folder_selection') {
          navigateTo('setup');
        }
      })
      .catch(() => {
        // Backend not ready yet — don't redirect, let the app load normally
      })
      .finally(() => setDepsChecked(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const renderScreen = () => {
    switch (currentScreen) {
      case 'setup':              return <Setup />;
      case 'folder_selection':   return <FolderSelection />;
      case 'conversion_status':  return <ConversionStatus />;
      case 'document_review':    return <DocumentReview />;
      case 'final_confirmation': return <FinalConfirmation />;
      case 'completion':         return <Completion />;
    }
  };

  // Don't render until dep check completes (avoids flash of folder_selection then redirect)
  if (!depsChecked) return null;

  return (
    <Layout updateState={updateState} onCheckForUpdates={checkForUpdates}>
      <UpdateBanner
        updateState={updateState}
        onRestart={restartAndInstall}
        onDismiss={dismiss}
      />

      {/* Global error toast */}
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-start justify-between">
          <p className="text-sm text-red-700">{error}</p>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs ml-4">
            Dismiss
          </button>
        </div>
      )}
      {renderScreen()}
    </Layout>
  );
}

export default App;
```

Key changes from original:
- Import `useEffect`, `useState`, `api`, and `Setup`
- `depsChecked` state prevents flash of wrong screen
- `useEffect` on mount checks deps and redirects to `setup` if LibreOffice is missing
- Only redirects if currently on `folder_selection` (so "Skip for Now" isn't overridden)
- Added `case 'setup'` to the switch

**Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add desktop/src/App.tsx
git commit -m "feat: wire Setup screen into App with dep check on mount"
```

---

### Task 8: Make "Check for Updates" more prominent in About modal

**Files:**
- Modify: `desktop/src/components/AboutModal.tsx:186-198`

**Step 1: Replace the version/update section**

In `desktop/src/components/AboutModal.tsx`, replace lines 186-198 (the `<section>` with version and check button):

```tsx
      <section className="flex items-center justify-between">
        <p className="text-[10px] text-slate-400 uppercase tracking-widest">
          {appVersion ? `v${appVersion}` : 'v—'}
        </p>
        <button
          onClick={onCheckForUpdates}
          disabled={checkButtonDisabled}
          className="flex items-center gap-1.5 text-xs text-primary-500 hover:text-primary-600 disabled:text-slate-300 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={11} className={updateState.status === 'checking' ? 'animate-spin' : ''} />
          {checkButtonLabel()}
        </button>
      </section>
```

with:

```tsx
      <section className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">
            Version <span className="font-medium text-slate-700">{appVersion || '—'}</span>
          </p>
          <button
            onClick={onCheckForUpdates}
            disabled={checkButtonDisabled}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium
                       bg-primary-600 text-white hover:bg-primary-700 disabled:bg-slate-200
                       disabled:text-slate-400 disabled:cursor-not-allowed shadow-sm transition-all btn-press"
          >
            <RefreshCw size={13} className={updateState.status === 'checking' ? 'animate-spin' : ''} />
            {checkButtonLabel()}
          </button>
        </div>
      </section>
```

**Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add desktop/src/components/AboutModal.tsx
git commit -m "feat: make Check for Updates button more prominent in About modal"
```

---

### Task 9: Smoke test the full flow

**Step 1: Run the desktop app in dev mode**

Run: `cd desktop && npm run dev:electron`

**Step 2: Verify the following manually**

1. If LibreOffice is NOT installed: setup screen appears with "Almost Ready" heading, download button, Check Again button, and Skip link.
2. Click "Skip for now" → folder_selection loads normally.
3. Close and reopen app → setup screen appears again (not permanently dismissed).
4. If LibreOffice IS installed: app goes straight to folder_selection (no setup screen flash).
5. Folder input placeholder shows Windows-style path on Windows, Mac-style on Mac.
6. Open About modal → "Check for Updates" is a prominent blue button, not a tiny link.
7. Click "Check for Updates" → shows "Checking..." then result.

**Step 3: Type-check and lint**

Run: `cd desktop && npx tsc --noEmit && npx eslint .`
Expected: No errors

**Step 4: Run Python tests**

Run: `pytest tests/test_binary_resolver.py -v`
Expected: All PASS

**Step 5: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore: lint fixes"
```
