# Resilience and Trust Improvements — Design Spec

**Date:** 2026-05-07
**Scope:** Bulk Redaction Tool desktop app (Electron + React + FastAPI)
**Goal:** Fix six user-visible defects that erode trust, without architectural rewrites.
**Target version:** v1.3.0

## Context

The desktop app ships to teachers and school psychologists who are non-technical. There is currently no in-app feedback mechanism, so user-side defects are invisible to the maintainer. A code review surfaced six concrete issues that produce wrong, dead-end, or confusing behaviour today. This spec addresses those six issues only — no speculative improvements, no architectural rewrites.

## Issues addressed

| # | Issue | Severity |
|---|---|---|
| 1 | Backend-down failures surface as "Folder not found" | Wrong message |
| 2 | No React error boundary; uncaught exceptions blank the app | Dead end |
| 3 | Setup screen's "Check Again" silently swallows errors | Silent failure |
| 4 | Raw backend error strings reach the user toast | Confusing UX |
| 5 | Cancel during redaction leaves partial output with no cleanup path | Trust erosion |
| 6 | Zero-PII detection lands user on a dead-end review screen | Trust erosion |

Issues considered and explicitly out of scope:
- "Accept All" button label semantics — works fine, just slightly misleading
- Back-navigation from DocumentReview to FolderSelection — workaround exists ("Process Another Folder")
- Architectural rewrite of error handling — premature without telemetry
- Conversion-side cleanup on cancel — converted PDFs are useful artefacts

---

## Section 1: Backend-down detection

**Problem.** `api.ts` throws a generic `Error` for both network failures (backend unreachable) and HTTP errors. `FolderSelection.validateFolder` silently catches both and sets `folderValid = false`, so a dead backend looks identical to a typo'd folder path.

**Design.**

Distinguish network errors from HTTP errors in `desktop/src/api.ts`:

```ts
export class BackendUnreachableError extends Error {
  constructor() { super('Backend not reachable'); this.name = 'BackendUnreachableError'; }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  } catch (e: any) {
    if (e.name === 'AbortError') throw e;
    throw new BackendUnreachableError();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
```

Add `backendReachable: boolean` (default `true`) and `setBackendReachable` to the Zustand store. A `useBackendHealth()` hook in `App.tsx` polls `/api/health` every 5 seconds **only while `backendReachable === false`**. When a successful health check returns, the flag flips back to `true` and polling stops.

Render a banner above the existing global error toast when the flag is `false`:

> "The redaction engine isn't responding. Please wait a moment, or restart the app if this persists."

Update `FolderSelection.validateFolder` to handle the two error types differently. Currently the function uses a bare `catch` that conflates network and HTTP errors. The new version:

```ts
} catch (e) {
  if (e instanceof BackendUnreachableError) {
    useStore.getState().setBackendReachable(false);
    // Don't flip folderValid — leave the input in a neutral state
  } else {
    setFolderValid(false);  // Existing behaviour: real validation failure
  }
}
```

The "Folder not found — check the path" JSX message is gated on `folderValid === false`, so leaving `folderValid` untouched when the backend is unreachable means the false-negative message never renders. The top-of-app banner explains the real situation.

**Files touched:**
- `desktop/src/api.ts` (new error class, distinguish network vs HTTP)
- `desktop/src/store.ts` (new field + setter)
- `desktop/src/App.tsx` (banner + polling effect)
- `desktop/src/pages/FolderSelection.tsx` (skip false-negative messaging)

---

## Section 2: React error boundary

**Problem.** Any uncaught render exception blanks the entire window. The user has no recovery path other than quitting and relaunching.

**Design.**

New class component at `desktop/src/components/ErrorBoundary.tsx`:

```tsx
export class ErrorBoundary extends React.Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Render error:', error, info);
    window.electronAPI?.logError?.({
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
      timestamp: new Date().toISOString(),
    });
  }
  render() {
    if (this.state.error) {
      return <ErrorFallback
        error={this.state.error}
        onReset={() => { useStore.getState().reset(); this.setState({ error: null }); }}
      />;
    }
    return this.props.children;
  }
}
```

