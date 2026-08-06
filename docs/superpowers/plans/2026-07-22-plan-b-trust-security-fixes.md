# Plan B: Trust & Security Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app's success screen honest (failed documents can never show green), make Cancel actually stop the backend, stop silent destruction of the user's review work, stop stale-folder results being processed, lock the local API down (token auth + pinned CORS + cleanup filename guard), and cache the spaCy model so detection isn't re-loading a 600 MB model per request.

**Architecture:** Backend changes in `backend/main.py` (+ `backend/schemas.py`), service/logger changes in `src/services/redaction_service.py` and `src/core/logger.py`, one engine change in `src/core/pii_orchestrator.py`, Electron changes in `desktop/electron/main.cjs` + `preload.cjs`, and frontend changes in `desktop/src/` (store, api client, three pages, one component). Python behaviour is TDD'd with pytest/TestClient; store and api-client logic is TDD'd with vitest; React components have no unit harness — they are verified with `npm run build` (tsc) + `npm run lint`.

**Tech Stack:** FastAPI + Starlette middleware, Electron 40 contextBridge/IPC, Zustand, vitest, pytest + fastapi TestClient.

> **Revision note (post senior review):** This plan was reviewed against the real codebase with runnable experiments before implementation. Six findings changed the design and are marked **[REV]** inline with the evidence that drove them. Do not "simplify" a `[REV]` decision back to the obvious-looking version — each one was measured.

## Global Constraints

