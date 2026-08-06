# Batch B — Desktop & Backend Robustness Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the desktop ↔ backend boundary resilient: no infinite hangs, no stuck loading states, no orphaned/zombie backend, no raw 500 tracebacks bypassing the friendly-error mapper, and remove a dead code block that obscures the redaction selection logic.

**Architecture:** Five surgical changes across two subsystems. Backend (Python/FastAPI) and `api.ts` changes are covered by automated tests (pytest TestClient / vitest). The React component (`ConversionStatus.tsx`) and Electron main (`main.cjs`) changes have **no unit-test harness** in this repo (vitest here only tests pure modules; there is no React Testing Library and Electron main cannot be unit-run) — they are verified by `tsc` typecheck, `eslint`, `node --check`, and diff review. The plan is explicit about which gate applies to each task. **No fabricated tests.**

**Tech Stack:** Python 3.13 + FastAPI + `fastapi.testclient.TestClient`; TypeScript 5.9 + React 19 + Zustand; vitest 2; Electron 40. Backend tests: `venv/bin/python3.13 -m pytest`. Desktop tests: `cd desktop && npm test`. Desktop typecheck/build: `cd desktop && npm run build`. Desktop lint: `cd desktop && npm run lint`.

---

## Scope & Mapping to Review Findings

| Task | Finding | File(s) | Defect | Verification |
|------|---------|---------|--------|--------------|
| 1 | #5 | `backend/main.py` | Dead `user_selections` block built then discarded | pytest TestClient (detect→redact selection) |
| 2 | #10 | `backend/main.py` | Heavy endpoints emit raw 500 tracebacks past the error mapper | pytest TestClient (forced failure → clean 500) |
| 3 | #4 | `desktop/src/api.ts` | `fetch` has no timeout — UI hangs forever | vitest (fake timers) |
| 4 | #8 | `desktop/src/pages/ConversionStatus.tsx` | `detectPII` has no AbortController — Back force-navigates | `npm run build` + `npm run lint` + review |
| 5 | #7 | `desktop/electron/main.cjs` | Backend death mid-session unhandled; spawn failure unhandled | `node --check` + `npm run lint` + review |

**Branch:** Continue on `test` (Batch A is already committed there). One atomic commit per task. **Do not push or merge** — local commits only.

**Pre-flight (run once):**
```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git rev-parse --abbrev-ref HEAD                       # expect: test
venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -3   # baseline: 298 passed, 5 pre-existing fails
cd desktop && npm test 2>&1 | tail -5                 # baseline desktop tests
npm run build 2>&1 | tail -3                          # baseline tsc typecheck passes
npm run lint 2>&1 | tail -5                           # note pre-existing eslint error count (7 known)
```
Record each baseline. The 5 `test_ocr_verification.py` failures are pre-existing (Tesseract env). The 7 eslint errors are pre-existing (`DocumentCard.tsx`, `RedactionProgress.tsx`, `Sidebar.tsx`, `Walkthrough.tsx`) — do not increase the count.

---

### Task 1: Remove the dead `user_selections` block in `redact_documents`

**Files:**
- Modify: `backend/main.py` (`redact_documents`, the first `user_selections` build at lines ~219–229, which is immediately overwritten at line ~231)
- Test: `tests/test_backend_redact.py` (create) — also serves as the regression guard that selection logic still works after the deletion

**Context:** Lines 219–229 build `user_selections` using `str(doc_path)`-based keys, then line 231 does `user_selections = {}` and rebuilds it correctly using the frontend's `doc_path_str`-based keys. The first block is dead. The surviving block (lines ~232–240) is the correct one. We delete the dead block and add a TestClient test proving detect→redact honours `selected_keys`.

- [ ] **Step 1: Write the test (it should PASS before and after — it is a regression guard around a behaviour-preserving deletion).**

Create `tests/test_backend_redact.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_redact_honours_only_selected_keys():
    """detect → redact must redact ONLY the matches whose keys are in selected_keys."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        # Two distinct PII names so detection yields >= 2 matches.
        _make_pdf(pdf, "Student Joe Bloggs and parent Mary Bloggs attended.")

        det = client.post("/api/pii/detect", json={
            "pdf_paths": [str(pdf)],
            "student_name": "Joe Bloggs",
            "parent_names": ["Mary Bloggs"],
            "family_names": [],
            "organisation_names": [],
        })
        assert det.status_code == 200, det.text
        doc0 = det.json()["documents"][0]
        matches = doc0["matches"]
        assert len(matches) >= 1, "expected at least one detected match"

        # Select ONLY the first match.
        selected = [f"{pdf}_0"]
        red = client.post("/api/redact", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "parent_names": ["Mary Bloggs"],
            "family_names": [],
            "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": selected,
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        body = red.json()
        # The run completes and reports exactly the one selected item.
        assert body["document_results"][0]["items_redacted"] == 1
```

