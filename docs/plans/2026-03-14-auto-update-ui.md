# Auto-Update UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface the already-wired auto-updater to non-tech-savvy users — every launch silently checks for updates, downloads in the background, and shows a clear friendly banner when a restart will install the update.

**Architecture:** A custom React hook (`useUpdater`) owns all update state. An `UpdateBanner` component renders in `App.tsx` above the screen content. The About modal gains a live version number and a "Check for Updates" button. All new IPC channels follow the existing pattern in `main.cjs` → `preload.cjs` → `electron.d.ts`.

**Tech Stack:** Electron `autoUpdater` (electron-updater v6), React 19, Zustand (not used for update state — update state is local to the hook), Tailwind CSS v4, Framer Motion, Lucide icons.

---

## Context You Must Read First

Before touching any file, read these:
- `desktop/electron/main.cjs` — existing autoUpdater setup is at lines 128–154. IPC handlers at 156–169.
- `desktop/electron/preload.cjs` — all 15 lines. Understand `contextBridge` pattern.
- `desktop/src/electron.d.ts` — type declarations for `window.electronAPI`.
- `desktop/src/App.tsx` — where the banner will be rendered.
- `desktop/src/components/AboutModal.tsx` — `TabAbout` component at line 128 needs version + button.
- `desktop/src/components/Layout.tsx` — understand where content lives so banner placement is clear.

**Styling convention:** Tailwind utility classes only. Use `text-primary-600`, `bg-primary-50` etc. for brand colour. Look at existing components for patterns — e.g. the error toast in `App.tsx:33` for banner structure reference.

---

## Anticipated Problems (Read Before Starting)

**P1 — Listener accumulation:** The existing `onUpdateAvailable` and `onUpdateDownloaded` in `preload.cjs` use `ipcRenderer.on`, which adds a new listener every time the React component calls it. If `App.tsx` re-renders, listeners stack up. Fix: return a cleanup function from each `on*` method so React's `useEffect` can call it. See Task 1.

**P2 — "Check for Updates" feedback loop:** If the user clicks "Check for Updates" and there's no update, nothing happens with the current code — `update-not-available` fires but isn't forwarded to the renderer. Without feedback, non-tech users will think the button is broken. Fix: forward the event and show "You're up to date." See Task 2.

**P3 — Hardcoded version in About modal:** `AboutModal.tsx:152` shows `v0.1.0` hardcoded. This will never update. Fix: expose `app.getVersion()` via IPC. See Task 2.

**P4 — Update interrupted mid-job:** A user might be halfway through redacting documents when the update banner appears. Clicking "Restart Now" will kill the app mid-process. The banner must appear but not interrupt — the restart button should always be opt-in, never forced. ✅ Already handled by `autoInstallOnAppQuit = true` — if they ignore the banner and just close normally, the update installs. The banner just gives them an explicit choice.

**P5 — No internet / network error:** `autoUpdater.checkForUpdates()` throws if there's no internet. Currently caught silently in `main.cjs:153`. The manual "Check for Updates" button also needs to handle this gracefully — show "Couldn't check for updates. Are you connected to the internet?" not a raw error. See Task 4.

**P6 — Unsigned app + SmartScreen:** The update installer is not code-signed. When `quitAndInstall()` runs the downloaded `.exe`, Windows SmartScreen may block it with a "Windows protected your PC" dialog. This is a UX problem but not a code problem — document it in a code comment. Users need to click "More info → Run anyway". Nothing to fix in code, but acknowledge it.

**P7 — GitHub repo must be public for updates to work without a token:** `electron-updater` fetches `latest.yml` from GitHub Releases. If the repo is private, the GH_TOKEN env var must be set. This is a deployment concern, not a code concern. Add a comment in `main.cjs` noting this.

---

## Task 1 — Fix Listener Cleanup in Preload

**Why first:** Every subsequent task depends on the React hooks calling `on*` correctly. Fix the foundation before building on it.

**Files:**
- Modify: `desktop/electron/preload.cjs` (full file, 15 lines)
- Modify: `desktop/src/electron.d.ts` (full file)

