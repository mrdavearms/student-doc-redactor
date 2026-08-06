# Batch A — Resource-Leak & Silent-Miss Stability Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the five highest-risk stability/correctness defects in the redaction core — PyMuPDF handle leaks, partially-written output files, and silent missed redactions — so a malformed document or missing OCR/NER engine fails loudly instead of leaking PII or crashing a batch.

**Architecture:** Five independent, surgical edits across four `src/core` files plus one backend endpoint. Each is guarded by a focused TDD test. No public signatures change except behaviour-on-error (graceful where it should be, loud where silence would leak PII). The fixes compose: Task 2's `RuntimeError` is caught and turned into a clean `(False, msg)` by Task 1's `try/finally`.

**Tech Stack:** Python 3.13, PyMuPDF (`fitz`), pytest, FastAPI TestClient. Run tests with `venv/bin/python3.13 -m pytest` (the `venv/bin/pytest` shebang is broken — always use `-m pytest`).

---

## Scope & Mapping to Review Findings

| Task | Finding | File | Defect |
|------|---------|------|--------|
| 1 | #1 | `src/core/redactor.py` | `redact_pdf` leaks the doc handle on exception; partial output left on disk |
| 2 | #3 | `src/core/redactor.py` | OCR image-only page silently unredacted when Tesseract missing |
| 3 | #9 | `src/core/redactor.py` | Widget deletion uses raw substring match → short names over-delete |
| 4 | #2 | `src/core/pii_orchestrator.py` | NER runtime failure silently swallowed under `require_ner=True` |
| 5 | #6 | `src/core/text_extractor.py` + `backend/main.py` | `fitz` handle leaked on exception in coordinate extraction & preview |

**Branch:** Work on `test` (already checked out). One atomic commit per task. **Do not push** — local commits are the safety net; pushing/merging needs explicit sign-off.

**Pre-flight (run once before Task 1):**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
git rev-parse --abbrev-ref HEAD   # expect: test
venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -5
```

Record the baseline pass/fail count. Per project memory, `test_ocr_verification.py` may have pre-existing failures from a Tesseract env issue — note them so they are not mistaken for regressions.

---

## File Structure

No new source files. One new test file (`tests/test_text_extractor.py`). New tests appended to four existing test files. Each source edit is small and local to one method.

---

### Task 1: `redact_pdf` — close the handle and clean up partial output on failure

**Files:**
- Modify: `src/core/redactor.py` (method `PDFRedactor.redact_pdf`, the outer `try/except` spanning roughly lines 105–181)
- Test: `tests/test_redactor.py` (append new class `TestRedactPdfRobustness`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_redactor.py` (the file already imports `fitz`, `PDFRedactor`; add the new imports at the top of the file alongside the existing imports):

```python
from unittest.mock import patch
from pathlib import Path
import tempfile
from redactor import RedactionItem


class TestRedactPdfRobustness:
    """redact_pdf must never raise, must close its document, and must not
    leave a partially-written output file behind when a stage fails."""

    def _make_pdf_file(self, path, text="Hello Joe Bloggs"):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=12)
        doc.save(str(path))
        doc.close()

    def test_failure_returns_false_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()

            def boom(self, doc):
                raise RuntimeError("strip failed")

            with patch.object(PDFRedactor, "_strip_metadata", boom):
                success, msg = redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert success is False
            assert "strip failed" in msg

    def test_partial_output_removed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()

            def boom(self, doc):
                out.write_bytes(b"%PDF partial")  # simulate a half-written file
                raise RuntimeError("save failed")

            with patch.object(PDFRedactor, "_strip_metadata", boom):
                success, msg = redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert success is False
            assert not out.exists(), "partial output must be removed on failure"

    def test_document_closed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()
            opened = []
            real_open = fitz.open

            def tracking_open(*a, **k):
                d = real_open(*a, **k)
                opened.append(d)
                return d

            def boom(self, doc):
                raise RuntimeError("boom")

            with patch("redactor.fitz.open", tracking_open), \
                 patch.object(PDFRedactor, "_strip_metadata", boom):
                redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert opened, "redact_pdf should have opened a document"
            assert opened[0].is_closed, "document must be closed after a failure"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_redactor.py::TestRedactPdfRobustness -v
```
Expected: `test_partial_output_removed_on_failure` and `test_document_closed_on_failure` FAIL (partial file remains; `is_closed` is False because the current code only closes on the success path). `test_failure_returns_false_without_raising` may already PASS — that is fine.

- [ ] **Step 3: Apply the fix**