- [ ] **Step 2: Run it (expect PASS — confirms baseline behaviour before the deletion):**
```bash
venv/bin/python3.13 -m pytest tests/test_backend_redact.py -v
```
If it fails for an environmental reason (e.g. spaCy model missing), STOP and report NEEDS_CONTEXT — do not proceed blind.

- [ ] **Step 3: Delete the dead block.** In `backend/main.py`, in `redact_documents`, remove these lines entirely (the block between the cache-rebuild and the `# Simpler approach` comment):

```python
    # Build user_selections from selected_keys
    user_selections: Dict[str, bool] = {}
    for doc_path_str in req.documents:
        doc_path = Path(doc_path_str)
        matches = detected_pii[doc_path].get("matches", [])
        for idx in range(len(matches)):
            key = f"{doc_path}_{idx}"
            user_selections[key] = key in [
                k.replace(doc_path_str, str(doc_path)) for k in req.selected_keys
                if k.startswith(doc_path_str)
            ]

    # Simpler approach: just mark selected keys as True
    user_selections = {}
```
and replace it with just:
```python
    # Build user_selections: mark each frontend-sent selected key as True.
    user_selections: Dict[str, bool] = {}
```
(The following loop — `for doc_path_str in req.documents:` building `user_selections[key] = frontend_key in req.selected_keys` — stays exactly as is.)

- [ ] **Step 4: Re-run the test (expect PASS — behaviour unchanged):**
```bash
venv/bin/python3.13 -m pytest tests/test_backend_redact.py -v
```

- [ ] **Step 5: Commit:**
```bash
git add backend/main.py tests/test_backend_redact.py
git commit -m "refactor(backend): remove dead user_selections block in redact

The first user_selections build (str(doc_path) keys) was immediately
overwritten by a second, correct build (frontend doc_path_str keys). Delete
the dead block; add a detect->redact TestClient regression guard.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wrap heavy endpoints so failures return a clean, mappable 500

**Files:**
- Modify: `backend/main.py` (`process_folder` ~105–124, `detect_pii` ~129–197, `redact_documents` ~202–283) — wrap each service call so an uncaught exception becomes `HTTPException(status_code=500, detail=...)` instead of a raw traceback
- Test: append to `tests/test_backend_redact.py`

**Context:** None of the three heavy endpoints catch exceptions from the service layer. A corrupt PDF or model error surfaces as a raw 500 whose body is a traceback string — which the frontend's `friendlyError` mapper (rule 29) cannot match, so the user sees a useless generic message. Wrapping in `try/except → HTTPException(500, detail="…")` gives a stable, mappable message. `HTTPException` itself must pass through unchanged (it is not an error to convert).

- [ ] **Step 1: Write the failing test.** Append to `tests/test_backend_redact.py`:

```python
from unittest.mock import patch