**Step 1: Update preload.cjs**

Replace the entire file contents with:

```js
/**
 * Electron Preload Script
 * Exposes minimal APIs to the renderer process.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Returns a cleanup function — call it in useEffect's return to avoid listener buildup
  onUpdateAvailable: (cb) => {
    const handler = (_event, version) => cb(version);
    ipcRenderer.on('update-available', handler);
    return () => ipcRenderer.removeListener('update-available', handler);
  },
  onUpdateDownloaded: (cb) => {
    const handler = () => cb();
    ipcRenderer.on('update-downloaded', handler);
    return () => ipcRenderer.removeListener('update-downloaded', handler);
  },
  onUpdateNotAvailable: (cb) => {
    const handler = () => cb();
    ipcRenderer.on('update-not-available', handler);
    return () => ipcRenderer.removeListener('update-not-available', handler);
  },
  onDownloadProgress: (cb) => {
    const handler = (_event, percent) => cb(percent);
    ipcRenderer.on('download-progress', handler);
    return () => ipcRenderer.removeListener('download-progress', handler);
  },

  restartAndInstall: () => ipcRenderer.invoke('restart-and-install'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
});
```

**Step 2: Update electron.d.ts**

Replace the entire file with:

```ts
export {};

declare global {
  interface Window {
    electronAPI?: {
      platform: string;
      isElectron: boolean;
      selectFolder: () => Promise<string | null>;
      openExternal: (url: string) => Promise<void>;

      // Each returns a cleanup function for useEffect
      onUpdateAvailable: (cb: (version: string) => void) => () => void;
      onUpdateDownloaded: (cb: () => void) => () => void;
      onUpdateNotAvailable: (cb: () => void) => () => void;
      onDownloadProgress: (cb: (percent: number) => void) => () => void;

      restartAndInstall: () => Promise<void>;
      checkForUpdates: () => Promise<void>;
      getAppVersion: () => Promise<string>;
    };
  }
}
```

**Step 3: Verify TypeScript compiles**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 4: Commit**

```bash
git add desktop/electron/preload.cjs desktop/src/electron.d.ts
git commit -m "fix: add listener cleanup to preload IPC bindings"
```

---

## Task 2 — Add New IPC Handlers in main.cjs

**Files:**
- Modify: `desktop/electron/main.cjs`

**Step 1: Add handlers in the IPC section (after line 169, before the app lifecycle section)**

Add these four handlers after the existing `open-external` handler:

```js
ipcMain.handle('restart-and-install', () => {
  autoUpdater.quitAndInstall();
});

ipcMain.handle('check-for-updates', async () => {
  // In dev, autoUpdater is not set up — ignore silently
  if (isDev) return;
  await autoUpdater.checkForUpdates().catch(() => {});
});

ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});
```

**Step 2: Forward `update-not-available` and `download-progress` events in `setupAutoUpdater()`**

In the existing `setupAutoUpdater()` function (around line 130), add two new event handlers after the existing ones:

```js
autoUpdater.on('update-not-available', () => {
  console.log('No update available');
  if (mainWindow) {
    mainWindow.webContents.send('update-not-available');
  }
});

autoUpdater.on('download-progress', (progress) => {
  if (mainWindow) {
    mainWindow.webContents.send('download-progress', Math.round(progress.percent));
  }
});
```

Also add a comment near the `setTimeout` line noting the GitHub public repo requirement:

```js
// NOTE: For updates to work, the GitHub repo must be public, or GH_TOKEN must be
// set in the environment. See package.json "publish" config for repo details.
setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 10000);
```

**Step 3: Verify the app still starts (no syntax errors)**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 4: Commit**

```bash
git add desktop/electron/main.cjs
git commit -m "feat: add restart-and-install, check-for-updates, and get-app-version IPC handlers"
```

---

## Task 3 — Create useUpdater Hook

**Why a hook:** Keeps all update state in one place. `App.tsx` and `AboutModal.tsx` both need update state — the hook is the single source of truth. Don't put this in Zustand; it's ephemeral UI state that doesn't survive a reset.

