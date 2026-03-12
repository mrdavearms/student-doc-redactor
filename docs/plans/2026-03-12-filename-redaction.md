# Filename PII Redaction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Strip the student's name (and parent/family names) from output filenames while preserving document-type context words.

**Architecture:** A pure `strip_pii_from_filename()` function in `redactor.py` applies word-boundary regex substitutions using the same name variation list `PIIDetector` already computes. The service builds and passes variations; the completion screen shows an original→redacted filename mapping table.

**Tech Stack:** Python `re` module, existing `PIIDetector.name_variations`, Streamlit for the UI mapping table.

---

## Key Files

| File | Role |
|---|---|
| `src/core/redactor.py` | Add `strip_pii_from_filename()` |
| `src/services/redaction_service.py` | Add fields to `RedactionRequest`, wire variations through pipeline |
| `src/ui/screens.py` | Pass names to request, store results, show mapping table |
| `tests/test_filename_redaction.py` | New — 12 tests for the strip function |

## Critical context before starting

- `_process_document()` in `redaction_service.py` calls `redact_pdf()` directly (line 210), **not** `create_redacted_copy()`. Filename logic lives in `_process_document()`.
- `PIIDetector.name_variations` is already a public attribute — student name variations only (parents/family are separate).
- The `re` module is not yet imported in `redactor.py` — you'll need to add it.
- `DocumentResult.document_name` stores the **original** filename (e.g. `Joe Bloggs Report.pdf`). After this change, `output_path.name` will differ — store `document_results` in session state for the completion screen to use.

---

## Task 1: Write failing tests for `strip_pii_from_filename`

**Files:**
- Create: `tests/test_filename_redaction.py`

**Step 1: Create the test file**

```python
"""Tests for strip_pii_from_filename — filename PII redaction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.redactor import strip_pii_from_filename

BLOGGS_VARIATIONS = ["Joe Bloggs", "Joe", "Bloggs", "J. Bloggs", "J.F.", "JF"]


class TestStripPiiFromFilename:

    def test_name_in_prefix(self):
        result = strip_pii_from_filename(
            "Joe Bloggs DIP Vineland Report 2025", BLOGGS_VARIATIONS
        )
        assert result == "DIP Vineland Report 2025"

    def test_name_in_suffix(self):
        result = strip_pii_from_filename(
            "Vineland Report - Joe Bloggs", BLOGGS_VARIATIONS
        )
        assert result == "Vineland Report"

    def test_name_embedded_with_brackets(self):
        result = strip_pii_from_filename(
            "Behavior Management Plan - Joe Bloggs (T1 2024)", BLOGGS_VARIATIONS
        )
        assert result == "Behavior Management Plan (T1 2024)"

    def test_underscore_separated(self):
        result = strip_pii_from_filename(
            "Bloggs_Joe_Adaptive_Behaviour_Assessment_Summary", BLOGGS_VARIATIONS
        )
        assert result == "Adaptive Behaviour Assessment Summary"

    def test_parent_name_stripped(self):
        variations = BLOGGS_VARIATIONS + ["Mary Bloggs"]
        result = strip_pii_from_filename(
            "Overview of Joe's behaviours - Mary Bloggs", variations
        )
        assert result == "Overview of behaviours"

    def test_possessive_cleaned(self):
        result = strip_pii_from_filename(
            "Joe's Assessment Report", BLOGGS_VARIATIONS
        )
        assert result == "Assessment Report"

    def test_no_pii_passthrough(self):
        result = strip_pii_from_filename("AA report", BLOGGS_VARIATIONS)
        assert result == "AA report"

    def test_short_variation_not_stripped(self):
        # "JF" is 2 chars — must be skipped; "JFK" must not be touched
        result = strip_pii_from_filename("JFKAirport Report", BLOGGS_VARIATIONS)
        assert result == "JFKAirport Report"

    def test_empty_result_fallback(self):
        result = strip_pii_from_filename("Joe", BLOGGS_VARIATIONS)
        assert result == "document"

    def test_short_result_fallback(self):
        # After stripping, only "A" remains — too short, use fallback
        result = strip_pii_from_filename("Joe A", BLOGGS_VARIATIONS)
        assert result == "document"

    def test_empty_variations_passthrough(self):
        result = strip_pii_from_filename("Report 2025", [])
        assert result == "Report 2025"

    def test_longest_variation_matched_first(self):
        # "Joe Bloggs" stripped as a unit — result has no double-space
        result = strip_pii_from_filename(
            "Joe Bloggs Report", ["Joe Bloggs", "Joe", "Bloggs"]
        )
        assert result == "Report"
```

