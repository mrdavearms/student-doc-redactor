# Resilience and Trust Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the six fixes specified in `docs/superpowers/specs/2026-05-07-resilience-and-trust-improvements-design.md` to eliminate user-visible defects that erode trust in the Bulk Redaction Tool desktop app.

**Architecture:** Each phase is independently testable and produces a commit-mergeable change. Phase 0 adds the test runner. Phase 1 must precede Phase 3 (Phase 3 imports `BackendUnreachableError` from Phase 1). Phases 2, 4, and 5 are independent of all others. Manual smoke verification is done after the full series merges to `test`.

**Tech Stack:** TypeScript, React 19, Zustand, Electron, FastAPI, Pydantic, Vitest (added in Phase 0).

---

## Spec reference

Read the spec first: `docs/superpowers/specs/2026-05-07-resilience-and-trust-improvements-design.md`. The plan below is the executable form of that spec; if you find any contradiction, the spec is authoritative.

## Branch

All work happens on the worktree branch `claude/admiring-blackwell-f6b062`. The repo's parent branch is `test`. Do NOT merge to `main` until all phases pass smoke verification.

---

## Phase 0: Add Vitest test runner

The desktop app currently has no test framework. Phase 3 needs one for the error-message mapper unit tests. This phase adds Vitest with no other behavioural changes.

### Task 0.1: Install Vitest

**Files:**
- Modify: `desktop/package.json`

- [ ] **Step 1: Install Vitest as a dev dependency**

Run from the repo root:
```bash
cd desktop && npm install --save-dev vitest@^2.1.0
```

Expected: `package.json` has `"vitest": "^2.1.0"` under `devDependencies`. `package-lock.json` updated.

- [ ] **Step 2: Add the `test` script to `package.json`**

In `desktop/package.json`, add to the `scripts` block (between `lint` and `preview`):

```json
"test": "vitest run",
"test:watch": "vitest",
```

- [ ] **Step 3: Verify Vitest runs (with no tests yet)**

Run from `desktop/`:
```bash
npm test
```

Expected: Vitest exits 0 with "No test files found" or similar. This confirms the runner works.

- [ ] **Step 4: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/package.json desktop/package-lock.json
git commit -m "chore: add Vitest test runner

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 1: Backend-down detection (Spec Section 1)

Distinguish network errors from HTTP errors in the API client; surface a banner when the backend is unreachable; correct the false-negative folder validation message.

### Task 1.1: Add `BackendUnreachableError` and distinguish error types in `api.ts`

**Files:**
- Modify: `desktop/src/api.ts`

- [ ] **Step 1: Replace the `request` function with the network-aware version**

Open `desktop/src/api.ts`. At the top, after the `BASE` constant, add the error class. Replace the existing `request` function with the new implementation:

```ts
export class BackendUnreachableError extends Error {
  constructor() {
    super('Backend not reachable');
    this.name = 'BackendUnreachableError';
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch (e: any) {
    if (e?.name === 'AbortError') throw e;
    throw new BackendUnreachableError();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Run typecheck**

Run from `desktop/`:
```bash
npm run build
```

Expected: build completes without TS errors. (If errors mention `BackendUnreachableError`, ensure it's `export`ed.)

### Task 1.2: Add `backendReachable` to the Zustand store

**Files:**
- Modify: `desktop/src/store.ts`

- [ ] **Step 1: Add the field and setter to the `AppState` interface**

In `desktop/src/store.ts`, find the error-state block and add a backend-reachable block immediately after it:

```ts
  // Error state
  error: string | null;
  setError: (error: string | null) => void;

  // Backend reachability (false ⇒ show banner, start polling)
  backendReachable: boolean;
  setBackendReachable: (reachable: boolean) => void;