**Files:**
- Create: `desktop/src/hooks/useUpdater.ts`

**Step 1: Create the file**

```ts
/**
 * useUpdater — manages auto-update state for the lifetime of the app.
 *
 * State machine:
 *   idle → checking → up-to-date   (no update found)
 *          checking → downloading  (update found, autoDownload=true)
 *                     downloading → ready  (downloaded, awaiting restart)
 *
 * All transitions are driven by IPC events from the main process.
 * The manual checkForUpdates() call can move idle → checking at any time.
 */

import { useState, useEffect, useCallback } from 'react';

export type UpdateState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'up-to-date' }
  | { status: 'downloading'; version: string; percent: number }
  | { status: 'ready'; version: string }
  | { status: 'error'; message: string };

export function useUpdater() {
  const [updateState, setUpdateState] = useState<UpdateState>({ status: 'idle' });
  const isElectron = !!window.electronAPI;

  useEffect(() => {
    if (!isElectron) return;

    const cleanupAvailable = window.electronAPI!.onUpdateAvailable((version) => {
      setUpdateState({ status: 'downloading', version, percent: 0 });
    });

    const cleanupProgress = window.electronAPI!.onDownloadProgress((percent) => {
      setUpdateState((prev) =>
        prev.status === 'downloading' ? { ...prev, percent } : prev
      );
    });

    const cleanupDownloaded = window.electronAPI!.onUpdateDownloaded(() => {
      setUpdateState((prev) =>
        prev.status === 'downloading'
          ? { status: 'ready', version: prev.version }
          : { status: 'ready', version: '' }
      );
    });

    const cleanupNotAvailable = window.electronAPI!.onUpdateNotAvailable(() => {
      setUpdateState({ status: 'up-to-date' });
      // Reset to idle after 5 seconds so the "up to date" message fades away
      setTimeout(() => setUpdateState({ status: 'idle' }), 5000);
    });

    return () => {
      cleanupAvailable();
      cleanupProgress();
      cleanupDownloaded();
      cleanupNotAvailable();
    };
  }, [isElectron]);

  const checkForUpdates = useCallback(async () => {
    if (!isElectron) return;
    setUpdateState({ status: 'checking' });
    try {
      await window.electronAPI!.checkForUpdates();
      // State transitions from here are driven by IPC events above.
      // If no event fires within 8 seconds, assume network error.
      setTimeout(() => {
        setUpdateState((prev) => {
          if (prev.status === 'checking') {
            return { status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" };
          }
          return prev;
        });
      }, 8000);
    } catch {
      setUpdateState({ status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" });
    }
  }, [isElectron]);

  const restartAndInstall = useCallback(() => {
    window.electronAPI?.restartAndInstall();
  }, []);

  const dismiss = useCallback(() => {
    setUpdateState({ status: 'idle' });
  }, []);

  return { updateState, checkForUpdates, restartAndInstall, dismiss };
}
```

**Step 2: Verify TypeScript**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 3: Commit**

```bash
git add desktop/src/hooks/useUpdater.ts
git commit -m "feat: add useUpdater hook for auto-update state machine"
```

---

## Task 4 — Create UpdateBanner Component

**Design intent:** Non-tech-savvy users. Plain English. No jargon. The banner appears at the top of the main content area and stays until dismissed or acted on. It never blocks the workflow.

**Visual states:**
- `downloading` → muted blue info bar: "A new version (v1.1.0) is downloading… 42%"
- `ready` → green bar with Restart button: "Update ready — v1.1.0 is downloaded. Restart to install it." [Restart Now] [Later]
- `up-to-date` → brief green bar: "You're up to date." (auto-dismisses in 5s)
- `error` → amber bar: "Couldn't check for updates. Are you connected to the internet?" [Dismiss]

**Files:**
- Create: `desktop/src/components/UpdateBanner.tsx`

**Step 1: Create the component**