**Step 2: Run to confirm they all fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
venv/bin/python -m pytest tests/test_filename_redaction.py -v
```

Expected: `ImportError: cannot import name 'strip_pii_from_filename'`

---

## Task 2: Implement `strip_pii_from_filename` in `redactor.py`

**Files:**
- Modify: `src/core/redactor.py` (lines 1–12, add `import re` and the new function)

**Step 1: Add `import re` at the top of `redactor.py`**

The current imports (lines 6–10) are:
```python
import io
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
```

Add `import re` after `import io`:
```python
import io
import re
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
```

**Step 2: Add `strip_pii_from_filename` as a module-level function after the imports, before `RedactionItem`**

Insert this block after line 11 (after the imports) and before line 14 (`@dataclass`):

```python
def strip_pii_from_filename(stem: str, name_variations: List[str]) -> str:
    """
    Remove PII name tokens from a filename stem, preserving document-type words.

    Args:
        stem: Filename without extension (e.g. "Joe Bloggs DIP Vineland Report 2025")
        name_variations: List of name strings to strip (student, parents, family).
                         Entries shorter than 3 chars are ignored.

    Returns:
        Cleaned stem, or "document" if the result is too short to be meaningful.
    """
    if not name_variations:
        return stem

    # Normalize underscores → spaces so word boundaries work on "Bloggs_Joe_..." format
    result = stem.replace('_', ' ')

    # Sort longest-first: strip "Joe Bloggs" before "Joe" to avoid orphaned fragments
    sorted_variations = sorted(name_variations, key=len, reverse=True)

    for variation in sorted_variations:
        if len(variation) < 3:
            continue
        pattern = re.compile(r'\b' + re.escape(variation) + r'\b', re.IGNORECASE)
        result = pattern.sub('', result)

    # Remove possessive remnants: "Joe's" → "'s" → ""
    result = re.sub(r"'s\b", '', result)

    # Collapse runs of spaces
    result = re.sub(r' {2,}', ' ', result)

    # Remove empty brackets left by name removal: "( )", "[]", "(  )"
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\[\s*\]', '', result)

    # Collapse double separators: "Plan -  - Report" or "Plan - - Report" → "Plan - Report"
    result = re.sub(r'(\s*-\s*){2,}', ' - ', result)

    # Strip leading/trailing separators and whitespace
    result = result.strip(' -_,.')

    # Final space normalise
    result = re.sub(r' {2,}', ' ', result).strip()

    # Fallback: if result is empty or too short to be a real name, use generic label
    if len(result) < 3:
        return 'document'

    return result
```

**Step 3: Run tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
venv/bin/python -m pytest tests/test_filename_redaction.py -v
```

Expected: 12 passed.

**Step 4: Run full suite to confirm no regressions**

```bash
venv/bin/python -m pytest tests/ -v --ignore=tests/test_ocr_verification.py -q
```

Expected: all existing tests pass (5 OCR tests skipped — pre-existing Tesseract env issue).

**Step 5: Commit**

```bash
git add tests/test_filename_redaction.py src/core/redactor.py
git commit -m "feat: add strip_pii_from_filename with 12 passing tests"
```

---

## Task 3: Wire name variations through the service layer

**Files:**
- Modify: `src/services/redaction_service.py`

**Step 1: Add `parent_names` and `family_names` fields to `RedactionRequest`**

The current `RedactionRequest` dataclass (lines 17–28) ends with `folder_action`. Add two new fields with defaults so existing callers don't break:

```python
@dataclass
class RedactionRequest:
    """Everything needed to perform a redaction run"""
    folder_path: Path
    student_name: str
    documents: List[Path]
    detected_pii: Dict[Path, dict]
    user_selections: Dict[str, bool]
    folder_action: Optional[str] = None
    parent_names: List[str] = field(default_factory=list)   # NEW
    family_names: List[str] = field(default_factory=list)   # NEW
```

**Step 2: Import `PIIDetector` at the top of `redaction_service.py`**

Current imports (lines 12–14):
```python
from src.core.pii_detector import PIIMatch
from src.core.redactor import PDFRedactor, RedactionItem
from src.core.logger import RedactionLogger, LogEntry
```

Update the first line:
```python
from src.core.pii_detector import PIIDetector, PIIMatch
from src.core.redactor import PDFRedactor, RedactionItem, strip_pii_from_filename
from src.core.logger import RedactionLogger, LogEntry
```

**Step 3: Build `name_variations` in `execute()` and pass it to `_process_document()`**

In `execute()` (lines 84–129), after step 2 (Initialise logger), add variation building and pass it through:

Replace the `for doc in request.documents:` loop:

```python
        # 2. Initialise logger
        logger = RedactionLogger(request.folder_path, request.student_name)

        # 2b. Build name variations for filename stripping
        # Use PIIDetector to get student name variations, then append parent/family names
        _detector = PIIDetector(
            request.student_name,
            request.parent_names,
            request.family_names,
        )
        name_variations = list(_detector.name_variations)
        for name in request.parent_names + request.family_names:
            if len(name) >= 3 and name not in name_variations:
                name_variations.append(name)

        # 3. Process each document
        results = RedactionResults(redacted_folder=redacted_folder)

        for doc in request.documents:
            doc_result = self._process_document(
                doc=doc,
                detected_pii=request.detected_pii,
                user_selections=request.user_selections,
                redacted_folder=redacted_folder,
                logger=logger,
                name_variations=name_variations,   # NEW
            )
            results.document_results.append(doc_result)
```

**Step 4: Update `_process_document()` signature and filename logic**

Current signature (line 152):
```python
    def _process_document(
        self,
        doc: Path,
        detected_pii: Dict[Path, dict],
        user_selections: Dict[str, bool],
        redacted_folder: Path,
        logger: RedactionLogger,
    ) -> DocumentResult:
```

New signature:
```python
    def _process_document(
        self,
        doc: Path,
        detected_pii: Dict[Path, dict],
        user_selections: Dict[str, bool],
        redacted_folder: Path,
        logger: RedactionLogger,
        name_variations: List[str] = None,   # NEW
    ) -> DocumentResult:
```

**Step 5: Replace the hardcoded output filename (two places in `_process_document`)**

Current line 200 (log entry `output_name`):
```python
                output_name=f"{doc.stem}_redacted.pdf",
```

Current line 210 (output path):
```python
        output_path = redacted_folder / f"{doc.stem}_redacted.pdf"
        success, message = self._redactor.redact_pdf(doc, output_path, redaction_items)
```

Replace **both** with the stripped version. Insert this block before the log-entry loop (before line 192 `redaction_items = []`):

```python
        # Compute safe output filename (strips PII from stem)
        safe_stem = strip_pii_from_filename(doc.stem, name_variations or [])
        output_filename = f"{safe_stem}_redacted.pdf"

        # Collision guard: if another file already produced the same stripped name
        counter = 2
        while (redacted_folder / output_filename).exists():
            output_filename = f"{safe_stem}_{counter}_redacted.pdf"
            counter += 1

        output_path = redacted_folder / output_filename
```

Then update the log entry (line 200) to use `output_filename`:
```python
                output_name=output_filename,
```

And remove the old `output_path` line (line 210) — it's now set above.

The `success, message = self._redactor.redact_pdf(...)` call stays but references the already-set `output_path`.