def test_detect_internal_error_returns_clean_500():
    """An unexpected service error must become a 500 with a string detail,
    not an unhandled raw traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs")

        with patch("backend.main.DetectionService") as MockSvc:
            MockSvc.return_value.detect_all.side_effect = RuntimeError("spaCy exploded")
            resp = client.post("/api/pii/detect", json={
                "pdf_paths": [str(pdf)],
                "student_name": "Joe Bloggs",
                "parent_names": [],
                "family_names": [],
                "organisation_names": [],
            })
    assert resp.status_code == 500
    detail = resp.json().get("detail", "")
    assert isinstance(detail, str) and len(detail) > 0
    assert "Detection failed" in detail


def test_detect_bad_path_still_returns_400():
    """A genuine client error (missing file) must remain a 400, not become a 500."""
    resp = client.post("/api/pii/detect", json={
        "pdf_paths": ["/no/such/file.pdf"],
        "student_name": "Joe Bloggs",
        "parent_names": [],
        "family_names": [],
        "organisation_names": [],
    })
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify failure:**
```bash
venv/bin/python3.13 -m pytest tests/test_backend_redact.py::test_detect_internal_error_returns_clean_500 tests/test_backend_redact.py::test_detect_bad_path_still_returns_400 -v
```
Expected: `test_detect_internal_error_returns_clean_500` FAILS — today TestClient re-raises the `RuntimeError` (it does not become a 500 with a `detail`). `test_detect_bad_path_still_returns_400` already PASSES.

- [ ] **Step 3: Wrap the three endpoints.** The pattern: keep the existing `HTTPException` raises (path checks) BEFORE the wrapped service call where possible, and wrap the service work in `try/except`, re-raising `HTTPException` untouched and converting everything else.

For `detect_pii` — wrap from the `service = DetectionService(...)` construction through the end of the response build. Change:
```python
    service = DetectionService(
        student_name=req.student_name,
        parent_names=req.parent_names,
        family_names=req.family_names,
        organisation_names=req.organisation_names,
        require_ner=True,
    )

    results = service.detect_all(pdf_paths)
```
to:
```python
    try:
        service = DetectionService(
            student_name=req.student_name,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            require_ner=True,
        )

        results = service.detect_all(pdf_paths)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection failed: {e}") from e
```
(The path-existence check above stays a 400. Everything after — the response/cache build — may stay outside the try; if you prefer, the cache-build loop can also live inside, but the failure point we must guard is `detect_all`.)

For `process_folder` — change:
```python
    service = ConversionService()
    results = service.process_folder(folder)
```
to:
```python
    try:
        service = ConversionService()
        results = service.process_folder(folder)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folder processing failed: {e}") from e
```

For `redact_documents` — wrap the service execution. Change:
```python
    service = RedactionService()
```
…through the line that calls `service.execute(...)` and builds the response. Locate the `service = RedactionService()` and the subsequent `results = service.execute(request)` (and response construction). Wrap them:
```python
    try:
        service = RedactionService()
        # ... existing RedactionRequest construction and results = service.execute(request) ...
        # ... existing response build ...
        return <existing RedactionResultsResponse(...)>
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redaction failed: {e}") from e
```
Implementer: read the actual body of `redact_documents` from `service = RedactionService()` to its `return`, and wrap exactly that span — do not change the logic inside, only indent it into the `try` and add the two `except` clauses. The cache-miss `HTTPException(400, ...)` raised earlier (before `service = RedactionService()`) stays outside the try and is unaffected.

- [ ] **Step 4: Add the matching frontend error mappings.** Open `desktop/src/lib/errorMessage.ts` and add patterns for the three new detail prefixes so the friendly mapper covers them (rule 29). Add, alongside the existing pattern checks, mappings for `/Detection failed/i`, `/Folder processing failed/i`, and `/Redaction failed/i` → a friendly "Something went wrong while {detecting PII|preparing your folder|redacting}. Please try again; if it keeps happening, restart the app." Then add three test cases to `desktop/tests/errorMessage.test.ts` mirroring the existing style:
```typescript
  it('maps "Detection failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Detection failed: spaCy exploded')))
      .toMatch(/detecting/i);
  });
  it('maps "Folder processing failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Folder processing failed: disk error')))
      .toMatch(/folder/i);
  });
  it('maps "Redaction failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Redaction failed: boom')))
      .toMatch(/redact/i);
  });
```
Implementer: read `desktop/src/lib/errorMessage.ts` first to match its exact structure (regex table vs if-chain) and keep the new entries consistent with it. The exact friendly wording is yours to choose, but each test's `toMatch` regex above must pass.

- [ ] **Step 5: Run both suites:**
```bash
venv/bin/python3.13 -m pytest tests/test_backend_redact.py -v
cd desktop && npm test 2>&1 | tail -8 ; cd ..
```
Expected: all backend redact tests PASS (including the two new 500/400 tests); all desktop `errorMessage` tests PASS including the three new ones.

- [ ] **Step 6: Commit:**
```bash
git add backend/main.py desktop/src/lib/errorMessage.ts desktop/tests/errorMessage.test.ts tests/test_backend_redact.py
git commit -m "fix(backend): convert uncaught endpoint errors to clean 500s

process_folder, detect_pii, redact_documents now wrap service calls and
re-raise non-HTTPException errors as HTTPException(500, detail=...), so the
frontend friendlyError mapper can show an actionable message instead of a raw
traceback. Adds matching error-message patterns + tests.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Give `api.ts` `request()` a default timeout

**Files:**
- Modify: `desktop/src/api.ts` (the `request` function, lines 14–30)
- Test: `desktop/tests/api.test.ts` (create)

**Context:** `request()` sets no timeout, so any wedged backend hangs the call forever (permanent loading overlay). Add a 60s internal timeout via an `AbortController`, composed with any caller-supplied `signal` (redact/processFolder pass one). A timeout (or network failure) maps to `BackendUnreachableError`; an **external** cancel must still surface as `AbortError` so callers' `if (e.name !== 'AbortError')` guards continue to suppress the toast.

- [ ] **Step 1: Write the failing test.** Create `desktop/tests/api.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, BackendUnreachableError } from '../src/api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('request timeout', () => {
  it('rejects with BackendUnreachableError when the backend never responds', async () => {
    vi.useFakeTimers();
    // fetch that only ever rejects when its signal aborts
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      }),
    );

    const p = api.health();
    const expectation = expect(p).rejects.toBeInstanceOf(BackendUnreachableError);
    await vi.advanceTimersByTimeAsync(60_000);
    await expectation;
  });

  it('propagates an external AbortError without converting it', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      }),
    );
    // processFolder forwards the caller signal into request()
    const p = api.processFolder('/some/folder', { signal: controller.signal });
    controller.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
  });
});
```

- [ ] **Step 2: Run to verify failure:**
```bash
cd desktop && npm test -- api.test.ts 2>&1 | tail -20 ; cd ..
```
Expected: the timeout test FAILS/hangs-then-fails (no timeout exists today), and the external-abort test may already pass. (If the whole run hangs, that itself confirms the missing timeout — the fix resolves it.)

- [ ] **Step 3: Apply the fix.** In `desktop/src/api.ts`, replace the `request` function:
```typescript
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') throw e;
    throw new BackendUnreachableError();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
```
with:
```typescript
const DEFAULT_TIMEOUT_MS = 60_000;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), DEFAULT_TIMEOUT_MS);
  const signal = options?.signal
    ? AbortSignal.any([options.signal, timeoutController.signal])
    : timeoutController.signal;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal,
    });
  } catch (e) {
    // An external cancel (the caller's own signal) must stay an AbortError so
    // callers can suppress the error toast. A timeout or network failure means
    // the backend is unreachable.
    if (options?.signal?.aborted) throw e;
    throw new BackendUnreachableError();
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 4: Run the test + typecheck:**
```bash
cd desktop && npm test -- api.test.ts 2>&1 | tail -20 && npm run build 2>&1 | tail -3 ; cd ..
```
Expected: both api tests PASS; `npm run build` (tsc) passes with no new errors.

- [ ] **Step 5: Commit:**
```bash
git add desktop/src/api.ts desktop/tests/api.test.ts
git commit -m "fix(desktop): add 60s default timeout to all backend requests

request() had no timeout, so a wedged backend left the UI hanging on a
permanent loading overlay. Add an AbortController timeout composed with any
caller signal; timeout/network failure -> BackendUnreachableError, external
cancel still surfaces as AbortError.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Give `detectPII` in `ConversionStatus` an AbortController

**Files:**
- Modify: `desktop/src/pages/ConversionStatus.tsx` (`handleContinue`, lines 48–77; the existing `abortRef` at line 23 is reused)
- Verification: `npm run build` (tsc) + `npm run lint` + diff review. **No unit test** — there is no React component test harness in this repo; do not invent one.

**Context:** `processFolder` already uses `abortRef` + a `useEffect` cleanup that aborts on unmount. `detectPII` in `handleContinue` does not, so clicking Back while detection is in flight lets the resolved promise call `setDetectionResults` + `navigateTo('document_review')`, overriding the user's Back. Reuse the same `abortRef` and skip the post-resolution work if the request was aborted.

- [ ] **Step 1: Apply the change.** In `ConversionStatus.tsx`, replace `handleContinue` (lines 48–77):
```typescript
  const handleContinue = async () => {
    if (!results) return;
    setLoading(true, 'Extracting text and detecting PII...');
    try {
      const allPdfs = [...results.pdf_files, ...results.converted_files];
      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const detection = await api.detectPII({
        pdf_paths: allPdfs,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
      });

      setDetectionResults(detection);
      const totalMatches = detection.documents.reduce((sum, d) => sum + d.matches.length, 0);
      if (totalMatches === 0) {
        navigateTo('no_pii_found');
      } else {
        navigateTo('document_review');
      }
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setLoading(false);
    }
  };
```
with:
```typescript
  const handleContinue = async () => {
    if (!results) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true, 'Extracting text and detecting PII...');
    try {
      const allPdfs = [...results.pdf_files, ...results.converted_files];
      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const detection = await api.detectPII({
        pdf_paths: allPdfs,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
      }, { signal: ctrl.signal });

      // If the user navigated away (Back) mid-request, do not force-navigate.
      if (ctrl.signal.aborted) return;

      setDetectionResults(detection);
      const totalMatches = detection.documents.reduce((sum, d) => sum + d.matches.length, 0);
      if (totalMatches === 0) {
        navigateTo('no_pii_found');
      } else {
        navigateTo('document_review');
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') setError(friendlyError(e));
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  };
```
Then update the Back button (line 223) to abort an in-flight detection before navigating. Replace:
```typescript
        <button
          onClick={() => navigateTo('folder_selection')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <ArrowLeft size={16} /> Back
        </button>
```
with:
```typescript
        <button
          onClick={() => { abortRef.current?.abort(); setLoading(false); navigateTo('folder_selection'); }}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <ArrowLeft size={16} /> Back
        </button>
```
Note: `api.detectPII` already accepts a second `options?: RequestInit` argument (verified in `api.ts`), so passing `{ signal }` is type-correct. `setLoading` is already destructured from the store in this component.

- [ ] **Step 2: Verify (typecheck + lint + review):**
```bash
cd desktop && npm run build 2>&1 | tail -3 && npm run lint 2>&1 | tail -6 ; cd ..
```
Expected: `npm run build` (tsc) passes; `npm run lint` shows **no increase** over the baseline 7 errors. Read the diff and confirm: the abort guard prevents post-Back navigation, the `finally` no longer clears loading after an abort (the Back handler owns that), and no other logic changed.

- [ ] **Step 3: Commit:**
```bash
git add desktop/src/pages/ConversionStatus.tsx
git commit -m "fix(desktop): cancel in-flight detection when leaving ConversionStatus

detectPII had no AbortController, so clicking Back while detection ran let the
resolved promise force-navigate to document_review. Reuse abortRef, guard the
post-resolution navigation, and abort on Back.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Detect unexpected backend death and spawn failure in Electron main

**Files:**
- Modify: `desktop/electron/main.cjs` (the `backendProcess.on('exit', …)` handler at ~104–106, the `startBackend` spawn at ~81–94, and add an `app.isQuitting` guard in the `before-quit`/`window-all-closed` handlers at ~248–265)
- Verification: `node --check desktop/electron/main.cjs` + `cd desktop && npm run lint` + diff review. **No unit test** — Electron main cannot be unit-run here.

**Context:** Today `backendProcess.on('exit')` only logs. If uvicorn dies mid-session the app silently shows the unreachable banner and polls forever with no "restart needed" prompt. A spawn failure (bad path, port 8765 in use) is unhandled. We add: (a) an `app.isQuitting` flag set during intentional shutdown so the exit handler can tell crash from clean quit; (b) an exit handler that, on an *unexpected* exit, shows a native error and quits; (c) a spawn `error` handler.

- [ ] **Step 1: Add the `isQuitting` flag at shutdown.** In `desktop/electron/main.cjs`, in BOTH the `window-all-closed` and `before-quit` handlers, set the flag before killing the backend. Replace:
```javascript
app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  app.quit();
});

app.on('before-quit', () => {
  if (updateCheckInterval) {
    clearInterval(updateCheckInterval);
    updateCheckInterval = null;
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
```
with:
```javascript
app.on('window-all-closed', () => {
  app.isQuitting = true;
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  app.quit();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (updateCheckInterval) {
    clearInterval(updateCheckInterval);
    updateCheckInterval = null;
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
```

- [ ] **Step 2: Upgrade the exit handler and add a spawn-error handler.** In `startBackend`, replace:
```javascript
  backendProcess.on('exit', (code) => {
    console.log(`Backend exited with code ${code}`);
  });
```
with:
```javascript
  backendProcess.on('exit', (code, signal) => {
    console.log(`Backend exited with code ${code}, signal ${signal}`);
    // An exit we did not initiate (app not shutting down) means the engine
    // crashed mid-session. The UI cannot recover without a restart.
    if (!app.isQuitting) {
      backendProcess = null;
      dialog.showErrorBox(
        'Redaction Engine Stopped',
        'The redaction engine stopped unexpectedly. The app will now close — please reopen it to continue.',
      );
      app.quit();
    }
  });

  backendProcess.on('error', (err) => {
    // The process could not be spawned at all (bad path, permissions, etc.).
    console.error('Failed to spawn backend:', err);
    if (!app.isQuitting) {
      dialog.showErrorBox(
        'Failed to Start',
        `The redaction engine could not be started.\n\n${err.message}\n\nPlease reinstall the application.`,
      );
      app.quit();
    }
  });
```

- [ ] **Step 3: Verify (syntax + lint + review):**
```bash
node --check "desktop/electron/main.cjs" && echo "syntax OK"
cd desktop && npm run lint 2>&1 | tail -6 ; cd ..
```
Expected: `syntax OK`; lint shows no increase over the baseline. Review the diff and confirm: `app.isQuitting` is set on every intentional-quit path before the backend is killed (so the exit handler won't fire the crash dialog during normal shutdown), and the crash/spawn dialogs only fire when `!app.isQuitting`.

- [ ] **Step 4: Manual smoke note (no automated test possible).** In the PR/handoff description, note that this path was verified by code review only and should be smoke-tested once in dev: run `cd desktop && npm run dev:electron`, then `kill` the spawned uvicorn process and confirm the app shows the "Redaction Engine Stopped" dialog and quits (rather than hanging on the unreachable banner). Do NOT claim this was done unless it actually was.

- [ ] **Step 5: Commit:**
```bash
git add desktop/electron/main.cjs
git commit -m "fix(desktop): detect backend crash and spawn failure in Electron main

The backend exit handler only logged; a mid-session uvicorn crash left the app
hanging on the unreachable banner. Add an app.isQuitting flag, show a native
'engine stopped' dialog and quit on unexpected exit, and handle spawn errors
(bad path / port in use).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Backend suite (compare to baseline 298 + new tests):**
```bash
venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -6
```
Expected: baseline 298 + new `test_backend_redact.py` tests, no new failures (same 5 pre-existing OCR-verification failures).

- [ ] **Desktop suite + typecheck + lint:**
```bash
cd desktop && npm test 2>&1 | tail -8 && npm run build 2>&1 | tail -3 && npm run lint 2>&1 | tail -6 ; cd ..
```
Expected: all vitest tests pass (errorMessage + routing + new api tests); `npm run build` passes; `npm run lint` error count unchanged from baseline (7).

- [ ] **Electron syntax:**
```bash
node --check "desktop/electron/main.cjs" && echo OK
```

- [ ] **Commit log & branch:**
```bash
git log --oneline -5
git rev-parse --abbrev-ref HEAD   # expect: test
```
Five new commits on `test`. **Do not push or merge** without explicit sign-off.

---

## Self-Review

**Spec coverage:** Findings #5 (Task 1), #10 (Task 2), #4 (Task 3), #8 (Task 4), #7 (Task 5) each map to a task with a defined verification gate. ✓

**Placeholder scan:** No TBD/TODO. Every code change shows exact old→new. The only deliberately-open items are the friendly-error *wording* (Task 2 Step 4) and Task 5's manual smoke note — both bounded by explicit pass criteria / honesty caveats, not placeholders. ✓

**Honesty about testing:** Tasks 4 and 5 are explicitly verified by typecheck/lint/`node --check`/review, NOT by fabricated unit tests, because no React/Electron test harness exists here. ✓

**Type/name consistency:** `api.detectPII(params, options?)` and `api.processFolder(folder, options?)` already accept a second `RequestInit` arg (verified in `api.ts`); `abortRef`, `setLoading`, `navigateTo` are already in `ConversionStatus`; `app`, `dialog`, `backendProcess`, `updateCheckInterval` are real in `main.cjs`; `DetectionService`, `ConversionService`, `RedactionService`, `HTTPException`, `_detection_cache` are real in `backend/main.py`. ✓

**Ordering/independence:** All five tasks are independent (no cross-task dependency). Task 2 touches `errorMessage.ts`/its test in addition to backend; no other task touches those files, so no conflict. ✓
