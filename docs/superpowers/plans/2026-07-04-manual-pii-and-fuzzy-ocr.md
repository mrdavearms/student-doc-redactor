# Manual PII Addition + Fuzzy OCR Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a reviewer manually flag PII the detection engines missed during document review, and make OCR-based redaction on scanned pages tolerant of common single-character OCR misreads (e.g. "Sarnh" for "Sarah").

**Architecture:** Feature 1 adds a new PII match directly into the same server-side `_detection_cache` that the existing `/api/redact` endpoint already reads from — no changes to the redact endpoint itself, because appending to the cached `matches` list is exactly what an extra detected match would look like. Feature 2 adds a small Levenshtein-distance helper to the single shared OCR word-matching function (`_match_and_redact_ocr_words`) so both `_redact_ocr_page` and `_redact_embedded_images` gain fuzzy tolerance for free.

**Tech Stack:** FastAPI + Pydantic (backend), React + Zustand + TypeScript + Vite (desktop frontend), PyMuPDF (`fitz`) + pytesseract (redaction engine), pytest (Python tests), vitest (frontend tests).

## Global Constraints

- Python 3.13+, existing venv at `venv/bin/python3.13` — run all pytest via `venv/bin/python3.13 -m pytest`, never `venv/bin/pytest` (broken shebang).
- Desktop tests only cover pure modules (`api.ts`, `errorMessage.ts`, `store.ts` is fair game — no React rendering). React/Electron changes are verified via `npm run build` (tsc) + `npm run lint`, not unit tests.
- `PIIMatch.source` currently only takes `'regex'` or `'presidio'` in practice — this plan adds `'manual'` as a new value.
- Text shorter than 3 characters must never be redacted (existing rule in both `_redact_text_search` and `_match_and_redact_ocr_words`) — the manual-add endpoint must enforce the same floor so it can't create an item the redactor silently ignores.
- `page_num` is 1-indexed everywhere in `PIIMatch`/`RedactionItem` (`page = doc[page_num - 1]` in `redactor.py`) — the manual-add endpoint must validate against the real page count, or an out-of-range value crashes `redact_pdf()` for the *entire* document (`IndexError` on `doc[page_num - 1]`).
- Fuzzy OCR matching must never apply to non-alphabetic PII (emails, URLs, phone numbers) — reuse the existing `pii_lower.isalpha()` guard already used for the substring-match branch.
- Work on the `test` branch; commit frequently per task.

---

## File Structure

| File | Change |
|---|---|
| `backend/schemas.py` | Add `AddManualPIIRequest`, `AddManualPIIResponse` |
| `backend/main.py` | Add `POST /api/pii/manual` endpoint |
| `tests/test_manual_pii.py` | **New** — endpoint validation + detect→manual→redact round trip |
| `desktop/src/types.ts` | No change (existing `PIIMatch` interface already covers manual items) |
| `desktop/src/api.ts` | Add `addManualPII()` client method |
| `desktop/src/store.ts` | Add `addManualMatch()` action |
| `desktop/tests/store.test.ts` | **New** — tests `addManualMatch()` |
| `desktop/src/lib/errorMessage.ts` | Add 2 patterns for new backend validation errors |
| `desktop/tests/errorMessage.test.ts` | Add test cases for the 2 new patterns |
| `desktop/src/pages/DocumentReview.tsx` | Add "Add a missed item" form |
| `src/core/redactor.py` | Add `_levenshtein()`, `_fuzzy_word_match()`; wire into `_match_and_redact_ocr_words()` |
| `tests/test_ocr_redaction.py` | Add `TestFuzzyOcrMatching` test class |
| `CLAUDE.md` | Document new `source='manual'` value, new rules, updated test inventory |

---

### Task 1: Backend — manual PII addition endpoint

**Files:**
- Modify: `backend/schemas.py:66-69` (insert after `DetectionResultsResponse`)
- Modify: `backend/main.py:27-47` (import block), insert new endpoint after `detect_pii` (after line 207)
- Test: `tests/test_manual_pii.py` (new)