**Step 6: Run the full test suite**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
venv/bin/python -m pytest tests/ -v --ignore=tests/test_ocr_verification.py -q
```

Expected: all passing, including the 12 new filename tests.

**Step 7: Commit**

```bash
git add src/services/redaction_service.py
git commit -m "feat: wire name_variations through service layer for filename stripping"
```

---

## Task 4: Update `screens.py` — pass names to request, store results, show mapping table

**Files:**
- Modify: `src/ui/screens.py`

**Step 1: Pass `parent_names` and `family_names` into `RedactionRequest`**

Find the `RedactionRequest(...)` constructor call (around line 431). It currently looks like:

```python
    request = RedactionRequest(
        folder_path=st.session_state.folder_path,
        student_name=st.session_state.student_name,
        documents=st.session_state.documents,
        detected_pii=st.session_state.detected_pii,
        user_selections=st.session_state.user_selections,
        folder_action=folder_action,
    )
```

Add the two new fields (parse from session state the same way detection does — see lines 191–192):

```python
    _parent_list = [n.strip() for n in st.session_state.parent_names.split(',') if n.strip()]
    _family_list = [n.strip() for n in st.session_state.family_names.split(',') if n.strip()]

    request = RedactionRequest(
        folder_path=st.session_state.folder_path,
        student_name=st.session_state.student_name,
        documents=st.session_state.documents,
        detected_pii=st.session_state.detected_pii,
        user_selections=st.session_state.user_selections,
        folder_action=folder_action,
        parent_names=_parent_list,    # NEW
        family_names=_family_list,    # NEW
    )
```

**Step 2: Store `document_results` in session state**

After `results = service.execute(request)`, the block currently stores:

```python
    st.session_state.redacted_folder = results.redacted_folder
    st.session_state.log_content = results.log_content
    st.session_state.verification_failures = results.verification_failures
    st.session_state.ocr_warnings = results.ocr_warnings
    st.session_state.processing_complete = True
```

Add one more line:

```python
    st.session_state.document_results = results.document_results   # NEW
```

**Step 3: Add filename mapping table to `completion_screen()`**

In `completion_screen()`, find the `#### Redacted Documents` section (around line 476):

```python
    st.markdown("#### Redacted Documents")
    st.info(f"Saved to: `{st.session_state.redacted_folder}`")
```

Replace it with:

```python
    st.markdown("#### Redacted Documents")
    st.info(f"Saved to: `{st.session_state.redacted_folder}`")

    # Filename mapping table — shows original → redacted name for audit trail
    document_results = st.session_state.get('document_results', [])
    if document_results:
        renamed = [
            r for r in document_results
            if r.output_path and r.output_path.name != f"{Path(r.document_name).stem}_redacted.pdf"
        ]
        if renamed:
            st.markdown("**Filename changes (PII removed from names):**")
            for r in renamed:
                original_stem = Path(r.document_name).stem
                new_name = r.output_path.name
                st.markdown(f"- `{original_stem}.pdf` → `{new_name}`")
```

You'll need `Path` imported — check the top of `screens.py` for existing imports. If `from pathlib import Path` is not already there, add it.

**Step 4: Run the full test suite one final time**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
venv/bin/python -m pytest tests/ -v --ignore=tests/test_ocr_verification.py -q
```

Expected: all passing.

**Step 5: Smoke test with Streamlit**

If Streamlit is not running:
```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
venv/bin/python -m streamlit run app.py --server.headless false &
```

Open http://localhost:8501, process the `sample/` folder with student name `Joe Bloggs` and parent name `Mary Bloggs`. On the completion screen, verify:
- `Joe Bloggs DIP Vineland Report 2025_redacted.pdf` → `DIP Vineland Report 2025_redacted.pdf`
- `Bloggs_Joe_Adaptive_Behaviour_Assessment_Summary_redacted.pdf` → `Adaptive Behaviour Assessment Summary_redacted.pdf`
- `AA report_redacted.pdf` → unchanged (no PII in name)

**Step 6: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: show original→redacted filename mapping on completion screen"
```

---

## Done

All 4 tasks complete. Final check:

```bash
venv/bin/python -m pytest tests/ -q --ignore=tests/test_ocr_verification.py
git log --oneline -5
```