`ErrorFallback` is a centred screen with: heading "Something went wrong", a friendly explanation, a collapsible "Technical details" block showing `error.message`, and a single "Start over" button. No quit button — users have OS-level shortcuts.

Wrap `<App />` in `<ErrorBoundary>` at the root render site (`desktop/src/main.tsx`).

**Local error log.** Add `electronAPI.logError(payload)` IPC method:
- `desktop/electron/preload.cjs` exposes `logError`.
- `desktop/electron/main.cjs` handler appends a JSON-line entry to `path.join(app.getPath('userData'), 'error.log')`.

**Files touched:**
- New: `desktop/src/components/ErrorBoundary.tsx`, `desktop/src/components/ErrorFallback.tsx`
- `desktop/src/main.tsx` (wrap App)
- `desktop/electron/preload.cjs` (expose logError)
- `desktop/electron/main.cjs` (IPC handler + file append)

---

## Section 3: Setup silent-catch + error-message mapping

**Problem 3.** `desktop/src/pages/Setup.tsx` has `catch { /* silently fail */ }` on Check Again. The user gets no feedback when the check itself errors.

**Problem 4.** Backend error strings like `"Cannot open PDF: cannot find xref"` and `"No cached detection data for /path/to/file.pdf. Run detection first."` reach the toast verbatim.

**Design.**

New module at `desktop/src/lib/errorMessage.ts`:

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
  for (const [re, msg] of PATTERNS) if (re.test(raw)) return msg;
  return FALLBACK;
}
```

The five `PATTERNS` entries match the complete set of `HTTPException(detail=...)` sites in `backend/main.py` (lines 104, 130, 209, 290, 295, 299, 325 — five unique strings). Service-layer code does not raise to the API; it returns result objects with errors embedded. The fallback covers any unexpected 500.

Replace every `setError(e.message)` call site with `setError(friendlyError(e))`:
- `desktop/src/pages/ConversionStatus.tsx`
- `desktop/src/pages/FinalConfirmation.tsx`
- `desktop/src/App.tsx` (dep check effect)

**Setup screen.** Replace the silent catch with visible state:

```tsx
const [checkError, setCheckError] = useState<string | null>(null);

const handleCheckAgain = async () => {
  setChecking(true);
  setCheckError(null);
  try {
    const result = await api.checkDependencies();
    // ... existing logic unchanged
  } catch (e) {
    setCheckError(friendlyError(e));
  } finally {
    setChecking(false);
  }
};
```

Render `checkError` as a small red message under the Check Again button.

**Files touched:**
- New: `desktop/src/lib/errorMessage.ts`
- New: `desktop/tests/errorMessage.test.ts` (Vitest unit tests covering all five patterns + fallback + backend-unreachable)
- `desktop/src/pages/Setup.tsx`
- `desktop/src/pages/ConversionStatus.tsx`
- `desktop/src/pages/FinalConfirmation.tsx`
- `desktop/src/App.tsx`

---

## Section 4: Cancel cleanup

**Problem.** Cancel during redaction aborts the HTTP request client-side, but the backend continues running the current document. Files already redacted stay on disk. The dialog's "Progress will be lost" message is inaccurate.

**Design (Path 4a — honest dialog + cleanup-on-demand).**

**Dialog text.** Change confirm text in `FinalConfirmation.tsx` cancel button to:

> "This will stop further documents from being processed. Files already redacted will remain in the output folder. Continue cancelling?"

**Track written files.** `RedactionService.run()` already accumulates `document_results`. Add `output_path: str | None` to each `DocumentResult` (it's already there per `DocumentResultResponse` in `backend/schemas.py` — verify and surface). The frontend can derive the list of written files from `redactionResults.document_results.filter(r => r.success && r.output_path).map(r => r.output_path)`.

Since cancellation aborts the HTTP request before `redactionResults` is populated, the backend needs to return a partial-result envelope on graceful shutdown OR the frontend needs to derive what was written from disk. Simpler approach: **scan the output directory after cancel.**

The frontend stores the resolved output path before redaction starts. On cancel, it queries a new endpoint `POST /api/cleanup/list` with the output path, which returns the list of redacted files currently present (matched by the `_redacted.pdf` naming convention). The user can then preview that list and choose to delete.

**Cleanup endpoint.** New `POST /api/cleanup` in `backend/main.py`:

```python
class CleanupRequest(BaseModel):
    output_folder: str
    file_paths: list[str]