- **Start by switching to the `test` branch** — `git branch --show-current` currently reports `main`, and repo policy is `test` → verify → merge to `main`. Run `git checkout test` before Task 1. Do NOT push or merge without the user's explicit go-ahead.
- Python tests: `venv/bin/python3.13 -m pytest` (never `venv/bin/pytest` — broken shebang). All existing tests must stay green.
- Desktop verification: `cd desktop && npm test` (vitest — baseline **24 passed**), `npm run build` (tsc), `npm run lint`. **ESLint baseline is exactly 7 errors + 2 warnings — the count must not increase.** `FinalConfirmation.tsx` and `DocumentCard.tsx` are already in the baseline error list; do not add new violations to them.
- Every new backend `HTTPException(detail=...)` string needs a pattern in `desktop/src/lib/errorMessage.ts` plus a test in `desktop/tests/errorMessage.test.ts` (repo rule #29).
- Conventional-commit subjects.
- No new dependencies (Python or npm). `secrets`, `threading`, and Electron's `crypto` are stdlib.
- Working directory: the repo root `/Users/davidarmstrong/Antigravity/redaction tool` (quote the path — it contains a space).

---

### Task 1: Cleanup endpoint — enforce redaction-output filename patterns

**Bug:** `/api/cleanup` deletes any `.pdf` inside a caller-supplied folder. Since users may set the output folder to the input folder, original (un-redacted) student PDFs are deletable. `/api/cleanup/list` already restricts itself to `*_redacted.pdf` / `*.UNVERIFIED.pdf` — the delete endpoint must match.

**Files:**
- Modify: `backend/main.py:437-462` (the `cleanup` endpoint)
- Test: `tests/test_cleanup_api.py`

**Interfaces:**
- Consumes: nothing.
- Produces: new failure `reason` string `"not a redaction output file"` in `CleanupResponse.failed` entries (no schema change — reason is free text).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cleanup_api.py` (match the existing `client.post` style in that file):

```python
    def test_rejects_pdf_not_matching_output_patterns(self, tmp_path):
        """An original student PDF must never be deletable via cleanup."""
        f = tmp_path / "original student report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert f.exists()
        assert "not a redaction output file" in r.json()["failed"][0]["reason"]

    def test_deletes_redacted_pattern(self, tmp_path):
        f = tmp_path / "report_redacted.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert not f.exists()

    def test_deletes_unverified_pattern(self, tmp_path):
        f = tmp_path / "report_redacted.UNVERIFIED.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert not f.exists()
```

- [ ] **Step 2: Run the tests to verify the first one fails**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_cleanup_api.py -k "output_patterns or deletes_redacted or deletes_unverified" -v
```

Expected: `test_rejects_pdf_not_matching_output_patterns` FAILS (file gets deleted); the other two PASS (regression guards).

- [ ] **Step 3: Add the filename-pattern check**

In `backend/main.py` `cleanup()`, after the existing `if path.suffix != ".pdf":` block, add:

```python
        if not (path.name.endswith("_redacted.pdf") or path.name.endswith(".UNVERIFIED.pdf")):
            failed.append(CleanupFailure(path=p, reason="not a redaction output file"))
            continue
```

(Keep the existing `"not a PDF"` check — an existing test asserts that reason for non-PDF files.)

- [ ] **Step 4: Run the cleanup suite**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_cleanup_api.py -v
```

Expected: ALL PASS (13 existing + 3 new). Every existing delete test uses `*_redacted.pdf` names, so none regress.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_cleanup_api.py
git commit -m "fix(backend): cleanup can only delete *_redacted.pdf and *.UNVERIFIED.pdf files"
```

---

### Task 2: API token auth + pinned CORS

**Bug:** `allow_origins=["*"]` + `allow_credentials=True` + no auth means any webpage in the user's browser can call the local API and read responses — including detecting PII in arbitrary local PDFs and deleting files. (A no-preflight "simple" POST reaches side-effecting endpoints regardless of CORS.) Fix: Electron generates a random per-session token, passes it to the backend via env and to the renderer via IPC; the backend rejects requests without it. When the env var is unset (manual `uvicorn`, pytest), auth is disabled so dev workflows are unchanged.

> **[REV-1] Middleware order is load-bearing.** Starlette's `add_middleware` does `user_middleware.insert(0, ...)`, so the **last-registered middleware is outermost**. Registering the token middleware after `add_middleware(CORSMiddleware, ...)` makes it outermost, so its 401 short-circuits *before* CORS runs and carries no `Access-Control-Allow-Origin`. In dev (renderer at `http://localhost:5173`, where CORS IS enforced) the browser then blocks the 401, `fetch` rejects, and `api.ts` reports "The redaction engine isn't responding" — the wrong message, plus health-poll banner flapping. Measured on the installed starlette 0.52.1: with the middleware defined *after* CORS, `has ACAO? False`; defined *before* CORS, `401 ACAO: http://localhost:5173`. **Therefore: define the `@app.middleware("http")` function ABOVE the `app.add_middleware(CORSMiddleware, ...)` call.**

> **[REV-2] Do not allow the `"null"` origin.** Measured with a real Electron 40.10.4 `loadFile` page fetching `http://127.0.0.1` with a JSON content-type and a custom header: the packaged app sends **no `Origin` header at all**, triggers **no preflight**, and succeeds even when the server emits **zero CORS headers** (`REQ POST /api/x Origin=undefined`). So pinning CORS does not break the packaged app — and `"null"` is precisely the origin sent by sandboxed iframes and `data:`/`blob:` documents, i.e. the attacker-controlled contexts we are excluding. Pin the two Vite dev origins only.

> **[REV-3] Deliver the token by IPC, not `additionalArguments`.** `additionalArguments` does work (verified in Electron 40.10.4 with `contextIsolation: true` — the arg appears in preload's `process.argv` and reaches the renderer), but it puts the token in the renderer helper's real command line, readable via `ps aux` by any other user on a shared staffroom machine. `ipcMain.handle` costs nothing extra since `request()` is already async.

**Files:**
- Modify: `backend/main.py` (imports, middleware, CORS)
- Modify: `desktop/electron/main.cjs` (token generation, backend env, IPC handler)
- Modify: `desktop/electron/preload.cjs` (`getApiToken` bridge)
- Modify: `desktop/src/electron.d.ts` (add `getApiToken`)
- Modify: `desktop/src/api.ts` (cached token + `X-Api-Token` header)
- Modify: `desktop/src/lib/errorMessage.ts` (map the 401 detail)
- Modify: `desktop/vite.config.ts` (`strictPort`)
- Create: `tests/test_api_auth.py`
- Test: `desktop/tests/api.test.ts`, `desktop/tests/errorMessage.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: env var `REDACTION_API_TOKEN` (backend reads per-request); request header `X-Api-Token`; IPC channel `get-api-token`; `window.electronAPI.getApiToken?: () => Promise<string>`; `__resetApiTokenCache()` exported from `api.ts` (test-only); 401 detail string `"Invalid or missing API token"`.

- [ ] **Step 1: Write the failing backend tests**

Create `tests/test_api_auth.py`. First check how `tests/test_cleanup_api.py` bootstraps its imports and TestClient, and copy that exact style; the shape is:

```python
"""API token auth: enabled only when REDACTION_API_TOKEN is set (Electron sets it)."""

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


class TestApiTokenAuth:
    def test_auth_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("REDACTION_API_TOKEN", raising=False)
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"})
        assert r.status_code == 200

    def test_request_without_token_rejected_when_env_set(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"})
        assert r.status_code == 401
        assert "API token" in r.json()["detail"]

    def test_request_with_wrong_token_rejected(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "wrong"})
        assert r.status_code == 401

    def test_request_with_token_accepted(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "sekrit-token"})
        assert r.status_code == 200

    def test_health_exempt_for_startup_polling(self, monkeypatch):
        """Electron's waitForBackend polls /api/health with no token."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        assert client.get("/api/health").status_code == 200

    def test_non_ascii_token_header_returns_401_not_500(self, monkeypatch):
        """secrets.compare_digest raises TypeError on non-ASCII str — must not 500."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "tökén"})
        assert r.status_code == 401

    def test_401_response_carries_cors_header(self, monkeypatch):
        """The renderer must be able to READ the 401 in dev, not just receive it."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 401
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_api_auth.py -v
```

Expected: the "rejected", non-ASCII, and CORS-header tests FAIL (everything currently returns 200).

- [ ] **Step 3: Implement the backend middleware and pin CORS**

In `backend/main.py`, add `import secrets` to the imports (`os` is already imported at line 7 — do not re-add it), and change the fastapi imports to:

```python
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
```

Now replace the entire existing CORS block with the following. **Order matters — the token middleware is defined FIRST so that CORSMiddleware, registered last, ends up outermost and can attach CORS headers to the 401 (see [REV-1]):**

```python
# ── API token auth ────────────────────────────────────────────────────────
# The Electron shell generates a random per-session token, passes it to this
# process via REDACTION_API_TOKEN, and the renderer sends it on every request.
# Requests without the token are rejected, so a webpage open in the user's
# browser cannot drive this API. When the env var is unset (manual `uvicorn`
# runs, pytest), auth is disabled.
#
# Registered BEFORE CORSMiddleware on purpose: Starlette's add_middleware
# inserts at index 0, so the LAST registration is outermost. Defining this
# first leaves CORS outermost, which is what lets a 401 carry the
# Access-Control-Allow-Origin header the dev renderer needs to read it.
@app.middleware("http")
async def require_api_token(request: Request, call_next):
    expected = os.environ.get("REDACTION_API_TOKEN", "")
    if expected and request.method != "OPTIONS" and request.url.path != "/api/health":
        provided = request.headers.get("x-api-token", "")
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str,
        # which would turn a bad header into a 500 + traceback.
        if not secrets.compare_digest(
            provided.encode("utf-8", "ignore"), expected.encode("utf-8")
        ):
            return JSONResponse(status_code=401,
                                content={"detail": "Invalid or missing API token"})
    return await call_next(request)


# Allow the Electron/Vite frontend to connect. Origins are pinned to the Vite
# dev server only. The packaged app loads via file:// and sends NO Origin
# header, triggers no preflight, and works with no CORS headers at all — so it
# needs no entry here. "null" is deliberately NOT allowed: that is the origin
# sandboxed iframes and data:/blob: documents send. The real access control is
# the API token above; CORS only stops browser pages reading responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: Run the backend auth tests plus the existing backend suites**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_api_auth.py tests/test_cleanup_api.py tests/test_backend_redact.py tests/test_manual_pii.py tests/test_text_extractor.py -v
```

Expected: ALL PASS. Existing backend tests run without the env var, so auth stays disabled for them (`os.environ` is read per-request, so `monkeypatch` works).

- [ ] **Step 5: Wire the token through Electron via IPC**

In `desktop/electron/main.cjs`:

1. After `const { autoUpdater } = require('electron-updater');`, add:

```js
const crypto = require('crypto');

// Per-session shared secret between the renderer and the Python backend.
// Passed to the backend via env and handed to the renderer over IPC (NOT via
// additionalArguments, which would expose it in `ps` output on a shared machine).
const API_TOKEN = crypto.randomBytes(32).toString('hex');
```

2. In `startBackend()`, add to the spawn `env` object, after `TESSDATA_PREFIX: ...`:

```js
      REDACTION_API_TOKEN: API_TOKEN,
```

3. Alongside the existing `ipcMain.handle(...)` registrations (search for `ipcMain.handle('select-folder'`), add:

```js
ipcMain.handle('get-api-token', () => API_TOKEN);
```

In `desktop/electron/preload.cjs`, add to the `exposeInMainWorld('electronAPI', { ... })` object, after `isElectron: true,`:

```js
  getApiToken: () => ipcRenderer.invoke('get-api-token'),
```

In `desktop/src/electron.d.ts`, add to the `electronAPI` interface after `isElectron: boolean;`:

```ts
      getApiToken?: () => Promise<string>;
```

- [ ] **Step 6: Send the header from the API client**

In `desktop/src/api.ts`, add above `async function request<T>(...)`:

```ts
// The API token is fetched once over IPC and cached for the session.
// Outside Electron (vitest, browser dev without the shell) it resolves to ''
// and no header is sent — the backend then has auth disabled too.
let tokenPromise: Promise<string> | null = null;

function getApiToken(): Promise<string> {
  if (!tokenPromise) {
    const getter = typeof window === 'undefined' ? undefined : window.electronAPI?.getApiToken;
    tokenPromise = getter ? getter().catch(() => '') : Promise.resolve('');
  }
  return tokenPromise;
}

/** Test-only: drop the cached token so each test can stub its own. */
export function __resetApiTokenCache() {
  tokenPromise = null;
}
```

Then inside `request()`, replace:

```ts
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal,
    });
```

with:

```ts
    const token = await getApiToken();
    res = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'X-Api-Token': token } : {}),
      },
      ...options,
      signal,
    });
```

- [ ] **Step 7: Write the frontend tests**

In `desktop/tests/api.test.ts`, first extend the existing `afterEach` — `restoreAllMocks()` does NOT undo `stubGlobal`, so a stubbed `window` would leak into later tests:

```ts
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  __resetApiTokenCache();
});
```

and add `__resetApiTokenCache` to the import from `../src/api`. Then add:

```ts
describe('api token header', () => {
  it('sends X-Api-Token when Electron provides one', async () => {
    let captured: Record<string, string> = {};
    vi.stubGlobal('window', { electronAPI: { getApiToken: () => Promise.resolve('tok-123') } });
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) => {
      captured = (opts.headers ?? {}) as Record<string, string>;
      return Promise.resolve(new Response(JSON.stringify({ status: 'ok', version: 'x' })));
    });
    await api.health();
    expect(captured['X-Api-Token']).toBe('tok-123');
  });

  it('omits the header outside Electron', async () => {
    let captured: Record<string, string> = {};
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) => {
      captured = (opts.headers ?? {}) as Record<string, string>;
      return Promise.resolve(new Response(JSON.stringify({ status: 'ok', version: 'x' })));
    });
    await api.health();
    expect(captured['X-Api-Token']).toBeUndefined();
  });

  it('surfaces the 401 detail as a readable Error (the real network path)', async () => {
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', () =>
      Promise.resolve(new Response(
        JSON.stringify({ detail: 'Invalid or missing API token' }),
        { status: 401 },
      )),
    );
    await expect(api.health()).rejects.toThrow('Invalid or missing API token');
  });
});
```

In `desktop/src/lib/errorMessage.ts`, add to the `PATTERNS` array:

```ts
  [/api token/i, "The app couldn't authenticate with its redaction engine. Please restart the app."],
```

Add to `desktop/tests/errorMessage.test.ts` (match its existing style):

```ts
  it('maps the API token 401 detail', () => {
    expect(friendlyError(new Error('Invalid or missing API token'))).toBe(
      "The app couldn't authenticate with its redaction engine. Please restart the app."
    );
  });
```

- [ ] **Step 8: Pin the Vite dev port**

The CORS allow-list hardcodes port 5173, but `desktop/vite.config.ts` has no `strictPort`, so Vite silently falls back to 5174 if 5173 is busy — and every request would then be rejected. In `desktop/vite.config.ts`, add to the config's `server` block (create the block if absent):

```ts
  server: {
    port: 5173,
    strictPort: true,
  },
```

(This also makes the existing `wait-on http://localhost:5173` in the dev script honest.)

- [ ] **Step 9: Run all verification**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test && npm run build && npm run lint && node --check electron/main.cjs && node --check electron/preload.cjs
```

Expected: vitest green (24 baseline + 3 new + 1 errorMessage), tsc clean, lint at exactly 7 errors + 2 warnings, both `.cjs` files parse.

- [ ] **Step 10: Manual smoke test (dev mode)**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm run dev:electron
```

Expected: the app starts and the dependency check on the Setup/Conversion screen succeeds — this proves the token round-trips end to end (Electron → env → backend, and IPC → renderer → header). If you instead see "The redaction engine isn't responding", the middleware order is wrong — re-read [REV-1]. Quit the app afterwards.

- [ ] **Step 11: Commit**

```bash
git add backend/main.py tests/test_api_auth.py desktop/electron/main.cjs desktop/electron/preload.cjs desktop/src/electron.d.ts desktop/src/api.ts desktop/src/lib/errorMessage.ts desktop/vite.config.ts desktop/tests/api.test.ts desktop/tests/errorMessage.test.ts
git commit -m "fix(security): per-session API token auth and pinned CORS origins"
```

---

### Task 3: Cache the spaCy NLP engine per process

**Bug:** every `/api/pii/detect` and `/api/dependencies/check` builds a new `AnalyzerEngine`, re-creating the spaCy engine each time. Measured cost: `create_engine` takes **0.61 s** while the `AnalyzerEngine` construction itself is **0.01 s** — so caching the NLP engine (and only that) recovers essentially all of the avoidable work. Note this is ~0.6 s per call, not a multi-second win: the 3.5 s first-call figure is one-off module import, which caching does not touch. The Setup screen's "Check Again" button pays this on every click.

**Files:**
- Modify: `src/core/pii_orchestrator.py` (module-level cache + `_init_presidio`)
- Test: `tests/test_pii_orchestrator.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_get_shared_nlp_engine()` module-level function in `pii_orchestrator.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pii_orchestrator.py` (ensure `import pytest` exists at the top):

```python
class TestNlpEngineCache:
    def test_nlp_engine_shared_between_orchestrators(self):
        o1 = PIIOrchestrator("Amy One")
        o2 = PIIOrchestrator("Ben Two")
        if o1.presidio_analyzer is None or o2.presidio_analyzer is None:
            pytest.skip("Presidio/spaCy not available in this environment")
        assert o1.presidio_analyzer.nlp_engine is o2.presidio_analyzer.nlp_engine, \
            "spaCy NLP engine must be loaded once per process, not per orchestrator"
```

(`AnalyzerEngine.nlp_engine` is confirmed to exist on the installed presidio-analyzer 2.2.361.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py::TestNlpEngineCache -v
```

Expected: FAIL (two distinct engine objects).

- [ ] **Step 3: Implement the cache**

In `src/core/pii_orchestrator.py`, add after the imports:

```python
import threading

# The spaCy model behind Presidio takes ~0.6s to wire up per call. Load it
# once per process and share it across orchestrators — the AnalyzerEngine
# itself is ~0.01s and stays per-orchestrator, because StudentNameRecognizer
# is parameterised with each run's name variations.
_NLP_ENGINE = None
_NLP_ENGINE_LOCK = threading.Lock()


def _get_shared_nlp_engine():
    """Create the spaCy NLP engine on first use; return the cached one after."""
    global _NLP_ENGINE
    with _NLP_ENGINE_LOCK:
        if _NLP_ENGINE is None:
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            })
            _NLP_ENGINE = provider.create_engine()
        return _NLP_ENGINE
```

In `_init_presidio`, replace:

```python
            # Create NLP engine with spaCy
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            })
            nlp_engine = provider.create_engine()
```

with:

```python
            # Shared, cached NLP engine (see _get_shared_nlp_engine)
            nlp_engine = _get_shared_nlp_engine()
```

and remove the now-unused `from presidio_analyzer.nlp_engine import NlpEngineProvider` import from `_init_presidio`'s try block (it moved into the helper).

- [ ] **Step 4: Run the orchestrator + backend suites**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py tests/test_backend_redact.py tests/test_manual_pii.py -v
```

Expected: ALL PASS. The lock is non-reentrant and held only across creation — no deadlock path under FastAPI's threadpool.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_orchestrator.py tests/test_pii_orchestrator.py
git commit -m "perf(orchestrator): load the spaCy NLP engine once per process"
```

---

### Task 4: Honest completion screen — failed documents can never look green

**Bug:** `Completion.tsx` derives `hasFailures` only from `verification_failures`. A document whose redaction errored (`success: false`, `error_message` set, empty `verification_failures`) still gets the green "All N documents redacted successfully" banner, and `DocumentCard` renders it with a green tick. `DocumentResult` already carries `success` and `error_message` (`desktop/src/types.ts:64-72`) — this is pure UI wiring.

> **[REV-4] Do not double-report.** `redaction_service._process_document:276-290` sets `success = False` **and** populates `verification_failures` **and** quarantines, all for one document. A naive `filter(d => !d.success)` therefore lists every verification failure a second time, in a second red box, under a misleading fallback message. The failed-documents section must exclude documents that already appear in the verification-failures section, and `DocumentCard`'s existing "Verification failed" box must be conditioned on `verification_failures` rather than on the combined flag.

**Files:**
- Modify: `desktop/src/pages/Completion.tsx` (failure derivation, banner, new section)
- Modify: `desktop/src/components/DocumentCard.tsx` (status derivation + expanded panel)

**Interfaces:**
- Consumes: `DocumentResult.success` / `DocumentResult.error_message` (already in `types.ts`).
- Produces: none (UI only).

- [ ] **Step 1: Update Completion.tsx**

Replace:

```ts
  const r = redactionResults;
  const hasFailures = r.verification_failures.length > 0;
  const hasOcrWarnings = r.ocr_warnings.length > 0;
```

with:

```ts
  const r = redactionResults;
  // Documents that errored outright. Verification failures are reported in
  // their own section — excluded here so one document never fills two red boxes.
  const erroredDocs = r.document_results.filter(
    (d) => !d.success && d.verification_failures.length === 0
  );
  const hasVerificationFailures = r.verification_failures.length > 0;
  const hasFailures = hasVerificationFailures || erroredDocs.length > 0;
  const hasOcrWarnings = r.ocr_warnings.length > 0;
```

Replace the banner `<h3>` block:

```tsx
        <h3 className={`text-lg font-semibold ${hasFailures ? 'text-amber-800' : 'text-emerald-800'}`}>
          {hasFailures
            ? 'Completed with warnings'
            : `All ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} redacted successfully`}
        </h3>
```

with:

```tsx
        <h3 className={`text-lg font-semibold ${hasFailures ? 'text-amber-800' : 'text-emerald-800'}`}>
          {hasFailures
            ? `${r.successfully_redacted} of ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} redacted — review the issues below`
            : `All ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} redacted successfully`}
        </h3>
```

Change the existing verification-failures block's condition from `{hasFailures && (` to:

```tsx
      {hasVerificationFailures && (
```

Then, immediately after that block's closing `)}`, add the errored-documents section:

```tsx
      {/* Documents that errored before producing a redacted copy */}
      {erroredDocs.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <XCircle size={16} />
            {erroredDocs.length} document{erroredDocs.length === 1 ? '' : 's'} could not be redacted
            <HelpTip text="These documents hit an error during redaction, so no redacted copy was produced for them. The originals are untouched — do not share these documents until the problem is resolved." />
          </div>
          {erroredDocs.map((d, i) => (
            <p key={i} className="text-xs text-red-500 py-0.5">
              {d.document_name}: {d.error_message || 'Redaction did not complete.'}
            </p>
          ))}
        </motion.div>
      )}
```

- [ ] **Step 2: Update DocumentCard.tsx**

Replace:

```ts
  const hasWarnings = result.ocr_warnings.length > 0;
  const hasFails = result.verification_failures.length > 0;
```

with:

```ts
  const hasWarnings = result.ocr_warnings.length > 0;
  const verificationFailed = result.verification_failures.length > 0;
  // Any unsuccessful document gets the failure treatment, whether it failed
  // verification or errored outright.
  const hasFails = verificationFailed || !result.success;
```

In the expanded panel, change the existing failure block's condition from `{hasFails && (` to `{verificationFailed && (` so its "Verification failed — review this document manually." text only appears for actual verification failures. Then add immediately after it:

```tsx
              {!result.success && !verificationFailed && (
                <div className="mt-3 bg-rose-50 rounded-lg px-3 py-2">
                  <p className="text-xs text-rose-600">
                    {result.error_message || 'Redaction did not complete for this document.'}
                  </p>
                </div>
              )}
```

- [ ] **Step 3: Verify**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm run build && npm run lint
```

Expected: tsc clean; lint at exactly 7 errors + 2 warnings (`DocumentCard.tsx` is in the baseline — do not add new violations).

- [ ] **Step 4: Commit**

```bash
git add desktop/src/pages/Completion.tsx desktop/src/components/DocumentCard.tsx
git commit -m "fix(desktop): failed documents can no longer render as successful on the completion screen"
```

---

### Task 5: Real server-side cancel for redaction

**Bug:** Cancel during redaction aborts the fetch but the backend keeps redacting every document; the UI then lists "partial output" from a stale directory scan while files keep appearing. Fix: cooperative cancellation — a `/api/redact/cancel` endpoint sets a flag; the service checks it between documents; the frontend **keeps the original request alive** and gets accurate partial results back. Also: the client's blanket 60s timeout would abort long redactions/detections — give those two calls a 30-minute budget.

> **[REV-5] Quarantined files must stay visible.** When verification fails, `redaction_service.py:288` sets `output_path = None` and moves the file to `quarantine_path`. Building the cancel screen's file list from `output_path` alone therefore drops `.UNVERIFIED.pdf` files written during the run — leaving a possibly-unredacted file on disk that the "Delete partial output" button cannot remove. `quarantine_path` exists on the dataclass but is NOT currently in the response model; expose it and include it in the list.

**Files:**
- Modify: `src/core/logger.py` (cancel notice in the audit log)
- Modify: `src/services/redaction_service.py` (`RedactionResults.cancelled`, `execute(should_cancel=...)`)
- Modify: `backend/main.py` (`_redaction_control`, `/api/redact/cancel`, wire-through, response fields)
- Modify: `backend/schemas.py` (`DocumentResultResponse.quarantine_path`, `RedactionResultsResponse.cancelled`)
- Modify: `desktop/src/types.ts` (`DocumentResult.quarantine_path`, `RedactionResults.cancelled`)
- Modify: `desktop/src/api.ts` (per-call timeout, `cancelRedaction`)
- Modify: `desktop/src/pages/FinalConfirmation.tsx` (cancel flow rework)
- Test: `tests/test_backend_redact.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RedactionLogger.set_cancelled(cancelled: bool = True)`; `RedactionService.execute(request, should_cancel: Optional[Callable[[], bool]] = None)`; `RedactionResults.cancelled: bool`; `DocumentResultResponse.quarantine_path: Optional[str]`; `POST /api/redact/cancel` → `{"status": "cancel_requested"}`; `api.cancelRedaction()`; `request()` third parameter `timeoutMs: number`.

- [ ] **Step 1: Write the failing Python tests**

Add to `tests/test_backend_redact.py` (match its existing import/bootstrap style):

```python
class TestRedactionCancel:
    def _make_request(self, tmp_path, names):
        import fitz
        from src.services.redaction_service import RedactionRequest

        docs = []
        for name in names:
            p = tmp_path / name
            d = fitz.open()
            pg = d.new_page()
            pg.insert_text((72, 72), f"Document {name}")
            d.save(str(p))
            d.close()
            docs.append(p)

        detected = {p: {"matches": [], "text_data": {"pages": {}, "ocr_pages": []}}
                    for p in docs}
        return RedactionRequest(
            folder_path=tmp_path,
            student_name="Test Student",
            documents=docs,
            detected_pii=detected,
            user_selections={},
        )

    def test_execute_stops_between_documents_when_cancelled(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
        # execute() calls should_cancel() exactly once per iteration, before
        # processing: first returns False (doc 1 runs), second returns True.
        flags = iter([False, True])
        results = RedactionService().execute(req, should_cancel=lambda: next(flags))

        assert results.cancelled is True
        assert len(results.document_results) == 1

    def test_execute_without_cancel_processes_all(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf"))
        results = RedactionService().execute(req)
        assert results.cancelled is False
        assert len(results.document_results) == 2

    def test_cancelled_run_is_recorded_in_the_audit_log(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
        flags = iter([False, True])
        results = RedactionService().execute(req, should_cancel=lambda: next(flags))
        assert "RUN CANCELLED" in results.log_content

    def test_cancel_endpoint_sets_flag(self):
        from backend import main as backend_main

        backend_main._redaction_control["cancel_requested"] = False
        try:
            r = client.post("/api/redact/cancel")
            assert r.status_code == 200
            assert backend_main._redaction_control["cancel_requested"] is True
        finally:
            # Never leave the flag set — a later test would phantom-cancel.
            backend_main._redaction_control["cancel_requested"] = False
```

(These tests use empty selections, so no OCR verification runs and Tesseract is not required. Verified: the fixture writes only into `tmp_path`.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_backend_redact.py -k Cancel -v
```

Expected: FAIL — `execute() got an unexpected keyword argument 'should_cancel'` / 404 on the cancel endpoint.

- [ ] **Step 3: Add the cancel notice to the audit log**

In `src/core/logger.py`, add to `RedactionLogger.__init__` after `self.successfully_redacted = 0`:

```python
        self.cancelled = False
```

Add this method after `set_totals`:

```python
    def set_cancelled(self, cancelled: bool = True):
        """Mark the run as user-cancelled so the audit log says so."""
        self.cancelled = cancelled
```

In `generate_log`, after the `lines.append(f"Flagged for manual review: {len(self.flagged_files)}")` line, add:

```python
        if self.cancelled:
            lines.append(
                f"RUN CANCELLED BY USER — {self.successfully_redacted} of "
                f"{self.total_documents} documents were processed"
            )
```

- [ ] **Step 4: Implement service-side cancellation**

In `src/services/redaction_service.py`:

1. Add `cancelled` to `RedactionResults`:

```python
@dataclass
class RedactionResults:
    """Complete results from a redaction run"""
    redacted_folder: Path
    document_results: List[DocumentResult] = field(default_factory=list)
    log_content: str = ""
    log_path: Optional[Path] = None
    cancelled: bool = False
```

2. Change the `execute` signature:

```python
    def execute(self, request: RedactionRequest, should_cancel=None) -> RedactionResults:
```

3. Replace the document loop's opening:

```python
        for doc in request.documents:
            doc_result = self._process_document(
```

with:

```python
        for doc in request.documents:
            # Cooperative cancel: the API layer flips a flag when the user
            # clicks Cancel; we stop cleanly between documents.
            if should_cancel is not None and should_cancel():
                results.cancelled = True
                break
            doc_result = self._process_document(
```

4. In the "Finalise log" section, insert before `results.log_content = logger.generate_log()`:

```python
        if results.cancelled:
            logger.set_cancelled(True)
```

- [ ] **Step 5: Implement the API layer**

In `backend/schemas.py`, add to `DocumentResultResponse`:

```python
    quarantine_path: Optional[str] = None
```

and to `RedactionResultsResponse`:

```python
    cancelled: bool = False
```

In `backend/main.py`:

1. Add near `_detection_cache`:

```python
# Cooperative cancel flag for the (single) in-flight redaction run.
_redaction_control = {"cancel_requested": False}
```

2. Add the endpoint just above `redact_documents`:

```python
@app.post("/api/redact/cancel")
def cancel_redaction():
    """Ask an in-flight /api/redact run to stop after the current document."""
    _redaction_control["cancel_requested"] = True
    return {"status": "cancel_requested"}
```

3. As the FIRST statement in `redact_documents`'s body:

```python
    _redaction_control["cancel_requested"] = False
```

4. Change the execute call to:

```python
        results = service.execute(
            request,
            should_cancel=lambda: _redaction_control["cancel_requested"],
        )
```

5. In the `DocumentResultResponse(...)` construction inside the list comprehension, add:

```python
                    quarantine_path=str(r.quarantine_path) if r.quarantine_path else None,
```

6. In the `RedactionResultsResponse(...)` kwargs, add:

```python
            cancelled=results.cancelled,
```

- [ ] **Step 6: Run the Python tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_backend_redact.py tests/test_manual_pii.py tests/test_cleanup_api.py -v
```

Expected: ALL PASS.

- [ ] **Step 7: Frontend — types and API client**

In `desktop/src/types.ts`, add to `DocumentResult`:

```ts
  quarantine_path: string | null;
```

and to `RedactionResults`:

```ts
  cancelled: boolean;
```

In `desktop/src/api.ts`:

1. Give `request` a per-call timeout — replace its signature and the `setTimeout` line:

```ts
async function request<T>(
  path: string,
  options?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);
```

(Every existing call site passes `options` second, so adding a third parameter is backward-compatible.)

2. Long-running calls get a 30-minute budget. In `detectPII`, change the closing of its `request(...)` call from `}, options?...)` form to pass the timeout as the third argument:

```ts
    request<import('./types').DetectionResults>('/api/pii/detect', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),
```

Apply the identical change to the `request(...)` call inside `redact` (append `, 30 * 60_000` after its options object).

3. Add after `redact`:

```ts
  cancelRedaction: () =>
    request<{ status: string }>('/api/redact/cancel', { method: 'POST' }),
```

- [ ] **Step 8: Frontend — FinalConfirmation cancel flow**

In `desktop/src/pages/FinalConfirmation.tsx`:

1. Replace `const abortRef = useRef<AbortController | null>(null);` with:

```ts
  const cancelRequestedRef = useRef(false);
  const [cancelPending, setCancelPending] = useState(false);
```

2. Replace `handleRedact` with:

```ts
  const handleRedact = async () => {
    setRedacting(true);
    cancelRequestedRef.current = false;
    setCancelPending(false);
    const resolvedOutputPath = outputMode === 'custom' && customPath
      ? customPath
      : `${folderPath}/redacted`;
    setLastOutputPath(resolvedOutputPath);
    try {
      const selectedKeys: string[] = [];
      for (const doc of detectionResults.documents) {
        doc.matches.forEach((_, idx) => {
          const key = `${doc.path}_${idx}`;
          if (userSelections[key]) selectedKeys.push(key);
        });
      }

      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const results = await api.redact({
        folder_path: folderPath,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
        redact_header_footer: redactHeaderFooter,
        documents: detectionResults.documents.map((d) => d.path),
        detected_pii: Object.fromEntries(
          detectionResults.documents.map((d) => [d.path, d.matches])
        ),
        selected_keys: selectedKeys,
        folder_action: null,
        custom_output_path: outputMode === 'custom' ? customPath : null,
      });

      if (cancelRequestedRef.current || results.cancelled) {
        // The backend stopped between documents, so its results ARE the
        // accurate partial-output list — no directory guessing needed.
        // Quarantined (.UNVERIFIED.pdf) files have no output_path, so include
        // quarantine_path or they'd be invisible to "Delete partial output".
        setPartialFiles(
          results.document_results
            .map((d) => d.output_path || d.quarantine_path)
            .filter((p): p is string => Boolean(p))
        );
        setRedactionResults(results);
        setCancelled(true);
        return;
      }

      setRedactionResults(results);
      navigateTo('completion');
    } catch (e: any) {
      if (cancelRequestedRef.current) {
        // Cancel was requested but the request itself failed — fall back to
        // listing whatever redaction outputs exist on disk.
        try {
          const list = await api.cleanupList(resolvedOutputPath);
          setPartialFiles(list.files);
        } catch {
          setPartialFiles([]);
        }
        setCancelled(true);
      } else {
        if (/no cached detection data/i.test(e?.message ?? '')) {
          // Server-side cache is gone — force a fresh detection run next time
          // (see Task 6; without this the wizard can loop forever).
          useStore.getState().setDetectionParamsKey('');
        }
        setError(friendlyError(e));
      }
    } finally {
      setRedacting(false);
    }
  };
```

3. Replace the cancel button inside the `if (redacting)` screen:

```tsx
          <button
            onClick={async () => {
              if (cancelPending) return;
              if (!confirm('Stop after the current document finishes? Documents already redacted will remain in the output folder.')) {
                return;
              }
              cancelRequestedRef.current = true;
              setCancelPending(true);
              try {
                await api.cancelRedaction();
              } catch {
                // The backend may have already finished — the in-flight redact
                // response will resolve normally and we handle it there.
              }
            }}
            disabled={cancelPending}
            className="px-4 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors btn-press"
          >
            {cancelPending ? 'Stopping after current document…' : 'Cancel'}
          </button>
```

The redacting screen stays visible while `cancelPending` is true; the request resolves when the backend stops, then the existing Cancelled screen renders with accurate results.

- [ ] **Step 9: Verify**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test && npm run build && npm run lint
```

Expected: vitest green, tsc clean, lint at exactly 7 errors + 2 warnings. (`FinalConfirmation.tsx` is in the lint baseline — keep the `useRef` import, it is still used by `cancelRequestedRef`.)

- [ ] **Step 10: Commit**

```bash
git add src/core/logger.py src/services/redaction_service.py backend/main.py backend/schemas.py desktop/src/types.ts desktop/src/api.ts desktop/src/pages/FinalConfirmation.tsx tests/test_backend_redact.py
git commit -m "fix(redaction): cancel now stops the backend between documents and reports accurate partial output"
```

---

### Task 6: Preserve review work across back-navigation

**Bug:** going Back from review and clicking Continue re-runs detection, which clears the server cache and resets every selection — silently destroying manual PII entries the user typed in because the detector missed them. Fix: fingerprint the detection inputs; if unchanged, skip re-detection (the server cache is still valid — `_detection_cache.clear()` is called only in `detect_pii`, and `/api/pii/manual` only appends); if changed, warn before discarding review work.

> **[REV-6] The skip path needs an escape hatch.** The frontend fingerprint and the backend cache live in different processes. If they desync — backend restarted independently (the documented dev workflow runs `uvicorn` separately), or any recovery after `backendReachable` flipped false — the wizard becomes an inescapable loop: Continue skips detection → redact returns `400 "No cached detection data"` → the error tells the user to go back one step → Continue skips detection again, forever. Before this change that state was self-healing because detection always re-ran. So: **any code path that sees a "no cached detection data" error must clear `detectionParamsKey`**, and losing backend reachability must clear it too.

**Files:**
- Modify: `desktop/src/store.ts` (add `detectionParamsKey` + setter; clear it in `setBackendReachable(false)`)
- Modify: `desktop/src/pages/ConversionStatus.tsx` (`handleContinue`)
- Modify: `desktop/src/pages/DocumentReview.tsx` (clear the key on a manual-PII cache miss)
- Test: `desktop/tests/store.test.ts`

**Interfaces:**
- Consumes: `PIIMatch.source === 'manual'` (existing field); `FinalConfirmation`'s cache-miss handler from Task 5 Step 8.
- Produces: store key `detectionParamsKey: string`, action `setDetectionParamsKey(key: string)`.

- [ ] **Step 1: Write the failing store tests**

Add to `desktop/tests/store.test.ts`:

```ts
describe('store: detectionParamsKey', () => {
  beforeEach(() => {
    useStore.getState().reset();
  });

  it('stores the key and clears it on reset', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    expect(useStore.getState().detectionParamsKey).toBe('fingerprint-1');
    useStore.getState().reset();
    expect(useStore.getState().detectionParamsKey).toBe('');
  });

  it('clears the key when the backend becomes unreachable', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    useStore.getState().setBackendReachable(false);
    expect(useStore.getState().detectionParamsKey).toBe('');
  });

  it('keeps the key when the backend is reachable again', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    useStore.getState().setBackendReachable(true);
    expect(useStore.getState().detectionParamsKey).toBe('fingerprint-1');
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test
```

Expected: FAIL — `setDetectionParamsKey is not a function`.

- [ ] **Step 3: Add the store key**

In `desktop/src/store.ts`:

1. Add to the `AppState` interface after `addManualMatch`:

```ts
  // Fingerprint of the inputs used for the last successful detection run.
  // Lets the wizard skip re-detection (preserving review work and the backend
  // cache) when nothing has changed. MUST be cleared whenever the backend
  // cache might be gone, or the wizard can loop with no way forward.
  detectionParamsKey: string;
  setDetectionParamsKey: (key: string) => void;
```

2. Add to `initialState`:

```ts
  detectionParamsKey: '',
```

3. Add the action after `addManualMatch`:

```ts
  setDetectionParamsKey: (key) => set({ detectionParamsKey: key }),
```

4. Replace `setBackendReachable`:

```ts
  // Losing the backend may mean a restarted process with an empty detection
  // cache — drop the fingerprint so the next Continue re-runs detection.
  setBackendReachable: (reachable) =>
    set(reachable ? { backendReachable: true } : { backendReachable: false, detectionParamsKey: '' }),
```

- [ ] **Step 4: Run the store tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test
```

Expected: PASS.

- [ ] **Step 5: Rework handleContinue in ConversionStatus.tsx**

Extend the store destructure at the top of the component:

```ts
  const {
    folderPath, conversionResults, setConversionResults,
    setDetectionResults, studentName, parentNames, familyNames,
    organisationNames, detectionResults, userSelections,
    detectionParamsKey, setDetectionParamsKey,
    navigateTo, setLoading, setError,
  } = useStore();
```

Replace `handleContinue` with:

```ts
  const handleContinue = async () => {
    if (!results) return;

    const allPdfs = [...results.pdf_files, ...results.converted_files];
    const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
    const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
    const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

    const paramsKey = JSON.stringify({
      pdfs: allPdfs,
      student: studentName.trim(),
      parents: parentList,
      family: familyList,
      orgs: orgList,
    });

    // Same inputs as the last successful run — reuse the existing results so
    // review decisions and manually added items survive. The backend cache is
    // only cleared by a NEW detect call, so redaction will still work.
    if (detectionResults && detectionParamsKey && paramsKey === detectionParamsKey) {
      const totalMatches = detectionResults.documents.reduce(
        (sum, d) => sum + d.matches.length, 0);
      navigateTo(totalMatches === 0 ? 'no_pii_found' : 'document_review');
      return;
    }

    // Inputs changed — re-detection will reset review work. Warn if any exists.
    if (detectionResults) {
      const hasReviewWork =
        Object.values(userSelections).some((v) => v === false) ||
        detectionResults.documents.some((d) =>
          d.matches.some((m) => m.source === 'manual'));
      if (hasReviewWork) {
        const proceed = confirm(
          'Your details have changed, so PII detection needs to run again. ' +
          'This will reset your review choices and remove any manually added items. Continue?'
        );
        if (!proceed) return;
      }
    }

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true, 'Extracting text and detecting PII...');
    try {
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
      setDetectionParamsKey(paramsKey);
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

- [ ] **Step 6: Clear the key on a manual-PII cache miss**

Open `desktop/src/pages/DocumentReview.tsx` and find the `catch` block around the `api.addManualPII(...)` call. Add this as the first statement in that catch, before the existing `setError(...)`:

```ts
      if (/no cached detection data/i.test((e as { message?: string })?.message ?? '')) {
        useStore.getState().setDetectionParamsKey('');
      }
```

(Adjust the error variable name to whatever that catch already binds. If `useStore` is not already imported as a value in this file it will be — the component uses the store — so use the same import.)

- [ ] **Step 7: Verify**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test && npm run build && npm run lint
```

Expected: vitest green, tsc clean, lint at baseline.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/store.ts desktop/src/pages/ConversionStatus.tsx desktop/src/pages/DocumentReview.tsx desktop/tests/store.test.ts
git commit -m "fix(desktop): back-navigation no longer silently destroys review choices and manual PII"
```

---

### Task 7: Reprocess when the input folder changes

**Bug:** changing the folder on step 1 leaves the previous folder's `conversionResults` in the store; `ConversionStatus`'s effect sees existing results and skips reprocessing (`ConversionStatus.tsx:32`) — the app shows and processes the OLD folder's files.

> **[REV-7] Do NOT fix this by clearing state inside `setFolderPath`.** `FolderSelection.validateFolder` calls `setFolderPath` on **every keystroke** (`FolderSelection.tsx:19`, wired to `onChange` at line 72). Clearing there means one stray keystroke in the folder field silently wipes `detectionResults`, `userSelections` and every manually-added PII item with no warning — exactly the destruction Task 6 exists to prevent, and unrecoverable (typing the character back doesn't restore anything). Instead, record which folder produced the conversion results and let `ConversionStatus` reprocess on mismatch. Detection staleness is already covered by Task 6's fingerprint: a new folder means new PDF paths, so `paramsKey` differs and the user gets the `confirm()` before anything is discarded.

**Files:**
- Modify: `desktop/src/store.ts` (`conversionFolderPath`; clear stale `redactionResults` on new detection)
- Modify: `desktop/src/pages/ConversionStatus.tsx` (the process-folder effect)
- Test: `desktop/tests/store.test.ts`

**Interfaces:**
- Consumes: `detectionParamsKey` from Task 6.
- Produces: store key `conversionFolderPath: string`, set automatically by `setConversionResults`.

- [ ] **Step 1: Write the failing store tests**

Add to `desktop/tests/store.test.ts`:

```ts
describe('store: conversionFolderPath', () => {
  const conversion = {
    pdf_files: [], converted_files: [], failed_conversions: [],
    password_protected: [], total_files: 1, processable_count: 1, flagged_count: 0,
  };

  beforeEach(() => {
    useStore.getState().reset();
  });

  it('records the folder that produced the conversion results', () => {
    useStore.getState().setFolderPath('/folder-a');
    useStore.getState().setConversionResults(conversion);
    expect(useStore.getState().conversionFolderPath).toBe('/folder-a');
  });

  it('leaves conversion results intact when the path is edited (no keystroke data loss)', () => {
    useStore.getState().setFolderPath('/folder-a');
    useStore.getState().setConversionResults(conversion);
    useStore.setState({ detectionResults: { documents: [], total_matches: 0 } });

    useStore.getState().setFolderPath('/folder-b');

    // Nothing destroyed — the mismatch is what triggers reprocessing.
    expect(useStore.getState().conversionResults).toBe(conversion);
    expect(useStore.getState().detectionResults).not.toBeNull();
    expect(useStore.getState().conversionFolderPath).toBe('/folder-a');
    expect(useStore.getState().folderPath).toBe('/folder-b');
  });

  it('clears stale redaction results when a new detection run lands', () => {
    useStore.setState({
      redactionResults: {
        redacted_folder: '/old', document_results: [], log_content: '', log_path: null,
        total_documents: 0, successfully_redacted: 0, verification_failures: [],
        ocr_warnings: [], cancelled: false,
      },
    });
    useStore.getState().setDetectionResults({ documents: [], total_matches: 0 });
    expect(useStore.getState().redactionResults).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test
```

Expected: the first and third FAIL (`conversionFolderPath` is undefined; `redactionResults` survives).

- [ ] **Step 3: Implement the store changes**

In `desktop/src/store.ts`:

1. Add to the `AppState` interface near `conversionResults`:

```ts
  // Which folder produced conversionResults — lets ConversionStatus detect a
  // folder change and reprocess, without destroying state on every keystroke.
  conversionFolderPath: string;
```

2. Add to `initialState`:

```ts
  conversionFolderPath: '',
```

3. Replace `setConversionResults`:

```ts
  setConversionResults: (results) =>
    set((state) => ({
      conversionResults: results,
      conversionFolderPath: state.folderPath,
    })),
```

4. In `setDetectionResults`, add `redactionResults: null` to the object it sets, so a completed run's results can never linger behind a fresh detection:

```ts
    set({
      detectionResults: results,
      userSelections: selections,
      currentDocIndex: 0,
      redactionResults: null,
    });
```

- [ ] **Step 4: Reprocess on mismatch in ConversionStatus.tsx**

Add `conversionFolderPath` to the store destructure, then replace the process-folder effect's guard:

```ts
    if (conversionResults || !deps) return;
```

with:

```ts
    // Reprocess when the folder changed since these results were produced.
    if (!deps) return;
    if (conversionResults && conversionFolderPath === folderPath) return;
```

and add `conversionFolderPath` to that effect's dependency array.

- [ ] **Step 5: Verify**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test && npm run build && npm run lint
```

Expected: all green, lint at baseline. Also confirm by reading the file that no render path dereferences `conversionResults` without its existing null guard (`const results = conversionResults;` then `{results && ...}`).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/store.ts desktop/src/pages/ConversionStatus.tsx desktop/tests/store.test.ts
git commit -m "fix(desktop): reprocess documents when the input folder changes"
```

---

### Task 8: Full regression run + CLAUDE.md sync

**Files:**
- Modify: `CLAUDE.md` (project root)

- [ ] **Step 1: Run everything**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -3
```

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm test && npm run build && npm run lint && node --check electron/main.cjs && node --check electron/preload.cjs
```

Expected: Python suite fully green; vitest green; tsc clean; lint at exactly 7 errors + 2 warnings; both `.cjs` files parse. Note the Python test total for the doc update.

- [ ] **Step 2: Update CLAUDE.md**

Make exactly these edits:

1. **Reconcile the test count.** CLAUDE.md currently says **306** on the `**Test**:` line near the top and **316** in the Test Structure block. Set both to the actual number from Step 1.
2. **Rule #30** (cleanup restrictions) — replace the first sentence with: "`/api/cleanup` and `/api/cleanup/list` only operate on `*_redacted.pdf` and `*.UNVERIFIED.pdf` files inside the resolved `output_folder` (verified via `Path.is_relative_to`); the delete endpoint enforces the filename patterns itself, not just the list endpoint."
3. **Add a new numbered rule:** "**API token auth, and middleware order**: When `REDACTION_API_TOKEN` is set (Electron sets it at spawn), every endpoint except `/api/health` requires a matching `X-Api-Token` header. The token flows `main.cjs` → backend env + `ipcMain.handle('get-api-token')` → `preload.cjs` → `window.electronAPI.getApiToken()` → cached in `api.ts`. Unset (manual `uvicorn`, pytest) means auth is disabled. **The `@app.middleware(\"http\")` token function must be defined BEFORE `app.add_middleware(CORSMiddleware, ...)`** — Starlette inserts at index 0, so the last registration is outermost, and only that ordering lets a 401 carry CORS headers the dev renderer can read. CORS is pinned to the two Vite dev origins; the packaged app sends no Origin at all and needs no entry, and `\"null\"` is deliberately excluded (it is the sandboxed-iframe origin)."
4. **Add a new numbered rule:** "**Cooperative redaction cancel**: `POST /api/redact/cancel` flips `_redaction_control['cancel_requested']`; `RedactionService.execute(should_cancel=...)` checks it between documents, sets `RedactionResults.cancelled`, and marks the audit log via `logger.set_cancelled()`. The frontend does NOT abort the redact request on cancel — it keeps it alive and reads accurate partial results from the response, including `quarantine_path` for `.UNVERIFIED.pdf` files (which have no `output_path`)."
5. **Add a new numbered rule:** "**spaCy loads once per process**: `_get_shared_nlp_engine()` in `pii_orchestrator.py` caches the NLP engine module-level (thread-locked). Never construct `NlpEngineProvider` per request — it costs ~0.6s each time. The `AnalyzerEngine` itself stays per-orchestrator (~0.01s) because `StudentNameRecognizer` is parameterised per run."
6. **Add a new numbered rule:** "**`detectionParamsKey` must be cleared on any backend-cache doubt**: the frontend skips re-detection when the fingerprint matches, which is only safe while `_detection_cache` holds the same run. Every path that can observe a `no cached detection data` error — and `setBackendReachable(false)` — clears the key. Without that the wizard loops: skip detection → redact 400s → 'go back one step' → skip again."
7. **Zustand Store Keys table** — add:
   `| detectionParamsKey | string | Fingerprint of last detection inputs — matching inputs skip re-detection |`
   `| conversionFolderPath | string | Folder that produced conversionResults — mismatch triggers reprocessing |`
   Add a note under the table: "`setFolderPath` is deliberately dumb (it fires on every keystroke); folder-change invalidation happens via `conversionFolderPath` in `ConversionStatus`, and `setDetectionResults` clears any stale `redactionResults`."
8. **Test Structure** — update the `test_backend_redact.py` and `test_cleanup_api.py` per-file counts; add a line for `test_api_auth.py` (`# 7 tests: API token middleware, CORS header on 401, non-ASCII header`).
9. **Desktop test note** (the `**Test (desktop)**:` line) — append `store.ts` to the list of covered pure modules.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document API token auth, cancel flow, NLP cache and store invalidation"
```

---

## Self-Review Checklist (run after all tasks)

- [ ] All Part-2 items have a task: green-tick-on-failure (4), cancel doesn't cancel (5), silent review-work destruction (6), stale folder results (7), CORS/auth (2), cleanup deletion scope (1), spaCy reload (3).
- [ ] **[REV-1]** The token middleware is defined ABOVE `add_middleware(CORSMiddleware, ...)`, and `test_401_response_carries_cors_header` passes.
- [ ] **[REV-2]** `"null"` is NOT in `allow_origins`, and the dev smoke test (Task 2 Step 10) succeeded.
- [ ] **[REV-3]** The token is delivered by IPC; `additionalArguments` is not used.
- [ ] **[REV-4]** A verification-failed document appears in exactly ONE red box, not two.
- [ ] **[REV-5]** `quarantine_path` reaches the frontend and is included in the cancel screen's file list.
- [ ] **[REV-6]** `detectionParamsKey` is cleared by `reset()`, `setBackendReachable(false)`, and both cache-miss handlers (`FinalConfirmation`, `DocumentReview`).
- [ ] **[REV-7]** `setFolderPath` does NOT clear derived state; folder changes are caught by `conversionFolderPath`.
- [ ] Lint count still exactly 7 errors + 2 warnings; Python suite fully green; dev smoke test done.