**Interfaces:**
- Produces: `POST /api/pii/manual` — request `{doc_path: str, text: str, page_num: int, category?: str}`, response `{match: PIIMatchResponse, index: int}`. Appends a `PIIMatch(source="manual", confidence=1.0, line_num=0, bbox=None)` to `_detection_cache[doc_path]["matches"]`.
- Consumes: existing `_detection_cache: Dict[str, Dict]` (module global in `backend/main.py`), existing `PIIMatch` dataclass (`src/core/pii_detector.py`), existing `PIIMatchResponse` schema.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manual_pii.py`:

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


def _detect(pdf_path, student_name="Nobody Relevant"):
    return client.post("/api/pii/detect", json={
        "pdf_paths": [str(pdf_path)],
        "student_name": student_name,
        "parent_names": [],
        "family_names": [],
        "organisation_names": [],
    })


def test_manual_item_is_appended_and_redacted_end_to_end():
    """A manually-added item the engines missed must actually get redacted
    when the user selects it and runs /api/redact — proving the cache-append
    approach flows through the existing redact endpoint unmodified."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        # "STUDENTREF12345" is not a name, email, or any pattern the regex
        # or NER engines recognise — detection must find zero matches.
        _make_pdf(pdf, "Internal reference code STUDENTREF12345 for this file.")

        det = _detect(pdf)
        assert det.status_code == 200, det.text
        assert det.json()["documents"][0]["matches"] == []

        manual = client.post("/api/pii/manual", json={
            "doc_path": str(pdf),
            "text": "STUDENTREF12345",
            "page_num": 1,
        })
        assert manual.status_code == 200, manual.text
        body = manual.json()
        assert body["index"] == 0
        assert body["match"]["text"] == "STUDENTREF12345"
        assert body["match"]["source"] == "manual"
        assert body["match"]["confidence_label"] == "high"

        red = client.post("/api/redact", json={
            "folder_path": tmp,
            "student_name": "Nobody Relevant",
            "parent_names": [],
            "family_names": [],
            "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": [f"{pdf}_0"],
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        result = red.json()["document_results"][0]
        assert result["success"] is True
        assert result["items_redacted"] == 1

        out_doc = fitz.open(result["output_path"])
        out_text = out_doc[0].get_text()
        out_doc.close()
        assert "STUDENTREF12345" not in out_text


def test_manual_item_rejects_text_under_3_chars():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Jo", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "at least 3 characters" in resp.json()["detail"]


def test_manual_item_rejects_out_of_range_page():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 5,
        })
        assert resp.status_code == 400
        assert "does not exist in this document" in resp.json()["detail"]


def test_manual_item_requires_prior_detection():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        # No _detect(pdf) call — no cache entry exists for this path.

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "Run detection first" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python3.13 -m pytest tests/test_manual_pii.py -v`
Expected: FAIL — `404 Not Found` for `/api/pii/manual` (route doesn't exist yet) on all four tests.

- [ ] **Step 3: Add the request/response schemas**

In `backend/schemas.py`, insert immediately after the `DetectionResultsResponse` class (after line 68, before the `# ── Redaction` comment on line 71):

```python
class AddManualPIIRequest(BaseModel):
    doc_path: str
    text: str
    page_num: int  # 1-indexed, matches PIIMatch.page_num convention
    category: str = "Manual"


class AddManualPIIResponse(BaseModel):
    match: PIIMatchResponse
    index: int
```

- [ ] **Step 4: Add the endpoint**

In `backend/main.py`, add `AddManualPIIRequest` and `AddManualPIIResponse` to the existing import block (lines 27-47):

```python
from backend.schemas import (
    ConversionResultsResponse,
    DependencyStatusResponse,
    DetectPIIRequest,
    DetectionResultsResponse,
    DocumentPIIResponse,
    DocumentResultResponse,
    HealthResponse,
    OpenFolderRequest,
    PIIMatchResponse,
    PreviewRequest,
    PreviewResponse,
    ProcessFolderRequest,
    RedactRequest,
    RedactionResultsResponse,
    CleanupListRequest,
    CleanupListResponse,
    CleanupRequest,
    CleanupResponse,
    CleanupFailure,
    AddManualPIIRequest,
    AddManualPIIResponse,
)
```

Then insert this new endpoint right after `detect_pii()` ends (after line 207), before the `# ── Redaction` section comment:

```python
@app.post("/api/pii/manual", response_model=AddManualPIIResponse)
def add_manual_pii(req: AddManualPIIRequest):
    """
    Append a user-identified PII item the detection engines missed.

    Stored in the same server-side cache /api/redact reads from, so once
    the frontend marks it selected it is redacted exactly like any other
    detected match — no changes needed to the redact endpoint itself.
    """
    import fitz

    cached = _detection_cache.get(req.doc_path)
    if not cached:
        raise HTTPException(
            status_code=400,
            detail=f"No cached detection data for {req.doc_path}. Run detection first.",
        )

    text = req.text.strip()
    if len(text) < 3:
        raise HTTPException(status_code=400, detail="Manual PII text must be at least 3 characters.")

    doc_path = Path(req.doc_path)
    if not doc_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {doc_path}")

    try:
        pdf = fitz.open(str(doc_path))
        total_pages = len(pdf)
        pdf.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot open PDF: {e}")

    if req.page_num < 1 or req.page_num > total_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Page {req.page_num} does not exist in this document (it has {total_pages} pages).",
        )

    match = PIIMatch(
        text=text,
        category=req.category,
        confidence=1.0,
        page_num=req.page_num,
        line_num=0,
        context=text,
        source="manual",
        bbox=None,
    )
    cached["matches"].append(match)
    index = len(cached["matches"]) - 1

    return AddManualPIIResponse(
        match=PIIMatchResponse(
            text=match.text,
            category=match.category,
            confidence=match.confidence,
            confidence_label=match.confidence_label,
            page_num=match.page_num,
            line_num=match.line_num,
            context=match.context,
            source=match.source,
            bbox=None,
        ),
        index=index,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python3.13 -m pytest tests/test_manual_pii.py -v`
Expected: PASS (4 passed)

Also run the existing backend redact tests to confirm no regression:
Run: `venv/bin/python3.13 -m pytest tests/test_backend_redact.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/main.py tests/test_manual_pii.py
git commit -m "feat(backend): add endpoint to manually add a missed PII item"
```

---

### Task 2: Frontend — API client + store action for manual PII

**Files:**
- Modify: `desktop/src/api.ts:80-97` (insert new method after `redact`)
- Modify: `desktop/src/store.ts` (add `addManualMatch` action + interface entry)
- Test: `desktop/tests/store.test.ts` (new)

**Interfaces:**
- Consumes: `PIIMatch` type from `desktop/src/types.ts:40-50` (already has all needed fields including `source`).
- Produces: `api.addManualPII(params): Promise<{match: PIIMatch, index: number}>` and `useStore.getState().addManualMatch(docPath: string, match: PIIMatch, index: number): void` — both consumed by Task 3's `DocumentReview.tsx` form.

- [ ] **Step 1: Write the failing store test**

Create `desktop/tests/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';
import type { PIIMatch } from '../src/types';

function manualMatch(overrides: Partial<PIIMatch> = {}): PIIMatch {
  return {
    text: 'Sarnh Jones',
    category: 'Manual',
    confidence: 1.0,
    confidence_label: 'high',
    page_num: 2,
    line_num: 0,
    context: 'Sarnh Jones',
    source: 'manual',
    bbox: null,
    ...overrides,
  };
}

describe('store: addManualMatch', () => {
  beforeEach(() => {
    useStore.setState({
      detectionResults: {
        documents: [
          { path: '/tmp/a.pdf', filename: 'a.pdf', matches: [], ocr_pages: [] },
          { path: '/tmp/b.pdf', filename: 'b.pdf', matches: [], ocr_pages: [] },
        ],
        total_matches: 0,
      },
      userSelections: {},
    });
  });

  it('appends the match to the matching document only', () => {
    const match = manualMatch();
    useStore.getState().addManualMatch('/tmp/a.pdf', match, 0);

    const state = useStore.getState();
    expect(state.detectionResults?.documents[0].matches).toEqual([match]);
    expect(state.detectionResults?.documents[1].matches).toEqual([]);
  });

  it('marks the new match selected by its index-derived key', () => {
    const match = manualMatch();
    useStore.getState().addManualMatch('/tmp/a.pdf', match, 0);

    expect(useStore.getState().userSelections['/tmp/a.pdf_0']).toBe(true);
  });

  it('appends after existing matches without disturbing their selections', () => {
    useStore.setState((s) => ({
      detectionResults: {
        ...s.detectionResults!,
        documents: s.detectionResults!.documents.map((d) =>
          d.path === '/tmp/a.pdf' ? { ...d, matches: [manualMatch({ text: 'Existing' })] } : d
        ),
      },
      userSelections: { '/tmp/a.pdf_0': false },
    }));

    const newMatch = manualMatch({ text: 'New One' });
    useStore.getState().addManualMatch('/tmp/a.pdf', newMatch, 1);

    const state = useStore.getState();
    expect(state.detectionResults?.documents[0].matches.map((m) => m.text)).toEqual(['Existing', 'New One']);
    expect(state.userSelections['/tmp/a.pdf_0']).toBe(false);
    expect(state.userSelections['/tmp/a.pdf_1']).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npm test -- store.test.ts`
Expected: FAIL — `useStore.getState().addManualMatch is not a function`

- [ ] **Step 3: Add the store action**

In `desktop/src/store.ts`, add to the `AppState` interface (after `deselectAll` on line 47):

```typescript
  deselectAll: (docPath: string, count: number) => void;
  addManualMatch: (docPath: string, match: import('./types').PIIMatch, index: number) => void;
```

And add the implementation after `deselectAll` (after line 141, before `setRedactionResults`):

```typescript
  deselectAll: (docPath, count) =>
    set((state) => {
      const selections = { ...state.userSelections };
      for (let i = 0; i < count; i++) selections[`${docPath}_${i}`] = false;
      return { userSelections: selections };
    }),

  addManualMatch: (docPath, match, index) =>
    set((state) => {
      if (!state.detectionResults) return {};
      const documents = state.detectionResults.documents.map((doc) =>
        doc.path === docPath ? { ...doc, matches: [...doc.matches, match] } : doc
      );
      return {
        detectionResults: { ...state.detectionResults, documents },
        userSelections: { ...state.userSelections, [`${docPath}_${index}`]: true },
      };
    }),
```

- [ ] **Step 4: Add the API client method**

In `desktop/src/api.ts`, insert after the `redact` method (after line 97, before `previewPage`):

```typescript
  addManualPII: (params: {
    doc_path: string;
    text: string;
    page_num: number;
    category?: string;
  }) =>
    request<{ match: import('./types').PIIMatch; index: number }>('/api/pii/manual', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
```

- [ ] **Step 5: Run tests and type check**

Run: `cd desktop && npm test`
Expected: PASS (all suites, including the 3 new `store.test.ts` cases)

Run: `cd desktop && npm run build`
Expected: no TypeScript errors

- [ ] **Step 6: Commit**

```bash
git add desktop/src/api.ts desktop/src/store.ts desktop/tests/store.test.ts
git commit -m "feat(desktop): add store action and API client for manual PII entries"
```

---

### Task 3: Frontend — "Add a missed item" form on the review screen

**Files:**
- Modify: `desktop/src/lib/errorMessage.ts:3-12`
- Modify: `desktop/tests/errorMessage.test.ts`
- Modify: `desktop/src/pages/DocumentReview.tsx`

**Interfaces:**
- Consumes: `api.addManualPII` and `useStore().addManualMatch` from Task 2; `useStore().setError` (existing, `desktop/src/store.ts:61-62`); `friendlyError` from `desktop/src/lib/errorMessage.ts`.

- [ ] **Step 1: Write the failing error-message tests**

In `desktop/tests/errorMessage.test.ts`, add two cases (find the existing `describe('friendlyError', ...)` block and add inside it, after the "Cannot open PDF" case):

```typescript
  it('maps manual-PII text-too-short to a friendly message', () => {
    expect(friendlyError(new Error('Manual PII text must be at least 3 characters.')))
      .toMatch(/at least 3 characters/i);
  });

  it('maps manual-PII out-of-range page to a friendly message', () => {
    expect(friendlyError(new Error('Page 5 does not exist in this document (it has 2 pages).')))
      .toMatch(/doesn't have that many pages/i);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npm test -- errorMessage.test.ts`
Expected: FAIL — both new cases fall through to the generic `FALLBACK` message, which doesn't match either regex.

- [ ] **Step 3: Add the error patterns**

In `desktop/src/lib/errorMessage.ts`, add two entries to the `PATTERNS` array (after the `/cannot open pdf/i` line):

```typescript
  [/cannot open pdf/i, "One of the PDFs couldn't be read. It may be corrupted or password-protected."],
  [/manual pii text must be at least 3 characters/i, "That's too short to redact reliably — please enter at least 3 characters."],
  [/does not exist in this document/i, "That document doesn't have that many pages. Check the page number and try again."],
  [/page \d+ out of range/i, "Couldn't load that page from the PDF."],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npm test -- errorMessage.test.ts`
Expected: PASS

- [ ] **Step 5: Add the manual-entry form to DocumentReview.tsx**

In `desktop/src/pages/DocumentReview.tsx`, change the imports (lines 1-7):

```typescript
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowLeft, ArrowRight, CheckSquare, Square, FileText, CheckCircle2, Plus,
} from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { friendlyError } from '../lib/errorMessage';
import HelpTip from '../components/HelpTip';
```

Update the store destructure (lines 10-14):

```typescript
  const {
    detectionResults, currentDocIndex, userSelections,
    setCurrentDocIndex, toggleSelection, selectAll, deselectAll,
    addManualMatch, setError, navigateTo,
  } = useStore();
```

Add local state for the form right after the `nextDocWithPII` function (after line 22, before the `useEffect` on line 25):

```typescript
  const [manualText, setManualText] = useState('');
  const [manualPage, setManualPage] = useState(1);
  const [manualBusy, setManualBusy] = useState(false);
  const [manualFieldError, setManualFieldError] = useState<string | null>(null);

  // Reset the form when the current document changes so a stale entry
  // can't accidentally get submitted against the wrong document.
  useEffect(() => {
    setManualText('');
    setManualPage(1);
    setManualFieldError(null);
  }, [currentDocIndex]);
```

Add the submit handler right before the `return (` statement (after the `selectedCount` calculation, before line 52):

```typescript
  const handleAddManual = async () => {
    const trimmed = manualText.trim();
    if (trimmed.length < 3) {
      setManualFieldError('Enter at least 3 characters.');
      return;
    }
    setManualFieldError(null);
    setManualBusy(true);
    try {
      const result = await api.addManualPII({
        doc_path: doc.path,
        text: trimmed,
        page_num: manualPage,
      });
      addManualMatch(doc.path, result.match, result.index);
      setManualText('');
      setManualPage(1);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setManualBusy(false);
    }
  };
```

The form must show regardless of whether the detector found any matches, so it does NOT go inside the `{matches.length === 0 ? (...) : (<>...</>)}` fragment. Insert it as a new sibling section directly after the whole document-header card closes — i.e. after line 182's closing `</div>` (the one that closes the `<div className="bg-white rounded-xl border border-slate-200 p-5">` opened on line 91), and before the `{/* Navigation */}` comment on line 184:

```tsx
      {/* Manual "missed item" addition */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-2">
          <Plus size={16} className="text-primary-500" />
          <h3 className="text-sm font-medium text-slate-600">Add a Missed Item</h3>
          <HelpTip text="If you spot something the tool didn't catch — a name, ID, or anything else — add it here and it will be redacted along with everything else." />
        </div>
        <div className="flex flex-wrap items-end gap-2 mt-3">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-slate-400 mb-1">Text to redact</label>
            <input
              type="text"
              value={manualText}
              onChange={(e) => { setManualText(e.target.value); setManualFieldError(null); }}
              placeholder="e.g. a name or ID the tool missed"
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 focus:outline-none focus:border-primary-300"
            />
          </div>
          <div className="w-24">
            <label className="block text-xs text-slate-400 mb-1">Page</label>
            <input
              type="number"
              min={1}
              value={manualPage}
              onChange={(e) => setManualPage(Math.max(1, parseInt(e.target.value, 10) || 1))}
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 focus:outline-none focus:border-primary-300"
            />
          </div>
          <button
            onClick={handleAddManual}
            disabled={manualBusy || manualText.trim().length < 3}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium
                       bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-40
                       disabled:cursor-not-allowed transition-colors btn-press"
          >
            <Plus size={14} /> {manualBusy ? 'Adding...' : 'Add'}
          </button>
        </div>
        {manualFieldError && (
          <p className="text-xs text-rose-600 mt-2">{manualFieldError}</p>
        )}
      </div>

```

- [ ] **Step 6: Type check and lint**

Run: `cd desktop && npm run build`
Expected: no TypeScript errors

Run: `cd desktop && npm run lint`
Expected: same baseline as documented in `CLAUDE.md` (7 errors + 2 warnings, none newly introduced in `DocumentReview.tsx`)

- [ ] **Step 7: Manually verify in the running app**

Run: `cd desktop && npm run dev:electron`

Walk through: select a folder with at least one PDF → convert → land on the Review PII screen. For a document (with or without existing matches):
1. Type a short phrase (e.g. "Test Missed Item") into "Text to redact", leave page at 1, click Add.
2. Confirm a new entry appears in the match list above, pre-selected (checked), with category "Manual" and a "high" confidence badge.
3. Try adding with fewer than 3 characters — confirm the inline "Enter at least 3 characters" message appears and no request is sent.
4. Try a page number beyond the document's page count — confirm the global error banner shows "That document doesn't have that many pages...".
5. Proceed to Final Confirmation — confirm "Manual" appears in the category breakdown with the right count.
6. Create redacted documents, then open the output PDF and confirm the manually-entered text is blacked out.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/lib/errorMessage.ts desktop/tests/errorMessage.test.ts desktop/src/pages/DocumentReview.tsx
git commit -m "feat(desktop): add UI to manually flag PII the detector missed"
```

---

### Task 4: Fuzzy OCR word matching

**Files:**
- Modify: `src/core/redactor.py:327-402` (`_match_and_redact_ocr_words`), plus two new helpers
- Test: `tests/test_ocr_redaction.py` (add test class)

**Interfaces:**
- Produces: `_levenshtein(a: str, b: str) -> int` (module-level function in `redactor.py`) and `PDFRedactor._fuzzy_word_match(self, ocr_clean: str, pii_lower: str) -> bool`. Both used only inside `_match_and_redact_ocr_words`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_ocr_redaction.py`, add a new test class after `TestRedactOcrPageMatching` (find its closing test, `test_multiple_pii_items`, around line 373, and insert the new class after that method but still inside the existing test module — i.e. as a new top-level class in the same file):

```python
# ---------------------------------------------------------------------------
# Fuzzy OCR matching — tolerates single-character OCR misreads
# ---------------------------------------------------------------------------

class TestFuzzyOcrMatching:
    """
    Scanned pages routinely produce single-character OCR misreads
    (e.g. Tesseract reading 'Sarah' as 'Sarnh'). These tests confirm
    _match_and_redact_ocr_words tolerates that without over-matching
    short words or non-alphabetic PII (emails, IDs).
    """

    def setup_method(self):
        self.redactor = PDFRedactor()

    def _mock_ocr_data(self, words_with_boxes):
        data = {'text': [], 'left': [], 'top': [], 'width': [], 'height': [], 'conf': []}
        for word, x, y, w, h in words_with_boxes:
            data['text'].append(word)
            data['left'].append(x)
            data['top'].append(y)
            data['width'].append(w)
            data['height'].append(h)
            data['conf'].append(95)
        return data

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_one_char_misread_matches_five_letter_name(self, mock_ocr, mock_tess_ver):
        """PII 'Sarah' must match OCR 'Sarnh' (single substitution)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Sarnh", 100, 50, 90, 30),
            ("attended", 220, 50, 120, 30),
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Sarah")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_two_char_misread_does_not_match_five_letter_name(self, mock_ocr, mock_tess_ver):
        """5-7 letter names only tolerate a distance of 1 — two substitutions
        is too different to trust as the same word."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Soznh", 100, 50, 90, 30),  # 2 chars different from "Sarah"
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Sarah")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_long_name_tolerates_two_char_misread(self, mock_ocr, mock_tess_ver):
        """8+ letter names tolerate a distance of 2."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Cbristinm", 100, 50, 120, 30),  # "Christina" with 2 substitutions
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Christina")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_short_word_never_fuzzy_matched(self, mock_ocr, mock_tess_ver):
        """Words under 5 letters must require an exact match — fuzzing them
        risks blacking out unrelated short words like 'And'."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("And", 100, 50, 60, 30),
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Ann")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_email_never_fuzzy_matched(self, mock_ocr, mock_tess_ver):
        """Non-alphabetic PII (emails, IDs) must never use fuzzy matching —
        only the existing exact-substring path applies to them."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("jane@examplc.com", 100, 50, 200, 30),  # 1 char off from real email
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="jane@example.com")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multi_word_pii_with_one_word_misread_still_matches(self, mock_ocr, mock_tess_ver):
        """Multi-word PII 'Sarah Williams' must match OCR 'Sarnh Williams'."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Sarnh", 100, 50, 90, 30),
            ("Williams", 200, 50, 140, 30),
        ])
        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Sarah Williams")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py -k TestFuzzyOcrMatching -v`
Expected: FAIL — `test_one_char_misread_matches_five_letter_name`, `test_long_name_tolerates_two_char_misread`, and `test_multi_word_pii_with_one_word_misread_still_matches` fail (assert 1 == 0), the other three already pass by coincidence (exact-match-only behavior already rejects them) but will remain green once fuzzy matching is added since they're designed to stay rejected.

- [ ] **Step 3: Implement the Levenshtein helper and fuzzy match guard**

In `src/core/redactor.py`, add a module-level function right before the `PDFRedactor` class definition (before line 87, `class PDFRedactor:`):

```python
def _levenshtein(a: str, b: str) -> int:
    """
    Standard edit distance (insertions, deletions, substitutions).
    Used to tolerate common single-character OCR misreads (e.g. Tesseract
    reading "Sarah" as "Sarnh") when matching OCR'd words against PII.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,               # deletion
                curr[j - 1] + 1,           # insertion
                prev[j - 1] + (ca != cb),  # substitution
            )
        prev = curr
    return prev[-1]
```

Then add a method to `PDFRedactor`, right before `_match_and_redact_ocr_words` (before line 327):

```python
    def _fuzzy_word_match(self, ocr_clean: str, pii_lower: str) -> bool:
        """
        Whether an OCR-read word is likely the same as a PII word, tolerating
        common OCR misreads. Only ever applies to alphabetic PII of 5+
        characters — never to emails/URLs/numeric PII (the exact-substring
        branch already handles those), and never to short words where a
        1-character tolerance would risk matching an unrelated word.
        """
        if not pii_lower.isalpha() or len(pii_lower) < 5:
            return False
        if abs(len(ocr_clean) - len(pii_lower)) > 2:
            return False
        max_distance = 1 if len(pii_lower) <= 7 else 2
        return _levenshtein(ocr_clean, pii_lower) <= max_distance
```

Now wire it into `_match_and_redact_ocr_words` (lines 359-400). Update the single-word branch's condition (lines 365-372):

```python
                    if (
                        ocr_clean == pii_lower
                        or ocr_clean == pii_lower + "'s"
                        or ocr_clean == pii_lower + "\u2019s"
                        or ocr_clean.rstrip(".,;:!?") == pii_lower
                        # Exact match for PII with special chars (emails, URLs)
                        or (not pii_lower.isalpha() and pii_lower in ocr_lower)
                        or self._fuzzy_word_match(ocr_clean, pii_lower)
                    ):
```

And the multi-word branch's per-word check (lines 385-387):

```python
                        ocr_clean = re.sub(r"[^\w']", '', ocr_w.lower())
                        if (
                            ocr_clean != pii_w
                            and ocr_clean.rstrip(".,;:!?") != pii_w
                            and not self._fuzzy_word_match(ocr_clean, pii_w)
                        ):
                            match = False
                            break
```

- [ ] **Step 4: Run tests to verify they pass, and check for regressions**

Run: `venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py -v`
Expected: PASS (35 passed — the existing 29 plus 6 new)

Run: `venv/bin/python3.13 -m pytest tests/test_redactor.py tests/test_signature_detection.py -v`
Expected: PASS (no regressions in adjacent redaction logic)

- [ ] **Step 5: Commit**

```bash
git add src/core/redactor.py tests/test_ocr_redaction.py
git commit -m "feat(redactor): tolerate single-character OCR misreads when matching PII"
```

---

### Task 5: Documentation updates

**Files:**
- Modify: `CLAUDE.md` (rule #3, Test Structure section, new rules #31-#32)

- [ ] **Step 1: Update rule #3 (PIIMatch.source values)**

In `CLAUDE.md`, find rule "### 3. `PIIMatch` has a `source` field" and replace its body:

```markdown
### 3. `PIIMatch` has a `source` field

Added in `a699268`. Values in practice: `'regex'`, `'presidio'`, and `'manual'` (user-added during document review — see rule #31). The docstring on the dataclass still lists `'gliner'` from before that engine was removed (see Known Gaps) — no code path emits it anymore. Used by the orchestrator for deduplication logic. Don't remove it.
```

- [ ] **Step 2: Add two new rules documenting this session's features**

In `CLAUDE.md`, after rule "### 30. Cleanup endpoints are restricted to the user-selected output folder", add:

```markdown
### 31. Manually-added PII items live in the same detection cache as engine-found matches

`POST /api/pii/manual` (`backend/main.py`) appends a `PIIMatch(source="manual")` directly to `_detection_cache[doc_path]["matches"]` — the same list `/api/redact` reads from. This means a manual item is only ever *appended*, never inserted at an arbitrary position: its index in that list becomes its selection key (`f"{doc_path}_{index}"`), and `/api/redact` derives `user_selections` by iterating `range(len(matches))` from the cache. Inserting anywhere but the end would silently reassign an existing item's key to unrelated new content.

### 32. Fuzzy OCR matching only applies to alphabetic words of 5+ characters

`_fuzzy_word_match()` in `redactor.py` (used by the shared `_match_and_redact_ocr_words()`, so it covers both `_redact_ocr_page()` and `_redact_embedded_images()`) tolerates single-character OCR misreads via Levenshtein distance — but only for alphabetic PII of 5+ characters (`pii_lower.isalpha()` guard, same one used elsewhere to keep fuzzing away from emails/URLs). Distance tolerance is 1 for 5-7 letter words, 2 for 8+. Words under 5 letters, and any non-alphabetic PII, require an exact match — fuzzing short words risks blacking out unrelated text (e.g. "And" for "Ann").
```

- [ ] **Step 3: Update the Test Structure inventory**

In `CLAUDE.md`, find the `## Test Structure` section. Change the header count and the two affected lines:

```markdown
```
tests/                                # 316 tests total
├── test_pii_detector.py              # 52 tests: phone, email, address, Medicare, CRN, Student ID, DOB, NDIS, ABN, cross-line
├── test_pii_detector_names.py        # 65 tests: name variations, contextual detection, possessives, family, nicknames
├── test_pii_orchestrator.py          # 27 tests: orchestrator merge, dedup, NER-primary coordination
├── test_presidio_recognizers.py      # 18 tests: 6 custom AU Presidio recognizer unit tests
├── test_redactor.py                  # 14 tests: text-layer redaction routing, possessive+punctuation, redact_pdf robustness
├── test_signature_detection.py       # 16 tests: heuristic signature detection (unit + integration)
├── test_ocr_redaction.py             # 35 tests: image-only page detection, OCR redaction, word matching, fuzzy OCR matching
├── test_ocr_verification.py          # 7 tests: post-redaction OCR verification (300 DPI re-scan)
├── test_metadata_stripping.py        # 8 tests: PDF metadata removal (author, XMP, embedded files)
├── test_widget_redaction.py          # 7 tests: AcroForm widget deletion (incl. word-boundary match)
├── test_filename_redaction.py        # 13 tests: PII in filenames → [REDACTED] replacement
├── test_zone_redaction.py            # 5 tests: header/footer zone blanking (Stage 0)
├── test_manual_pii.py                # 4 tests: manual PII addition endpoint (validation, cache append, redact round-trip)
├── test_cleanup_api.py               # 13 tests: cleanup endpoint path-traversal guards
├── test_session_state.py             # 2 tests: session state key initialisation
├── test_binary_resolver.py           # 6 tests: cross-platform Tesseract/LibreOffice path resolution
├── test_text_extractor.py            # 4 tests: coord extraction + /api/preview fitz handle closing
├── test_backend_redact.py            # 3 tests: detect→redact selection + clean-500 error wrapping
├── test_integration.py               # 6 tests: end-to-end redaction pipeline (links, bookmarks, structure)
├── test_adversarial.py               # 7 tests: unicode edge cases, boundary conditions
└── test_false_positives.py           # 4 tests: false-positive regression tests
```
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document manual PII endpoint and fuzzy OCR matching"
```

---

## Self-Review Notes

- **Spec coverage:** Feature 1 (manual add) covered by Tasks 1-3 (backend endpoint, store/api wiring, UI form + manual verification). Feature 2 (fuzzy OCR) covered by Task 4. Task 5 keeps `CLAUDE.md` accurate per the project's own conventions (rule #29's pattern of "if you add a new backend error string, add a mapper pattern and a test case" — extended here to the new source value and test inventory).
- **Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.
- **Type consistency:** `addManualMatch(docPath: string, match: PIIMatch, index: number)` in Task 2's store matches the call site in Task 3's `handleAddManual`. `api.addManualPII` return type `{match: PIIMatch, index: number}` matches `AddManualPIIResponse` from Task 1's backend schema (`match: PIIMatchResponse`, `index: int` → serializes to the same JSON shape). `_fuzzy_word_match` signature matches its two call sites in Task 4's Step 3.