@app.post("/api/cleanup")
def cleanup(req: CleanupRequest):
    folder = Path(req.output_folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.output_folder}")

    deleted, failed = [], []
    for p in req.file_paths:
        path = Path(p).resolve()
        # Path safety: must be inside the declared output folder, must be a file we wrote
        if not path.is_relative_to(folder):
            failed.append({"path": p, "reason": "outside output folder"})
            continue
        if path.suffix != '.pdf':
            failed.append({"path": p, "reason": "not a PDF"})
            continue
        if not path.exists():
            continue  # Already gone, treat as success-noop
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError as e:
            failed.append({"path": p, "reason": str(e)})
    return {"deleted": deleted, "failed": failed}
```

Path safety: the request must include the user-selected output folder; the endpoint resolves both folder and each file path and refuses any file not under that folder. Only `.pdf` files are eligible — no recursive directory deletion. `.UNVERIFIED.pdf` quarantine files (produced when verification fails) match the suffix check because `Path.suffix` returns the last extension only.

**Cleanup listing endpoint.** New `POST /api/cleanup/list`:

```python
class CleanupListRequest(BaseModel):
    output_path: str

@app.post("/api/cleanup/list")
def cleanup_list(req: CleanupListRequest):
    folder = Path(req.output_path)
    if not folder.exists() or not folder.is_dir():
        return {"files": []}
    files = [str(p) for p in folder.glob("*_redacted.pdf")]
    files += [str(p) for p in folder.glob("*.UNVERIFIED.pdf")]
    return {"files": sorted(files)}
```

The listing covers both successfully redacted files (`*_redacted.pdf`) and the quarantine-renamed files produced when post-redaction verification fails (`*.UNVERIFIED.pdf`). Both are partial output worth offering to clean up.

**Frontend post-cancel UI.** After the user confirms cancellation in `FinalConfirmation`:

1. Show an inline info banner replacing the "redacting" screen:
   > "Cancelled. *N* files were redacted before stopping."
   With buttons: **"Open output folder"**, **"Delete partial output"**, **"Done"**
2. "Delete partial output" calls `/api/cleanup` with the listed files, then shows a small confirmation toast.
3. "Done" navigates back to `document_review`.

**Files touched:**
- `backend/main.py` (two new endpoints)
- `backend/schemas.py` (request/response models)
- `desktop/src/api.ts` (two new client methods: `cleanupList`, `cleanup`)
- `desktop/src/pages/FinalConfirmation.tsx` (dialog text, post-cancel UI state)
- `desktop/src/store.ts` (track `lastOutputPath: string` so cleanup knows where to look after cancel)

**What is NOT cleaned up.** The audit log file (if already written) stays. Converted-from-Word PDFs in the source folder stay. Only `_redacted.pdf` files in the chosen output folder are eligible for cleanup.

---

## Section 5: No-PII terminal state

**Problem.** When detection finds zero matches across every document, `DocumentReview` auto-skips through all of them and lands on the last document showing "No PII detected." The user can hit "Accept All & Continue," but `FinalConfirmation` then disables the redact button because nothing is selected. Dead end.

**Design.**

Add `'no_pii_found'` to the `Screen` type union in `desktop/src/types.ts` and the `SCREENS` array if needed for the sidebar.

In `ConversionStatus.handleContinue`, after detection completes:

```ts
const detection = await api.detectPII({...});
setDetectionResults(detection);