```

- [ ] **Step 2: Add the field to `initialState`**

Add `backendReachable: true,` next to `error: null,` in the `initialState` object.

- [ ] **Step 3: Add the setter implementation**

In the `create<AppState>((set) => ({` body, after the `setError` line, add:

```ts
  setBackendReachable: (reachable) => set({ backendReachable: reachable }),
```

- [ ] **Step 4: Verify typecheck**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 1.3: Add the backend-down banner and health polling to `App.tsx`

**Files:**
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Add imports**

At the top of `desktop/src/App.tsx`, add to the existing imports:

```tsx
import { useEffect, useState } from 'react';
// (existing imports unchanged)
import { api, BackendUnreachableError } from './api';
```

(`useEffect`/`useState` are already imported — only `BackendUnreachableError` is new.)

- [ ] **Step 2: Pull `backendReachable` and its setter from the store**

In the `App` function, alongside the existing `useStore` selectors:

```tsx
const backendReachable = useStore((s) => s.backendReachable);
const setBackendReachable = useStore((s) => s.setBackendReachable);
```

- [ ] **Step 3: Add a polling effect that runs only while the backend is unreachable**

Add this `useEffect` immediately after the existing dependency-check `useEffect` in `App.tsx`:

```tsx
// Poll /api/health every 5s while the backend is unreachable; clear flag on recovery.
useEffect(() => {
  if (backendReachable) return;
  const interval = setInterval(async () => {
    try {
      await api.health();
      setBackendReachable(true);
    } catch {
      // Still down; keep polling
    }
  }, 5000);
  return () => clearInterval(interval);
}, [backendReachable, setBackendReachable]);
```

- [ ] **Step 4: Update the existing dep-check effect to flip `backendReachable` on `BackendUnreachableError`**

Replace the existing dep-check `useEffect` body with:

```tsx
useEffect(() => {
  api.checkDependencies()
    .then((deps) => {
      if (!deps.libreoffice_ok && currentScreen === 'folder_selection') {
        navigateTo('setup');
      }
    })
    .catch((err) => {
      if (err instanceof BackendUnreachableError) {
        setBackendReachable(false);
      } else {
        console.warn('Dep check failed:', err.message);
      }
    })
    .finally(() => setDepsChecked(true));
}, []); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 5: Render the banner above the existing error toast**

In the `return` block of `App`, immediately after `<UpdateBanner ... />` and before the existing `{error && (...)}` toast block, insert:

```tsx
{!backendReachable && (
  <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
    <p className="text-sm text-amber-800">
      The redaction engine isn&apos;t responding. Please wait a moment, or restart the app if this persists.
    </p>
  </div>
)}
```

- [ ] **Step 6: Verify typecheck**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 1.4: Update `FolderSelection` to handle `BackendUnreachableError` distinctly

**Files:**
- Modify: `desktop/src/pages/FolderSelection.tsx`

- [ ] **Step 1: Add the import**

At the top of `desktop/src/pages/FolderSelection.tsx`:

```tsx
import { api, BackendUnreachableError } from '../api';
```

- [ ] **Step 2: Replace the `validateFolder` catch block**

Find the existing `validateFolder` callback. Replace its `try/catch` body (keep the function signature and `setValidating` calls):

```ts
const validateFolder = useCallback(async (path: string) => {
  setFolderPath(path);
  if (!path.trim()) {
    setFolderValid(false);
    return;
  }
  setValidating(true);
  try {
    const res = await api.validateFolder(path.trim());
    setFolderValid(res.exists && res.is_directory);
  } catch (e) {
    if (e instanceof BackendUnreachableError) {
      useStore.getState().setBackendReachable(false);
      // Leave folderValid as-is so the false-negative message doesn't render.
    } else {
      setFolderValid(false);
    }
  } finally {
    setValidating(false);
  }
}, [setFolderPath, setFolderValid]);
```

(`useStore` is already imported in this file as the destructuring source — keep that import; we use `useStore.getState()` here because we're inside a callback and want to bypass subscription.)

- [ ] **Step 3: Verify typecheck**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 1.5: Commit Phase 1

- [ ] **Step 1: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/src/api.ts desktop/src/store.ts desktop/src/App.tsx desktop/src/pages/FolderSelection.tsx
git commit -m "feat(desktop): detect backend unavailability and surface clear banner

Distinguishes network errors from HTTP errors in api.ts via
BackendUnreachableError. App-level banner appears when the backend is
unreachable; a 5-second poll on /api/health clears it once the backend
recovers. FolderSelection no longer reports 'Folder not found' when the
real cause is a dead backend.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 2: React error boundary (Spec Section 2)

Catch render-time exceptions; show a recovery screen; persist errors to a local log file via a new IPC method.

### Task 2.1: Add the `log-error` IPC handler in Electron main

**Files:**
- Modify: `desktop/electron/main.cjs`

- [ ] **Step 1: Add the file-append handler**

Open `desktop/electron/main.cjs`. Find the existing `ipcMain.handle('get-app-version', ...)` block. Immediately after it, add:

```js
ipcMain.handle('log-error', async (_event, payload) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const logPath = path.join(app.getPath('userData'), 'error.log');
    const line = JSON.stringify({ ...payload, recordedAt: new Date().toISOString() }) + '\n';
    fs.appendFileSync(logPath, line, 'utf8');
  } catch (err) {
    console.error('Failed to write error log:', err);
  }
});
```

(`app` and `ipcMain` are already imported at the top of the file.)

### Task 2.2: Expose `logError` via preload

**Files:**
- Modify: `desktop/electron/preload.cjs`

- [ ] **Step 1: Add `logError` to the `electronAPI` bridge**

In `desktop/electron/preload.cjs`, inside the `contextBridge.exposeInMainWorld('electronAPI', { ... })` object, after `getAppVersion: () => ipcRenderer.invoke('get-app-version'),`, add:

```js
  logError: (payload) => ipcRenderer.invoke('log-error', payload),
```

### Task 2.3: Type the new IPC method in `electron.d.ts`

**Files:**
- Modify: `desktop/src/electron.d.ts`

- [ ] **Step 1: Add the `logError` type**

Inside the `electronAPI?: { ... }` block, add (alongside `getAppVersion`):

```ts
      logError: (payload: {
        message: string;
        stack?: string;
        componentStack?: string;
        timestamp: string;
      }) => Promise<void>;
```

### Task 2.4: Create `ErrorFallback` component

**Files:**
- Create: `desktop/src/components/ErrorFallback.tsx`

- [ ] **Step 1: Write the component**

Create `desktop/src/components/ErrorFallback.tsx` with:

```tsx
import { useState } from 'react';
import { AlertCircle, ChevronDown, ChevronUp, RotateCcw } from 'lucide-react';

interface Props {
  error: Error;
  onReset: () => void;
}

export default function ErrorFallback({ error, onReset }: Props) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8">
      <div className="max-w-md w-full bg-white rounded-xl border border-slate-200 p-8 text-center">
        <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
          <AlertCircle size={28} className="text-red-600" />
        </div>
        <h1 className="text-xl font-semibold text-slate-800 mb-2">Something went wrong</h1>
        <p className="text-sm text-slate-500 mb-6">
          The app hit an unexpected problem. Your files are unaffected. Click below to start over.
        </p>

        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all"
        >
          <RotateCcw size={16} /> Start over
        </button>

        <button
          onClick={() => setShowDetails((v) => !v)}
          className="mt-4 mx-auto flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600"
        >
          {showDetails ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          Technical details
        </button>

        {showDetails && (
          <pre className="mt-3 text-[11px] text-left bg-slate-50 rounded-lg p-3 overflow-x-auto text-slate-600 whitespace-pre-wrap">
            {error.message}
            {error.stack ? `\n\n${error.stack}` : ''}
          </pre>
        )}
      </div>
    </div>
  );
}
```

### Task 2.5: Create `ErrorBoundary` component

**Files:**
- Create: `desktop/src/components/ErrorBoundary.tsx`

- [ ] **Step 1: Write the component**

Create `desktop/src/components/ErrorBoundary.tsx` with:

```tsx
import React from 'react';
import ErrorFallback from './ErrorFallback';
import { useStore } from '../store';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Render error:', error, info);
    window.electronAPI?.logError?.({
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack ?? undefined,
      timestamp: new Date().toISOString(),
    });
  }

  handleReset = () => {
    useStore.getState().reset();
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return <ErrorFallback error={this.state.error} onReset={this.handleReset} />;
    }
    return this.props.children;
  }
}
```

### Task 2.6: Wrap `<App />` in `<ErrorBoundary>` at the root

**Files:**
- Modify: `desktop/src/main.tsx`

- [ ] **Step 1: Update `main.tsx`**

Replace the contents of `desktop/src/main.tsx` with:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
```

- [ ] **Step 2: Verify typecheck and runtime startup**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 2.7: Manually smoke-test the boundary

- [ ] **Step 1: Inject a test throw**

Temporarily, in `desktop/src/pages/FolderSelection.tsx` at the top of the `FolderSelection` function, add:

```tsx
if (typeof window !== 'undefined' && window.location.search.includes('crashtest')) {
  throw new Error('Crash test');
}
```

- [ ] **Step 2: Launch the app, trigger the crash, verify recovery**

Run from `desktop/`:
```bash
npm run dev:electron
```

Open DevTools (Cmd+Opt+I or Ctrl+Shift+I) and run in the console:
```js
window.location.search = '?crashtest';
```

Expected: the ErrorFallback renders. Click "Start over". Verify the app returns to the folder-selection screen and behaves normally.

- [ ] **Step 3: Verify the error log file was written**

In a terminal:
```bash
# macOS:
cat "$HOME/Library/Application Support/redaction-tool/error.log"
# Windows:
# type %APPDATA%\redaction-tool\error.log
```

Expected: a JSON-line entry with `message: "Crash test"` and a `recordedAt` timestamp.

- [ ] **Step 4: Remove the test throw**

Revert the change made in Step 1 of this task. Verify the app launches normally one more time.

### Task 2.8: Commit Phase 2

- [ ] **Step 1: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/src/components/ErrorBoundary.tsx desktop/src/components/ErrorFallback.tsx desktop/src/main.tsx desktop/src/electron.d.ts desktop/electron/preload.cjs desktop/electron/main.cjs
git commit -m "feat(desktop): add React error boundary with local error log

Catches render-time exceptions, shows a recovery screen with optional
technical details, and persists the error to error.log in the app's
userData directory via a new log-error IPC handler. The Start Over
button calls useStore.getState().reset() to wipe wizard state.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 3: Error message mapping (Spec Section 3)

Translate raw backend error strings into teacher-friendly text. Make the Setup screen surface check failures.

### Task 3.1: TDD — write the failing test for `friendlyError`

**Files:**
- Create: `desktop/tests/errorMessage.test.ts`

- [ ] **Step 1: Write the test file**

Create `desktop/tests/errorMessage.test.ts` with:

```ts
import { describe, it, expect } from 'vitest';
import { friendlyError } from '../src/lib/errorMessage';
import { BackendUnreachableError } from '../src/api';

describe('friendlyError', () => {
  it('maps BackendUnreachableError to the engine-down message', () => {
    expect(friendlyError(new BackendUnreachableError()))
      .toMatch(/redaction engine isn't responding/i);
  });

  it('maps "Folder not found" to a friendly message', () => {
    expect(friendlyError(new Error('Folder not found: /tmp/x')))
      .toMatch(/folder couldn't be found/i);
  });

  it('maps "File not found" to a file-moved message', () => {
    expect(friendlyError(new Error('File not found: /tmp/x.pdf')))
      .toMatch(/files couldn't be opened/i);
  });

  it('maps "No cached detection data" to a re-run-detection message', () => {
    expect(friendlyError(new Error('No cached detection data for /tmp/x.pdf. Run detection first.')))
      .toMatch(/detection step needs to run again/i);
  });

  it('maps "Cannot open PDF" to a corrupted-PDF message', () => {
    expect(friendlyError(new Error('Cannot open PDF: cannot find xref')))
      .toMatch(/PDFs couldn't be read/i);
  });

  it('maps "Page N out of range" to a page-load message', () => {
    expect(friendlyError(new Error('Page 5 out of range (0-3)')))
      .toMatch(/couldn't load that page/i);
  });

  it('returns the fallback for an unknown error', () => {
    expect(friendlyError(new Error('Unrecognised exception')))
      .toMatch(/something went wrong/i);
  });

  it('returns the fallback for non-Error inputs', () => {
    expect(friendlyError('plain string')).toMatch(/something went wrong/i);
    expect(friendlyError(null)).toMatch(/something went wrong/i);
    expect(friendlyError(undefined)).toMatch(/something went wrong/i);
  });
});
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
cd desktop && npm test
```

Expected: FAIL with module-not-found for `../src/lib/errorMessage`.

### Task 3.2: Implement `friendlyError`

**Files:**
- Create: `desktop/src/lib/errorMessage.ts`

- [ ] **Step 1: Write the implementation**

Create `desktop/src/lib/errorMessage.ts` with:

```ts
import { BackendUnreachableError } from '../api';

const PATTERNS: Array<[RegExp, string]> = [
  [/folder not found/i, "That folder couldn't be found. Check the path and try again."],
  [/file not found/i, "One of the files couldn't be opened. It may have been moved or deleted since the folder was scanned."],
  [/no cached detection data/i, "The detection step needs to run again. Please go back one step and try again."],
  [/cannot open pdf/i, "One of the PDFs couldn't be read. It may be corrupted or password-protected."],
  [/page \d+ out of range/i, "Couldn't load that page from the PDF."],
];

const FALLBACK = "Something went wrong. Please try again, or restart the app if this keeps happening.";
const BACKEND_DOWN = "The redaction engine isn't responding. Please restart the app.";

export function friendlyError(err: unknown): string {
  if (err instanceof BackendUnreachableError) return BACKEND_DOWN;
  const raw = err instanceof Error ? err.message : String(err);
  for (const [re, msg] of PATTERNS) {
    if (re.test(raw)) return msg;
  }
  return FALLBACK;
}
```

- [ ] **Step 2: Run the test, verify it passes**

```bash
cd desktop && npm test
```

Expected: all 8 test cases PASS.

### Task 3.3: Replace `setError(e.message)` call sites with `friendlyError`

**Files:**
- Modify: `desktop/src/pages/ConversionStatus.tsx`
- Modify: `desktop/src/pages/FinalConfirmation.tsx`
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Update `ConversionStatus.tsx`**

Add the import at the top:

```tsx
import { friendlyError } from '../lib/errorMessage';
```

There are exactly three `setError(e.message)` sites in this file. Replace each:

| Location | Before | After |
|---|---|---|
| Dep-check effect (line ~26) | `.catch((e) => setError(e.message))` | `.catch((e) => setError(friendlyError(e)))` |
| `processFolder` effect (line ~38) | `if (e.name !== 'AbortError') setError(e.message);` | `if (e.name !== 'AbortError') setError(friendlyError(e));` |
| `handleContinue` (line ~67) | `setError(e.message);` | `setError(friendlyError(e));` |

After editing, confirm with:
```bash
grep -n 'setError(e\.message)\|setError(err\.message)' desktop/src/pages/ConversionStatus.tsx
```
Expected: zero matches.

- [ ] **Step 2: Update `FinalConfirmation.tsx`**

Add the import:

```tsx
import { friendlyError } from '../lib/errorMessage';
```

Find the catch block in `handleRedact`:

```tsx
} catch (e: any) {
  if (e.name !== 'AbortError') setError(e.message);
}
```

Replace with:

```tsx
} catch (e: any) {
  if (e.name !== 'AbortError') setError(friendlyError(e));
}
```

- [ ] **Step 3: Update `App.tsx`**

(In Phase 1 we already changed the `.catch` in the dep-check effect to handle `BackendUnreachableError`. The remaining `console.warn` for the non-backend case is fine — it's a developer log, not user-facing.)

No user-facing toast call to update in `App.tsx` — the dep-check error is internal. Verify no other `setError(...)` exists in `App.tsx`:

```bash
grep -n 'setError(' desktop/src/App.tsx
```

Expected: only the `setError(null)` clear button — leave that alone.

- [ ] **Step 4: Run the build and tests**

```bash
cd desktop && npm run build && npm test
```

Expected: build passes; all tests pass.

### Task 3.4: Replace silent catch in Setup screen

**Files:**
- Modify: `desktop/src/pages/Setup.tsx`

- [ ] **Step 1: Add the import**

At the top of `desktop/src/pages/Setup.tsx`:

```tsx
import { friendlyError } from '../lib/errorMessage';
```

- [ ] **Step 2: Add error state and update the handler**

Find the `useState` lines at the top of the `Setup` function. Add a third one:

```tsx
const [checkError, setCheckError] = useState<string | null>(null);
```

Replace the entire `handleCheckAgain` function with:

```tsx
const handleCheckAgain = async () => {
  setChecking(true);
  setCheckError(null);
  try {
    const result = await api.checkDependencies();
    setDeps(result);
    if (result.libreoffice_ok && result.ner_ok !== false) {
      setAllReady(true);
      setTimeout(() => navigateTo('folder_selection'), 2000);
    }
  } catch (e) {
    setCheckError(friendlyError(e));
  } finally {
    setChecking(false);
  }
};
```

- [ ] **Step 3: Render the error message between the existing status banners and the action buttons**

In `Setup.tsx`, find the `</AnimatePresence>` tag that closes the existing status-message block (it's the one wrapping the LibreOffice + NER error messages, around line 128 in the current file). Immediately after that closing tag and before the `{/* Actions */}` comment, insert:

```tsx
{checkError && (
  <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
    {checkError}
  </div>
)}
```

This places the dep-check failure message in the same visual band as the existing status banners, so it reads consistently.

- [ ] **Step 4: Verify build**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 3.5: Commit Phase 3

- [ ] **Step 1: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/src/lib/errorMessage.ts desktop/tests/errorMessage.test.ts desktop/src/pages/Setup.tsx desktop/src/pages/ConversionStatus.tsx desktop/src/pages/FinalConfirmation.tsx
git commit -m "feat(desktop): translate backend errors to teacher-friendly text

New friendlyError mapper covers all five HTTPException patterns from
backend/main.py plus a fallback. Setup screen no longer silently swallows
check-dependency errors — users see a red message under the button.
ConversionStatus and FinalConfirmation toasts now show friendly text
instead of raw backend strings.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 4: Cancel cleanup (Spec Section 4)

Add backend endpoints to list and delete partial output. Replace the inaccurate "Progress will be lost" dialog with honest copy and a post-cancel cleanup UI.

### Task 4.1: Add cleanup schemas to `backend/schemas.py`

**Files:**
- Modify: `backend/schemas.py`

- [ ] **Step 1: Append the new request/response models**

At the end of `backend/schemas.py`, add:

```python
# ── Cleanup ──────────────────────────────────────────────────────────────

class CleanupListRequest(BaseModel):
    output_path: str


class CleanupListResponse(BaseModel):
    files: List[str]


class CleanupRequest(BaseModel):
    output_folder: str
    file_paths: List[str]


class CleanupFailure(BaseModel):
    path: str
    reason: str


class CleanupResponse(BaseModel):
    deleted: List[str]
    failed: List[CleanupFailure]
```

### Task 4.2: Add cleanup endpoints to `backend/main.py`

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports for the new schemas**

Find the `from backend.schemas import (...)` block in `backend/main.py`. Extend the import list to include:

```python
    CleanupListRequest,
    CleanupListResponse,
    CleanupRequest,
    CleanupResponse,
    CleanupFailure,
```

- [ ] **Step 2: Append the two endpoints to the end of `backend/main.py`**

At the bottom of the file (after the existing `/api/folder/validate` endpoint), add:

```python
# ── Cleanup ──────────────────────────────────────────────────────────────

@app.post("/api/cleanup/list", response_model=CleanupListResponse)
def cleanup_list(req: CleanupListRequest):
    folder = Path(req.output_path)
    if not folder.exists() or not folder.is_dir():
        return CleanupListResponse(files=[])
    files = [str(p) for p in folder.glob("*_redacted.pdf")]
    files += [str(p) for p in folder.glob("*.UNVERIFIED.pdf")]
    return CleanupListResponse(files=sorted(files))


@app.post("/api/cleanup", response_model=CleanupResponse)
def cleanup(req: CleanupRequest):
    folder = Path(req.output_folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.output_folder}")

    deleted: list[str] = []
    failed: list[CleanupFailure] = []

    for p in req.file_paths:
        path = Path(p).resolve()
        if not path.is_relative_to(folder):
            failed.append(CleanupFailure(path=p, reason="outside output folder"))
            continue
        if path.suffix != ".pdf":
            failed.append(CleanupFailure(path=p, reason="not a PDF"))
            continue
        if not path.exists():
            continue  # Already gone — treat as no-op success
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError as e:
            failed.append(CleanupFailure(path=p, reason=str(e)))

    return CleanupResponse(deleted=deleted, failed=failed)
```

- [ ] **Step 3: Run backend tests to confirm nothing regressed**

From the repo root:
```bash
source venv/bin/activate && pytest tests/ -v -x --timeout=60
```

Expected: existing tests still pass. (No new tests yet — the endpoints will be smoke-tested manually in Task 4.6.)

### Task 4.3: Add cleanup methods to the API client

**Files:**
- Modify: `desktop/src/api.ts`

- [ ] **Step 1: Add the two methods to the `api` object**

In `desktop/src/api.ts`, inside the `export const api = { ... }` object, after the `openFolder` method, add:

```ts
  cleanupList: (output_path: string) =>
    request<{ files: string[] }>('/api/cleanup/list', {
      method: 'POST',
      body: JSON.stringify({ output_path }),
    }),

  cleanup: (output_folder: string, file_paths: string[]) =>
    request<{ deleted: string[]; failed: { path: string; reason: string }[] }>('/api/cleanup', {
      method: 'POST',
      body: JSON.stringify({ output_folder, file_paths }),
    }),
```

### Task 4.4: Track the resolved output path in the store

**Files:**
- Modify: `desktop/src/store.ts`

- [ ] **Step 1: Add `lastOutputPath` field, setter, and reset entry**

In the `AppState` interface, after `setRedactionResults`:

```ts
  lastOutputPath: string;
  setLastOutputPath: (path: string) => void;
```

In `initialState`, add `lastOutputPath: '',` next to `redactionResults: null,`.

In the `create<AppState>` body, after `setRedactionResults`, add:

```ts
  setLastOutputPath: (path) => set({ lastOutputPath: path }),
```

### Task 4.5: Replace `FinalConfirmation` cancel UX with honest copy + post-cancel screen

**Files:**
- Modify: `desktop/src/pages/FinalConfirmation.tsx`

- [ ] **Step 1: Add the post-cancel state and imports**

Add to existing imports at the top:

```tsx
import { Trash2, FolderOpen as FolderOpenIcon } from 'lucide-react';
```

(`FolderOpen` is already imported — alias the second one.)

Inside the `FinalConfirmation` function, alongside the existing `useState` calls, add:

```tsx
const [cancelled, setCancelled] = useState(false);
const [partialFiles, setPartialFiles] = useState<string[]>([]);
const [cleaningUp, setCleaningUp] = useState(false);
const [cleanupDone, setCleanupDone] = useState(false);
```

Pull `setLastOutputPath` and `lastOutputPath` from the store (alongside the existing destructured fields):

```tsx
const { /* existing fields */, lastOutputPath, setLastOutputPath } = useStore();
```

- [ ] **Step 2: Persist the resolved output path before redaction starts**

In `handleRedact`, immediately after `setRedacting(true);`, add:

```tsx
const resolvedOutputPath = outputMode === 'custom' && customPath
  ? customPath
  : `${folderPath}/redacted`;
setLastOutputPath(resolvedOutputPath);
```

- [ ] **Step 3: Replace the cancel-confirm dialog text and add post-cancel fetch**

Find the existing cancel button inside the `if (redacting)` early-return block. Replace its `onClick` with:

```tsx
onClick={async () => {
  if (!confirm("This will stop further documents from being processed. Files already redacted will remain in the output folder. Continue cancelling?")) {
    return;
  }
  abortRef.current?.abort();
  setRedacting(false);

  // Surface what's already on disk
  try {
    const list = await api.cleanupList(lastOutputPath);
    setPartialFiles(list.files);
  } catch {
    setPartialFiles([]);
  }
  setCancelled(true);
}}
```

- [ ] **Step 4: Add the post-cancel render branch**

Inside the `FinalConfirmation` function body, immediately before the existing `if (redacting) { ... }` block, add a new branch for the cancelled state:

```tsx
if (cancelled) {
  const fileCount = partialFiles.length;
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Cancelled</h2>
        <p className="text-sm text-slate-400 mt-1">
          {fileCount === 0
            ? "Redaction was cancelled before any files were written."
            : `${fileCount} file${fileCount === 1 ? '' : 's'} ${fileCount === 1 ? 'was' : 'were'} redacted before stopping.`}
        </p>
      </div>

      {fileCount > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-2">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Partial output</p>
          <ul className="text-xs text-slate-500 space-y-0.5 max-h-48 overflow-y-auto">
            {partialFiles.map((f) => <li key={f}>{f.split('/').pop()}</li>)}
          </ul>
        </div>
      )}

      {cleanupDone && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2.5 text-sm text-emerald-700">
          Partial output deleted.
        </div>
      )}

      <div className="flex flex-wrap gap-2 pt-2">
        <button
          onClick={() => api.openFolder(lastOutputPath)}
          disabled={fileCount === 0}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors btn-press"
        >
          <FolderOpenIcon size={14} /> Open output folder
        </button>

        <button
          onClick={async () => {
            setCleaningUp(true);
            try {
              await api.cleanup(lastOutputPath, partialFiles);
              setPartialFiles([]);
              setCleanupDone(true);
            } catch (e: any) {
              setError(friendlyError(e));
            } finally {
              setCleaningUp(false);
            }
          }}
          disabled={fileCount === 0 || cleaningUp}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors btn-press"
        >
          <Trash2 size={14} /> {cleaningUp ? 'Deleting...' : 'Delete partial output'}
        </button>

        <button
          onClick={() => {
            setCancelled(false);
            setPartialFiles([]);
            setCleanupDone(false);
            navigateTo('document_review');
          }}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors btn-press ml-auto"
        >
          Done
        </button>
      </div>
    </div>
  );
}
```

(Make sure `friendlyError` is imported from Phase 3.)

- [ ] **Step 5: Verify build**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 4.6: Manual smoke test of cleanup endpoints

- [ ] **Step 1: Run the app**

```bash
cd desktop && npm run dev:electron
```

- [ ] **Step 2: Trigger a multi-document redaction**

Pick a folder with at least 3 sample PDFs (use `sample/` if available). Run the wizard through to FinalConfirmation. Click "Create Redacted Documents". Once 1–2 documents complete, click Cancel and confirm.

Expected: Cancelled screen appears showing N files with their basenames listed.

- [ ] **Step 3: Verify Open Folder works**

Click "Open output folder" → the OS file manager opens to the redacted/ folder.

- [ ] **Step 4: Verify Delete Partial Output works**

Click "Delete partial output" → toast appears, list empties, only the original (un-redacted) files remain in the source folder. Originals are untouched.

- [ ] **Step 5: Verify Done returns cleanly**

Click "Done" → returns to DocumentReview screen with all selections preserved.

### Task 4.7: Commit Phase 4

- [ ] **Step 1: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add backend/main.py backend/schemas.py desktop/src/api.ts desktop/src/store.ts desktop/src/pages/FinalConfirmation.tsx
git commit -m "feat: honest cancel + cleanup of partial redaction output

Adds /api/cleanup/list and /api/cleanup endpoints to enumerate and
delete partial output safely (path validated against the user-selected
output folder). Replaces the inaccurate 'Progress will be lost' dialog
with copy that explains files-already-on-disk semantics. Post-cancel UI
lists partial files, opens the output folder, or deletes them.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 5: No-PII terminal state (Spec Section 5)

Skip the dead-end DocumentReview path when zero PII is detected anywhere; route to a clean "Nothing to redact" page.

### Task 5.1: Extend the `Screen` type

**Files:**
- Modify: `desktop/src/types.ts`

- [ ] **Step 1: Add the new screen value**

Replace the `Screen` union with:

```ts
export type Screen =
  | 'setup'
  | 'folder_selection'
  | 'conversion_status'
  | 'document_review'
  | 'no_pii_found'
  | 'final_confirmation'
  | 'completion';
```

(Do NOT add `no_pii_found` to the `SCREENS` array — it's a terminal state with no step number in the sidebar.)

### Task 5.2: Create `NoPiiFound` page

**Files:**
- Create: `desktop/src/pages/NoPiiFound.tsx`

- [ ] **Step 1: Write the component**

Create `desktop/src/pages/NoPiiFound.tsx` with:

```tsx
import { motion } from 'framer-motion';
import { ShieldCheck, RotateCcw, ArrowLeft } from 'lucide-react';
import { useStore } from '../store';

export default function NoPiiFound() {
  const { detectionResults, navigateTo, reset } = useStore();
  const docCount = detectionResults?.documents.length ?? 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center min-h-[60vh] text-center"
    >
      <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
        <ShieldCheck size={32} className="text-emerald-600" />
      </div>

      <h2 className="text-2xl font-bold text-slate-800">Nothing to redact</h2>
      <p className="text-sm text-slate-500 mt-2 max-w-md">
        We scanned {docCount} document{docCount === 1 ? '' : 's'} and didn&apos;t find any personal information matching the names you provided. Your folder appears clean.
      </p>
      <p className="text-xs text-slate-400 mt-3 max-w-md">
        If you expected items to be flagged, double-check the spelling of names on the previous step.
      </p>

      <div className="flex gap-3 mt-8">
        <button
          onClick={() => navigateTo('folder_selection')}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm border border-slate-200 text-slate-600 hover:bg-slate-100 transition-colors btn-press"
        >
          <ArrowLeft size={14} /> Back to Names
        </button>
        <button
          onClick={() => { reset(); navigateTo('folder_selection'); }}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <RotateCcw size={14} /> Process Another Folder
        </button>
      </div>
    </motion.div>
  );
}
```

### Task 5.3: Wire the route in `App.tsx`

**Files:**
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Import the new page and add the case**

At the top of `App.tsx`, alongside the existing page imports:

```tsx
import NoPiiFound from './pages/NoPiiFound';
```

In the `renderScreen` switch, add the new case in the same order it appears in the `Screen` union:

```tsx
case 'document_review':    return <DocumentReview />;
case 'no_pii_found':       return <NoPiiFound />;
case 'final_confirmation': return <FinalConfirmation />;
```

### Task 5.4: Branch `ConversionStatus.handleContinue` on total match count

**Files:**
- Modify: `desktop/src/pages/ConversionStatus.tsx`

- [ ] **Step 1: Replace the navigate call**

Inside `handleContinue`, find this line:

```tsx
setDetectionResults(detection);
navigateTo('document_review');
```

Replace with:

```tsx
setDetectionResults(detection);
const totalMatches = detection.documents.reduce(
  (sum, d) => sum + d.matches.length,
  0
);
navigateTo(totalMatches === 0 ? 'no_pii_found' : 'document_review');
```

- [ ] **Step 2: Verify build**

```bash
cd desktop && npm run build
```

Expected: no errors.

### Task 5.5: Commit Phase 5

- [ ] **Step 1: Commit**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/src/types.ts desktop/src/pages/NoPiiFound.tsx desktop/src/App.tsx desktop/src/pages/ConversionStatus.tsx
git commit -m "feat(desktop): clean terminal state when no PII is detected

When detection returns zero matches across every document, route to a
new NoPiiFound page instead of the broken-feeling DocumentReview /
disabled-FinalConfirmation chain. Two recovery paths: 'Back to Names'
preserves the folder + name inputs; 'Process Another Folder' resets.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 6: Final manual smoke verification

Once Phases 0–5 are merged on the worktree branch, run a coordinated smoke test that exercises every fix end-to-end before the branch is merged into `test`.

### Task 6.1: Smoke verify all six fixes

- [ ] **Step 1: Backend-down banner (Fix 1)**

Run `cd desktop && npm run dev:electron`. Once the app launches, kill the FastAPI process: in another terminal, `lsof -ti:8765 | xargs kill -9`. Click around the app — within 5 seconds of any API call, the amber backend-down banner should appear at the top of the wizard. Restart the backend (let Electron respawn it, or `./venv/bin/python3.13 -m uvicorn backend.main:app --port 8765`). Within 5 seconds of the next health poll, the banner should clear.

- [ ] **Step 2: Error boundary (Fix 2)**

Open DevTools console with Cmd+Opt+I (Mac) or Ctrl+Shift+I (Windows). Run:
```js
throw new Error('manual test')
```
Note: throwing in DevTools does NOT trigger the boundary (different context). Instead, temporarily edit `FolderSelection.tsx` to add `throw new Error('test')` at the top of the component, save, hot-reload. Confirm the ErrorFallback renders and "Start over" returns to a working folder selection screen. Revert the test throw.

Then verify `error.log`:
```bash
cat "$HOME/Library/Application Support/redaction-tool/error.log"
```
Expected: at least one JSON line with `message: "test"`.

- [ ] **Step 3: Setup silent-catch (Fix 3)**

On a fresh launch where the backend is killed, click Check Again on the setup screen. The red error message should appear under the button.

- [ ] **Step 4: Error message mapping (Fix 4)**

Trigger one mapped error: in the wizard, after detection, manually delete one of the source PDFs from disk, then click "Create Redacted Documents". The toast should show the friendly "files couldn't be opened" text, NOT a raw "File not found: ..." string. Run `cd desktop && npm test` to confirm all 8 mapper test cases still pass.

- [ ] **Step 5: Cancel cleanup (Fix 5)**

Process a folder with 5+ PDFs through to FinalConfirmation. Click Create Redacted Documents. Once 2 files are written, click Cancel; confirm. The Cancelled screen should list the 2 redacted files. Click Delete Partial Output; verify those files are gone from the output folder while originals remain. Click Done; verify return to DocumentReview with selections intact.

- [ ] **Step 6: No-PII terminal state (Fix 6)**

Process a folder using a deliberately wrong student name (e.g., "Zzzqx Nonexistent"). After detection, the NoPiiFound screen should render with the document count. Click "Back to Names" — folder path and name fields should be preserved on FolderSelection. Re-run with a real name; confirm the regular DocumentReview path still works.

### Task 6.2: Update CLAUDE.md (project memory)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a note in the "Critical Non-Obvious Rules" section**

Append a new numbered rule to the existing "Critical Non-Obvious Rules" list in `CLAUDE.md` (at the project root):

```markdown
### 28. Backend-down detection lives in `api.ts` + `App.tsx`

`api.ts` distinguishes network errors from HTTP errors via `BackendUnreachableError`. The Zustand `backendReachable` flag drives a top-of-app banner in `App.tsx`; a 5-second polling effect on `/api/health` only runs while the flag is `false`. `FolderSelection.validateFolder` deliberately leaves `folderValid` untouched on `BackendUnreachableError` so the false-negative "Folder not found" message doesn't render.

### 29. Error message text comes from `lib/errorMessage.ts`, not raw backend strings

All `setError` call sites use `friendlyError(e)` from `desktop/src/lib/errorMessage.ts`. The mapper covers every `HTTPException(detail=...)` pattern in `backend/main.py` plus a fallback. Tests live at `desktop/tests/errorMessage.test.ts`. If you add a new backend error string, add a pattern to the mapper and a test case.

### 30. Cleanup endpoints are restricted to the user-selected output folder

`/api/cleanup` and `/api/cleanup/list` only operate on `*_redacted.pdf` and `*.UNVERIFIED.pdf` files inside the resolved `output_folder` (verified via `Path.is_relative_to`). Do not relax these checks — they prevent path-traversal deletion of files outside the output area.
```

- [ ] **Step 2: Commit the CLAUDE.md update**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add CLAUDE.md
git commit -m "docs: capture v1.3.0 resilience invariants in CLAUDE.md

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

### Task 6.3: Bump version and prepare for merge to `test`

**Files:**
- Modify: `desktop/package.json`

- [ ] **Step 1: Bump version to 1.3.0**

In `desktop/package.json`, change `"version": "1.2.0"` to `"version": "1.3.0"`.

- [ ] **Step 2: Commit and push the worktree branch**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git add desktop/package.json
git commit -m "chore: bump version to 1.3.0

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push -u origin claude/admiring-blackwell-f6b062
```

The branch is now ready for the user to merge into `test` for the staging build, then `test` → `main` per the project's deployment workflow.

---

## Plan summary

**Total commits:** 7 (one per phase + version bump). Each is independently reviewable and the worktree is mergeable at every commit.

**New files (5):**
- `desktop/src/components/ErrorBoundary.tsx`
- `desktop/src/components/ErrorFallback.tsx`
- `desktop/src/lib/errorMessage.ts`
- `desktop/src/pages/NoPiiFound.tsx`
- `desktop/tests/errorMessage.test.ts`

**Modified files (12):**
- `desktop/package.json` (Vitest dep + version bump)
- `desktop/package-lock.json`
- `desktop/src/api.ts`
- `desktop/src/store.ts`
- `desktop/src/types.ts`
- `desktop/src/App.tsx`
- `desktop/src/main.tsx`
- `desktop/src/electron.d.ts`
- `desktop/src/pages/Setup.tsx`
- `desktop/src/pages/ConversionStatus.tsx`
- `desktop/src/pages/FinalConfirmation.tsx`
- `desktop/src/pages/FolderSelection.tsx`
- `desktop/electron/preload.cjs`
- `desktop/electron/main.cjs`
- `backend/main.py`
- `backend/schemas.py`
- `CLAUDE.md`

**Acceptance gate:** Task 6.1 must pass all six fix verifications before the branch merges to `test`. Smoke pass on `test` is required before merging to `main`.