```tsx
import { motion, AnimatePresence } from 'framer-motion';
import { Download, CheckCircle, AlertTriangle, RefreshCw } from 'lucide-react';
import type { UpdateState } from '../hooks/useUpdater';

interface UpdateBannerProps {
  updateState: UpdateState;
  onRestart: () => void;
  onDismiss: () => void;
}

export default function UpdateBanner({ updateState, onRestart, onDismiss }: UpdateBannerProps) {
  const visible =
    updateState.status === 'downloading' ||
    updateState.status === 'ready' ||
    updateState.status === 'up-to-date' ||
    updateState.status === 'error';

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2 }}
          className={`mb-4 rounded-lg px-4 py-3 flex items-center justify-between gap-4 text-sm ${
            updateState.status === 'ready'
              ? 'bg-emerald-50 border border-emerald-200'
              : updateState.status === 'up-to-date'
              ? 'bg-emerald-50 border border-emerald-200'
              : updateState.status === 'error'
              ? 'bg-amber-50 border border-amber-200'
              : 'bg-blue-50 border border-blue-200'
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            {updateState.status === 'downloading' && (
              <Download size={15} className="text-blue-500 shrink-0" />
            )}
            {updateState.status === 'ready' && (
              <CheckCircle size={15} className="text-emerald-500 shrink-0" />
            )}
            {updateState.status === 'up-to-date' && (
              <CheckCircle size={15} className="text-emerald-500 shrink-0" />
            )}
            {updateState.status === 'error' && (
              <AlertTriangle size={15} className="text-amber-500 shrink-0" />
            )}

            <span className={`truncate ${
              updateState.status === 'error' ? 'text-amber-700' :
              updateState.status === 'downloading' ? 'text-blue-700' : 'text-emerald-700'
            }`}>
              {updateState.status === 'downloading' &&
                `Downloading update${updateState.version ? ` v${updateState.version}` : ''}…${
                  updateState.percent > 0 ? ` ${updateState.percent}%` : ''
                }`}
              {updateState.status === 'ready' &&
                `Update ready${updateState.version ? ` — v${updateState.version}` : ''}. Restart the app to install it.`}
              {updateState.status === 'up-to-date' && "You're up to date."}
              {updateState.status === 'error' && updateState.message}
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {updateState.status === 'ready' && (
              <button
                onClick={onRestart}
                className="px-3 py-1 rounded-md bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-colors"
              >
                Restart Now
              </button>
            )}
            {(updateState.status === 'ready' || updateState.status === 'error') && (
              <button
                onClick={onDismiss}
                className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
              >
                {updateState.status === 'ready' ? 'Later' : 'Dismiss'}
              </button>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

**Step 2: Verify TypeScript**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 3: Commit**

```bash
git add desktop/src/components/UpdateBanner.tsx
git commit -m "feat: add UpdateBanner component for all update states"
```

---

## Task 5 — Wire UpdateBanner into App.tsx

**Files:**
- Modify: `desktop/src/App.tsx`

**Step 1: Replace App.tsx contents**

```tsx
import Layout from './components/Layout';
import UpdateBanner from './components/UpdateBanner';
import { useStore } from './store';
import { useUpdater } from './hooks/useUpdater';
import FolderSelection from './pages/FolderSelection';
import ConversionStatus from './pages/ConversionStatus';
import DocumentReview from './pages/DocumentReview';
import FinalConfirmation from './pages/FinalConfirmation';
import Completion from './pages/Completion';

function App() {
  const currentScreen = useStore((s) => s.currentScreen);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const { updateState, restartAndInstall, dismiss } = useUpdater();

  const renderScreen = () => {
    switch (currentScreen) {
      case 'folder_selection':   return <FolderSelection />;
      case 'conversion_status':  return <ConversionStatus />;
      case 'document_review':    return <DocumentReview />;
      case 'final_confirmation': return <FinalConfirmation />;
      case 'completion':         return <Completion />;
    }
  };

  return (
    <Layout>
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

**Step 2: Verify TypeScript**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 3: Commit**

```bash
git add desktop/src/App.tsx
git commit -m "feat: wire UpdateBanner into App.tsx"
```

---

## Task 6 — Update AboutModal with Live Version + Check for Updates Button

**What changes in `AboutModal.tsx`:**
- `TabAbout` receives `appVersion` and `updateState` props
- Version display changes from hardcoded `v0.1.0` to the live version
- A "Check for Updates" button is added below the version
- The button shows live feedback from `updateState`

**Files:**
- Modify: `desktop/src/components/AboutModal.tsx`
- Modify: `desktop/src/components/Layout.tsx` (to pass props down — see below)

Wait — `AboutModal` is opened from the Sidebar, not Layout. Check where it's opened.

**Step 1: Find where AboutModal is rendered**

```bash
grep -rn "AboutModal" "F:/antigravity/doc redactor/desktop/src/" --include="*.tsx"
```

Note the file path. It will likely be `Sidebar.tsx`. Read that file before proceeding.

**Step 2: Update `AboutModalProps` interface and `TabAbout` signature**

At the top of `AboutModal.tsx`, add the import:

```tsx
import { useEffect, useState } from 'react';
import type { UpdateState } from '../hooks/useUpdater';
```

Update `AboutModalProps`:

```tsx
interface AboutModalProps {
  open: boolean;
  onClose: () => void;
  onShowWalkthrough: () => void;
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}
```

Update the `TabAbout` props interface:

```tsx
function TabAbout({
  openLink,
  updateState,
  onCheckForUpdates,
}: {
  openLink: (url: string) => void;
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}) {
```

**Step 3: Add live version + update button to `TabAbout`**

Replace the entire `TabAbout` function body. The version section (currently just `<p className="text-[10px]...">v0.1.0</p>`) becomes:

```tsx
function TabAbout({ openLink, updateState, onCheckForUpdates }: {
  openLink: (url: string) => void;
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}) {
  const [appVersion, setAppVersion] = useState<string>('');

  useEffect(() => {
    window.electronAPI?.getAppVersion().then(setAppVersion).catch(() => {});
  }, []);

  const checkButtonLabel = () => {
    switch (updateState.status) {
      case 'checking':    return 'Checking…';
      case 'up-to-date':  return 'You\'re up to date ✓';
      case 'downloading': return `Downloading… ${updateState.percent > 0 ? updateState.percent + '%' : ''}`;
      case 'ready':       return 'Update ready — see banner above';
      case 'error':       return 'Check failed — try again';
      default:            return 'Check for Updates';
    }
  };

  const checkButtonDisabled =
    updateState.status === 'checking' ||
    updateState.status === 'downloading' ||
    updateState.status === 'ready';

  return (
    <div className="space-y-5">
      <section>
        <p className="text-sm text-slate-600">
          Developed by <span className="font-medium text-slate-800">David Armstrong</span>
        </p>
        <button
          onClick={() => openLink('https://github.com/mrdavearms/student-doc-redactor')}
          className="flex items-center gap-1.5 mt-1.5 text-xs text-primary-500 hover:text-primary-600 transition-colors"
        >
          <ExternalLink size={11} /> View on GitHub
        </button>
      </section>
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">What This App Does</h3>
        <p className="text-sm text-slate-500 leading-relaxed">
          Finds and removes personally identifiable information from student assessment
          documents — names, phone numbers, emails, addresses, and more. Built for teachers
          and school psychologists who need to share reports while protecting student privacy.
          All processing happens locally on your computer.
        </p>
      </section>
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
    </div>
  );
}
```

Also add `RefreshCw` to the existing lucide import line at the top of the file.

**Step 4: Pass the new props through in the `AboutModal` component**

Update the `AboutModal` function signature and the `TabAbout` render call:

```tsx
export default function AboutModal({ open, onClose, onShowWalkthrough, updateState, onCheckForUpdates }: AboutModalProps) {
  // ... existing state ...

  return (
    // ... existing JSX ...
    {activeTab === 'about' && (
      <TabAbout
        openLink={openLink}
        updateState={updateState}
        onCheckForUpdates={onCheckForUpdates}
      />
    )}
    // ...
  );
}
```

**Step 5: Find where AboutModal is rendered and pass new props**

After Step 1 reveals the file (likely `Sidebar.tsx`), import `useUpdater` there and pass `updateState` and `checkForUpdates` down:

```tsx
// In whichever file renders <AboutModal>
import { useUpdater } from '../hooks/useUpdater';

// Inside the component:
const { updateState, checkForUpdates } = useUpdater();

// In JSX:
<AboutModal
  open={showAbout}
  onClose={() => setShowAbout(false)}
  onShowWalkthrough={onShowWalkthrough}
  updateState={updateState}
  onCheckForUpdates={checkForUpdates}
/>
```

**⚠️ Important:** `useUpdater` must only be called once in the component tree — if both `App.tsx` and `Sidebar.tsx` call `useUpdater()`, they get separate state instances and won't stay in sync. The fix is to call `useUpdater()` in `App.tsx` only and pass `updateState`, `checkForUpdates`, `restartAndInstall`, and `dismiss` down as props — or use React context.

**Simplest solution:** Pass the updater values down via props from `App.tsx` → `Layout.tsx` → `Sidebar.tsx` → `AboutModal.tsx`. Or use a tiny React context. Use props if the chain is shallow (≤3 hops), context if deeper.

Check the actual component tree before deciding. Read `Sidebar.tsx` first.

**Step 6: Verify TypeScript**

```bash
cd "F:/antigravity/doc redactor/desktop"
npx tsc --noEmit
```
Expected: no errors.

**Step 7: Commit**

```bash
git add desktop/src/components/AboutModal.tsx desktop/src/components/Sidebar.tsx
git commit -m "feat: add live version number and Check for Updates to About modal"
```

---

## Task 7 — Build and Manual Smoke Test

This is not a unit test — the auto-updater cannot be unit tested without a real GitHub release. This is a manual checklist.

**Step 1: Build the app**

```bash
cd "F:/antigravity/doc redactor/desktop"
npm run dist:win
```
Expected: `release/Redaction Tool Setup 1.0.0.exe` produced, exit 0.

**Step 2: Install and run**

Run the installer. Launch "Redaction Tool" from the Start menu.

**Step 3: Manual checklist**

- [ ] App opens without errors
- [ ] No update banner visible on first launch (no update available in GitHub Releases yet)
- [ ] Open About modal → version shows `v1.0.0` (not `v0.1.0`)
- [ ] Click "Check for Updates" → button shows "Checking…" with spinning icon
- [ ] After ~8 seconds with no update found → "Couldn't check" appears (if no release posted) OR "You're up to date" (if a release exists)
- [ ] No duplicate banners if About modal is opened and closed multiple times

**Step 4: Simulate the download-ready state (dev mode test)**

To test the banner UI without a real update, temporarily add this to `App.tsx` after `useUpdater()` to force the state:

```tsx
// TEMP — remove before committing
useEffect(() => {
  setTimeout(() => setUpdateStateForTesting({ status: 'ready', version: '1.1.0' }), 3000);
}, []);
```

Actually — because state is encapsulated in the hook, the cleanest way to test the banner visually is:

In `useUpdater.ts`, add a dev shortcut — if `?devUpdate=1` is in the URL, set state to `ready`:

```ts
// DEV ONLY — in the useEffect in useUpdater.ts
if (process.env.NODE_ENV === 'development' && window.location.search.includes('devUpdate=ready')) {
  setUpdateState({ status: 'ready', version: '9.9.9' });
  return;
}
```

Then in dev mode: open `http://localhost:5173?devUpdate=ready` to see the banner.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete auto-update UI — banner, About modal version, check-for-updates button"
```

---

## What's Not In This Plan (Intentional)

- **Code signing:** Required to stop SmartScreen blocking the update installer. This is a separate task involving an EV certificate or Microsoft Trusted Root program. Out of scope for now.
- **Release workflow trigger:** The GitHub Actions `.github/workflows/release.yml` already handles publishing when you push a `v*` tag. No changes needed there.
- **Linux support:** Not in scope (README confirms macOS + Windows only).
- **Rollback:** If a bad update ships, the only recovery is to reinstall. Out of scope.