const totalMatches = detection.documents.reduce((sum, d) => sum + d.matches.length, 0);
if (totalMatches === 0) {
  navigateTo('no_pii_found');
} else {
  navigateTo('document_review');
}
```

New page `desktop/src/pages/NoPiiFound.tsx`:

- Centred green shield-check icon
- Heading: "Nothing to redact"
- Body: "We scanned *N* document(s) and didn't find any personal information matching the names you provided. Your folder appears clean."
- Subtext: "If you expected items to be flagged, double-check the spelling of names on the previous step."
- Two buttons:
  - **"Back to Names"** — navigates to `folder_selection` preserving folder + names (no `reset()`)
  - **"Process Another Folder"** — calls `reset()` then navigates to `folder_selection`

Add the route case in `App.tsx`:

```tsx
case 'no_pii_found': return <NoPiiFound />;
```

Sidebar step indicator: treat `no_pii_found` as the same step as `document_review` (step 3). No additional step in the sidebar.

**Files touched:**
- `desktop/src/types.ts`
- New: `desktop/src/pages/NoPiiFound.tsx`
- `desktop/src/App.tsx` (route case)
- `desktop/src/pages/ConversionStatus.tsx` (routing branch)
- `desktop/src/components/Sidebar.tsx` (only if step-indicator logic needs to recognise the new screen)

---

## Section 6: Testing

| Fix | Verification |
|---|---|
| 1. Backend-down detection | Manually kill backend → banner appears within 5s of next API call; restart backend → banner clears within 5s. |
| 2. Error boundary | Temporarily `throw new Error('test')` in a page render → fallback renders, "Start over" button restores app. Verify `error.log` contains entry. |
| 3. Setup silent-catch | Block backend, click Check Again → red error message renders under button. |
| 4. Error mapper | **Unit tests** in `desktop/tests/errorMessage.test.ts` cover all 5 patterns + fallback + `BackendUnreachableError`. Manual smoke for one trigger (e.g. delete a file mid-flow → friendly "file not found" message appears in toast). |
| 5. Cancel cleanup | Start a redaction run with 5+ docs, cancel after 2 finish → banner shows accurate "2 files redacted" count. Click "Delete partial output" → those 2 files removed from output folder, originals untouched. |
| 6. No-PII terminal state | Process a folder with student name "Zzzqx Nonexistent" → after detection, lands on NoPiiFound screen. "Back to Names" preserves folder path; "Process Another Folder" clears it. |

The error-message mapper is the only piece warranting automated tests — it's a pure function with a finite set of patterns. Everything else is verified by manual smoke testing during the PR review on the `test` branch.

---

## Out-of-scope, explicitly

- Backend-side cancellation token (Path 4b in brainstorming). Punted in favour of 4a.
- Conversion-side cleanup on cancel. Converted PDFs are useful artefacts.
- Telemetry / opt-in usage reporting. Separate concern; no current need.
- In-app feedback form. Separate concern; consider once we have v1.3.0 in users' hands.
- Refactoring the existing dep-check race in `App.tsx` beyond what Section 1 already does.

## Files-touched summary

**New files (8):**
- `desktop/src/components/ErrorBoundary.tsx`
- `desktop/src/components/ErrorFallback.tsx`
- `desktop/src/lib/errorMessage.ts`
- `desktop/src/pages/NoPiiFound.tsx`
- `desktop/tests/errorMessage.test.ts`

**Modified files (~10):**
- `desktop/src/api.ts`
- `desktop/src/store.ts`
- `desktop/src/types.ts`
- `desktop/src/App.tsx`
- `desktop/src/main.tsx`
- `desktop/src/pages/Setup.tsx`
- `desktop/src/pages/ConversionStatus.tsx`
- `desktop/src/pages/FinalConfirmation.tsx`
- `desktop/src/pages/FolderSelection.tsx`
- `desktop/src/components/Sidebar.tsx` (only if needed)
- `desktop/electron/preload.cjs`
- `desktop/electron/main.cjs`
- `backend/main.py`
- `backend/schemas.py`

## Acceptance criteria

A user reports each of the six original symptoms is gone:
1. App tells me the engine isn't responding instead of pretending my folder is wrong.
2. If something inside the app errors, I see a recovery screen instead of a blank window.
3. The Check Again button on the setup screen tells me what happened if it can't reach the engine.
4. Error messages I see read like English, not stack traces.
5. When I cancel mid-redaction, the app tells me what's already on disk and lets me clean it up.
6. When the app finds no personal information, it says so cleanly instead of putting me on a broken-looking screen.

All six observable behaviours pass manual verification before merge to `main`.