In `src/core/redactor.py`, change the start of the `redact_pdf` body. Replace:

```python
        try:
            doc = fitz.open(str(input_pdf))
```
with:
```python
        doc = None
        try:
            doc = fitz.open(str(input_pdf))
```

Then remove the inline `doc.close()` that follows the save. Replace:

```python
            # Save redacted document (clean=True removes incremental save data)
            doc.save(str(output_pdf), garbage=4, deflate=True, clean=True)
            doc.close()

            return True, f"Successfully redacted {len(redaction_items)} items"

        except Exception as e:
            return False, f"Error during redaction: {str(e)}"
```
with:
```python
            # Save redacted document (clean=True removes incremental save data)
            doc.save(str(output_pdf), garbage=4, deflate=True, clean=True)

            return True, f"Successfully redacted {len(redaction_items)} items"

        except Exception as e:
            # Remove any partially-written output so a failed redaction can
            # never leave a file that looks like a successful result.
            try:
                out = Path(output_pdf)
                if out.exists():
                    out.unlink()
            except OSError:
                pass
            return False, f"Error during redaction: {str(e)}"
        finally:
            if doc is not None:
                doc.close()
```

(`Path` is already imported at `src/core/redactor.py:12`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_redactor.py -v
```
Expected: all `TestRedactPdfRobustness` tests PASS and the pre-existing `TestRedactTextSearch` tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/redactor.py tests/test_redactor.py
git commit -m "fix(redactor): close PDF handle and clean partial output on failure

redact_pdf only closed the document on the success path and could leave a
half-written *_redacted.pdf on disk if a stage raised. Wrap the body in
try/finally and unlink the partial output on error.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: OCR image-only page fails loudly when Tesseract is unavailable

**Files:**
- Modify: `src/core/redactor.py` (method `PDFRedactor._redact_ocr_page`, the early-return at ~line 590)
- Test: `tests/test_ocr_redaction.py` (append one test; file already has `_make_image_pdf_with_text`, `patch`, `pytest`, `RedactionItem`)

**Rationale:** `_redact_ocr_page` is only ever called for an image-only page that *has* PII items on it. Returning `0` when the OCR engine is missing emits a document with unredacted PII counted as success. Raising mirrors the documented NER policy (CLAUDE.md rule 8) and is caught by Task 1's `try/finally`, which turns it into a clean `(False, msg)` and removes the partial output.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ocr_redaction.py`:

```python
def test_ocr_page_fails_loudly_when_tesseract_unavailable(tmp_path):
    """An image-only page with PII must NOT be reported as redacted when the
    OCR engine is missing — redact_pdf must return failure, not silent success."""
    pdf = _make_image_pdf_with_text("Joe Bloggs", tmp_path)
    out = tmp_path / "out.pdf"
    redactor = PDFRedactor()
    items = [RedactionItem(page_num=1, text="Joe Bloggs")]

    with patch.object(PDFRedactor, "_check_tesseract", return_value=False):
        success, msg = redactor.redact_pdf(pdf, out, items)

    assert success is False, "must fail when OCR engine is unavailable"
    assert "OCR" in msg or "Tesseract" in msg, f"message should name the cause: {msg}"
    assert not out.exists(), "no output file should be left behind"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py::test_ocr_page_fails_loudly_when_tesseract_unavailable -v
```
Expected: FAIL — current code returns `0` and `redact_pdf` reports success.

- [ ] **Step 3: Apply the fix**

In `src/core/redactor.py`, inside `_redact_ocr_page`, replace:

```python
        if not self._check_tesseract():
            return 0
```
with:
```python
        if not self._check_tesseract():
            # This page is image-only and its PII can only be located via OCR.
            # If the OCR engine is missing we cannot redact it — fail loudly
            # rather than emit a document with unredacted PII.
            raise RuntimeError(
                f"OCR engine (Tesseract) unavailable — cannot redact "
                f"image-only page {page.number + 1}"
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py -v
```
Expected: the new test PASSES and all existing OCR tests still PASS (they mock `pytesseract`/`_check_tesseract` to truthy paths, so the new raise does not fire).

- [ ] **Step 5: Commit**

```bash
git add src/core/redactor.py tests/test_ocr_redaction.py
git commit -m "fix(redactor): fail loudly when OCR engine missing on image-only page

_redact_ocr_page returned 0 when Tesseract was unavailable, silently leaving
scanned-page PII unredacted while reporting success. Raise instead, mirroring
the require_ner policy; redact_pdf turns it into a clean failure.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Widget deletion uses word-boundary matching, not raw substring

**Files:**
- Modify: `src/core/redactor.py` (method `PDFRedactor._delete_pii_widgets`, the `if pii in val` loop at ~line 676)
- Test: `tests/test_widget_redaction.py` (append one test; file already has `_create_pdf_with_widgets`, `tempfile`, `Path`, `fitz`, `RedactionItem`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_widget_redaction.py` (inside class `TestWidgetRedaction` or as a module-level test — module-level shown here):

```python
def test_short_name_does_not_substring_delete_widget():
    """Redacting the 3-char name 'Joe' must use word-boundary matching: it must
    delete a widget valued exactly 'Joe' but NOT one containing 'Joelle'."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.pdf"
        out = Path(tmp) / "output.pdf"
        _create_pdf_with_widgets(src, {
            "Sibling": "Joelle attends the same school",
            "Student": "Joe",
        })

        redactor = PDFRedactor()
        items = [RedactionItem(page_num=1, text="Joe")]
        success, msg = redactor.redact_pdf(src, out, items)

        assert success, msg
        doc = fitz.open(str(out))
        page = doc[0]
        remaining = {w.field_name: w.field_value for w in page.widgets()}
        assert "Sibling" in remaining, "'Joelle' widget must NOT be deleted by 'Joe'"
        assert remaining["Sibling"] == "Joelle attends the same school"
        assert "Student" not in remaining, "widget valued exactly 'Joe' must be deleted"
        doc.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_widget_redaction.py::test_short_name_does_not_substring_delete_widget -v
```
Expected: FAIL — `"joe" in "joelle attends the same school"` is True today, so the `Sibling` widget is wrongly deleted.

- [ ] **Step 3: Apply the fix**

In `src/core/redactor.py`, inside `_delete_pii_widgets`, replace:

```python
            for pii in redacted_texts:
                if pii in val:
                    names_to_delete.append(w.field_name)
                    break
```
with:
```python
            for pii in redacted_texts:
                # Word-boundary match, not raw substring: a short name like
                # "Joe" must not delete a widget containing "Joelle" or "major".
                if pii and re.search(r"\b" + re.escape(pii) + r"\b", val):
                    names_to_delete.append(w.field_name)
                    break
```

(`re` is already imported at `src/core/redactor.py:9`. `val` and `pii` are both already lowercased above this loop, so matching stays case-insensitive.)

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_widget_redaction.py -v
```
Expected: the new test PASSES and all existing widget tests still PASS — in particular `test_partial_match_deletes_widget` (value `"Assessment for JOE BLOGGS - Year 6"`, PII `"JOE BLOGGS"`) still matches because `\bjoe bloggs\b` is present as whole words.

- [ ] **Step 5: Commit**

```bash
git add src/core/redactor.py tests/test_widget_redaction.py
git commit -m "fix(redactor): word-boundary match for form-widget deletion

_delete_pii_widgets used a raw substring test, so a 3-char name like 'Joe'
would delete an unrelated widget containing 'Joelle'. Use a \\b...\\b match.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: NER runtime failure re-raises under `require_ner`

**Files:**
- Modify: `src/core/pii_orchestrator.py` (method `PIIOrchestrator._run_presidio`, the `except Exception: pass` at ~line 211)
- Test: `tests/test_pii_orchestrator.py` (append two tests; file already imports `pytest`, `PIIOrchestrator`)

- [ ] **Step 1: Write the failing tests**

Add this import near the top of `tests/test_pii_orchestrator.py` (after the existing imports):

```python
from unittest.mock import patch, MagicMock
```

Append these tests:

```python
def _orchestrator(require_ner):
    # Skip the heavy spaCy load — inject a mock analyzer instead.
    with patch.object(PIIOrchestrator, "_init_presidio", lambda self: None):
        return PIIOrchestrator("Joe Bloggs", require_ner=require_ner)


def test_run_presidio_reraises_when_ner_required():
    o = _orchestrator(require_ner=True)
    o.presidio_analyzer = MagicMock()
    o.presidio_analyzer.analyze.side_effect = RuntimeError("spaCy crashed")
    with pytest.raises(RuntimeError):
        o._run_presidio("Some document text", 1)


def test_run_presidio_degrades_when_ner_optional():
    o = _orchestrator(require_ner=False)
    o.presidio_analyzer = MagicMock()
    o.presidio_analyzer.analyze.side_effect = RuntimeError("spaCy crashed")
    result = o._run_presidio("Some document text", 1)
    assert result == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py::test_run_presidio_reraises_when_ner_required tests/test_pii_orchestrator.py::test_run_presidio_degrades_when_ner_optional -v
```
Expected: `test_run_presidio_reraises_when_ner_required` FAILS (today the exception is swallowed and `[]` is returned). `test_run_presidio_degrades_when_ner_optional` already PASSES.

- [ ] **Step 3: Apply the fix**

In `src/core/pii_orchestrator.py`, inside `_run_presidio`, replace:

```python
        except Exception:
            pass  # Graceful degradation

        return matches
```
with:
```python
        except Exception as e:
            # When NER is required (bundled desktop app), a runtime failure
            # means names may have gone undetected — surface it instead of
            # silently falling back to regex-only results.
            if self.require_ner:
                raise RuntimeError(f"NER analysis failed: {e}") from e
            # Optional NER (Streamlit) degrades gracefully to regex-only.

        return matches
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py -v
```
Expected: both new tests PASS and all existing orchestrator tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_orchestrator.py tests/test_pii_orchestrator.py
git commit -m "fix(orchestrator): surface NER runtime failures when require_ner

_run_presidio swallowed all analyzer exceptions. In the bundled desktop app
(require_ner=True) that silently dropped NER-discovered names. Re-raise there;
keep graceful degradation for the optional Streamlit path.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Stop leaking `fitz` handles in coordinate extraction and preview

**Files:**
- Modify: `src/core/text_extractor.py` (method `TextExtractor.get_text_with_coordinates`, ~lines 245–266)
- Modify: `backend/main.py` (endpoint `preview_page`, ~lines 297–321)
- Test (create): `tests/test_text_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_extractor.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
from text_extractor import TextExtractor


def _make_pdf(path, text="Hello world"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_coords_returns_empty_and_does_not_raise_on_bad_page():
    """An out-of-range page must return [] and must not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src)
        extractor = TextExtractor()
        result = extractor.get_text_with_coordinates(src, page_num=99)
        assert result == []


def test_coords_closes_document_even_on_error():
    """The opened fitz document must be closed even when page access raises."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src)
        extractor = TextExtractor()
        opened = []
        real_open = fitz.open

        def tracking_open(*a, **k):
            d = real_open(*a, **k)
            opened.append(d)
            return d

        # page_num=99 is out of range → indexing raises inside the try block.
        with patch("text_extractor.fitz.open", tracking_open):
            extractor.get_text_with_coordinates(src, page_num=99)

        assert opened, "a document should have been opened"
        assert opened[0].is_closed, "document must be closed on the error path"


def test_coords_happy_path_returns_spans():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src, "Findable text here")
        extractor = TextExtractor()
        result = extractor.get_text_with_coordinates(src, page_num=1)
        assert any("Findable" in text for text, _bbox in result)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_text_extractor.py -v
```
Expected: `test_coords_closes_document_even_on_error` FAILS (today `doc.close()` is skipped when indexing raises, so `is_closed` is False). The other two may already PASS.

- [ ] **Step 3: Apply the `text_extractor.py` fix**

In `src/core/text_extractor.py`, in `get_text_with_coordinates`, replace:

```python
        try:
            doc = fitz.open(str(pdf_path))
            page = doc[page_num - 1]

            # Get text with coordinates
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if block.get('type') == 0:  # Text block
                    for line in block.get('lines', []):
                        for span in line.get('spans', []):
                            text = span.get('text', '').strip()
                            bbox = span.get('bbox')
                            if text and bbox:
                                results.append((text, bbox))

            doc.close()

        except Exception as e:
            print(f"Error extracting coordinates: {str(e)}")

        return results
```
with:
```python
        try:
            with fitz.open(str(pdf_path)) as doc:
                page = doc[page_num - 1]

                # Get text with coordinates
                blocks = page.get_text("dict")["blocks"]

                for block in blocks:
                    if block.get('type') == 0:  # Text block
                        for line in block.get('lines', []):
                            for span in line.get('spans', []):
                                text = span.get('text', '').strip()
                                bbox = span.get('bbox')
                                if text and bbox:
                                    results.append((text, bbox))

        except Exception as e:
            print(f"Error extracting coordinates: {str(e)}")

        return results
```

- [ ] **Step 4: Run the text_extractor tests to verify they pass**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_text_extractor.py -v
```
Expected: all three PASS.

- [ ] **Step 5: Apply the `backend/main.py` preview fix**

In `backend/main.py`, in `preview_page`, replace the block from the page-range check through the return:

```python
    if req.page_num < 0 or req.page_num >= len(doc):
        doc.close()
        raise HTTPException(
            status_code=400,
            detail=f"Page {req.page_num} out of range (0-{len(doc) - 1})",
        )

    page = doc[req.page_num]
    # 150 DPI: multiply by 150/72
    mat = fitz.Matrix(150 / 72, 150 / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    total = len(doc)
    doc.close()

    return PreviewResponse(
        image_base64=base64.b64encode(img_bytes).decode("ascii"),
        total_pages=total,
        page_num=req.page_num,
    )
```
with:
```python
    try:
        if req.page_num < 0 or req.page_num >= len(doc):
            raise HTTPException(
                status_code=400,
                detail=f"Page {req.page_num} out of range (0-{len(doc) - 1})",
            )

        page = doc[req.page_num]
        # 150 DPI: multiply by 150/72
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        total = len(doc)

        return PreviewResponse(
            image_base64=base64.b64encode(img_bytes).decode("ascii"),
            total_pages=total,
            page_num=req.page_num,
        )
    finally:
        doc.close()
```

- [ ] **Step 6: Add a preview regression test**

Append to `tests/test_text_extractor.py`:

```python
def test_preview_endpoint_closes_doc_and_validates_range():
    """The /api/preview endpoint must close its document on both the happy
    path and the out-of-range path, and still return the documented results."""
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as bm

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.pdf"
        _make_pdf(src, "Preview me")

        opened = []
        real_open = fitz.open

        def tracking_open(*a, **k):
            d = real_open(*a, **k)
            opened.append(d)
            return d

        client = TestClient(app)
        with patch.object(bm.fitz, "open", tracking_open):
            ok = client.post("/api/preview", json={"pdf_path": str(src), "page_num": 0})
            bad = client.post("/api/preview", json={"pdf_path": str(src), "page_num": 99})

        assert ok.status_code == 200
        assert ok.json()["total_pages"] == 1
        assert bad.status_code == 400
        assert opened, "preview should have opened documents"
        assert all(d.is_closed for d in opened), "every opened doc must be closed"
```

Note: `preview_page` does `import fitz` at function scope, which binds the module-global `fitz` already imported in `backend/main.py`; patching `backend.main.fitz.open` covers it. If `backend.main` is not importable due to path setup, run from the repo root (pytest's default) — `backend/` is a package with `__init__.py`.

- [ ] **Step 7: Run the full preview + extractor test file**

Run:
```bash
venv/bin/python3.13 -m pytest tests/test_text_extractor.py -v
```
Expected: all tests PASS, including `test_preview_endpoint_closes_doc_and_validates_range`.

- [ ] **Step 8: Commit**

```bash
git add src/core/text_extractor.py backend/main.py tests/test_text_extractor.py
git commit -m "fix: close fitz handles on error in coord extraction and preview

get_text_with_coordinates and the /api/preview endpoint skipped doc.close()
on exception paths, leaking file handles on a frequently-hit preview path.
Use a context manager / try-finally so the document always closes.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Run the full suite and compare against the pre-flight baseline**

```bash
venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -15
```
Expected: baseline pass count **+ 11 new tests** (3 Task 1, 1 Task 2, 1 Task 3, 2 Task 4, 4 Task 5), with no new failures. Any `test_ocr_verification.py` failures present in the pre-flight baseline are pre-existing (Tesseract env) and out of scope — confirm the count is unchanged, not that it is zero.

- [ ] **Confirm the branch and commit log**

```bash
git log --oneline -6
git rev-parse --abbrev-ref HEAD   # expect: test
```
Five new commits on `test`. **Do not push or merge** without explicit sign-off.

---

## Self-Review

**Spec coverage:** All five Batch-A findings (#1, #3, #9, #2, #6) map to Tasks 1–5 respectively, each with a failing test that exercises the defect. ✓

**Placeholder scan:** No TBD/TODO/"add error handling" — every step shows the exact old→new code and exact commands. ✓

**Type/name consistency:** `RedactionItem(page_num=…, text=…)` matches the dataclass at `redactor.py:80`; `PDFRedactor._strip_metadata(self, doc)`, `_check_tesseract`, `_delete_pii_widgets`, `_run_presidio`, `get_text_with_coordinates(self, pdf_path, page_num)`, and `TextExtractor` are all real symbols verified in source. `require_ner` is a real `PIIOrchestrator.__init__` parameter. ✓

**Cross-task interaction:** Task 2's `RuntimeError` depends on Task 1's `try/finally` to produce the clean `(False, msg)` and partial-output cleanup asserted in its test — so Tasks must run in order (1 before 2). All other tasks are independent. ✓
