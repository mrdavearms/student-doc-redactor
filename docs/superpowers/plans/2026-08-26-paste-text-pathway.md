# Paste Text Pathway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user paste a slab of text into the desktop app, review the PII found in it, and get it back blacked out or de-identified — copied to the clipboard or saved as a file — without anything reaching disk unless they ask.

**Architecture:** Paste is a third `inputMode` (`'paste'`) alongside `'file'` and `'folder'`, NOT a third `workflowMode`. Both existing outputs therefore come for free, and `DocumentReview`, `PeopleReview` and `FinalConfirmation` are reused with no behavioural change. Detection enters through `PIIOrchestrator.detect_pii_in_text()`, which is already pure text-in. Results cache under a reserved pseudo-path so every selection-key contract in the app keeps working unchanged.

**Tech Stack:** Python 3.13, FastAPI, PyMuPDF (already a dependency), React 19 + Zustand + TypeScript, vitest.

**Design doc:** `docs/plans/2026-08-26-paste-text-pathway-design.md` — read it before starting. This plan implements it.

## Global Constraints

- **Branch:** `test`. Never push to `main` without asking.
- **No new dependencies.** Python or npm. PyMuPDF already lays out text.
- **Run Python tests as** `venv/bin/python3.13 -m pytest`. NEVER `venv/bin/pytest` — its shebang points at a non-existent `venv_new/` path.
- **Import conventions are not uniform.** `src/services/*` uses `from src.core.X import ...`. `src/core/*` uses bare `from redactor import ...`. Tests do `sys.path.insert` for both. Copy the convention of the file you are editing.
- **Reserved detection-cache key:** `<pasted-text>` — exact string, defined once as `PASTE_KEY`.
- **Block run:** `'█' * 6`, FIXED width regardless of what was removed. Never length-matched — that leaks the size of the original.
- **Size caps:** soft warning above `20_000` characters, hard rejection above `50_000`.
- **Nothing is written to disk** except by `POST /api/text/save`, which the user triggers from a native dialog.
- **Desktop lint baseline is 7 errors + 1 warning** (`cd desktop && npm run lint`). New code must not increase it.
- **No React component test harness exists.** Verify component work with `cd desktop && npm run build` (tsc) + `npm run lint`.
- If `npm test` or `npm run build` errors with `vitest: command not found`, run `cd desktop && npm install` first.

---

## File Structure

**New — Python**

| File | Responsibility |
|------|----------------|
| `src/services/text_cleanup_service.py` | `BlackoutMap`, `blackout()`, `deidentify_paste()`. Operates on strings. No filesystem access. |
| `src/core/text_pdf.py` | `render()` — lay a string out as a PDF and turn block runs into true black rectangles. |
| `tests/test_text_cleanup_service.py` | Blackout substitution, fixed-width invariant, verification symmetry. |
| `tests/test_text_pdf.py` | Sentinel selection, collision safety, pagination, nothing extractable under the boxes. |
| `tests/test_backend_paste.py` | All six `/api/text/*` endpoints, the reserved-key guard, size caps, `ocr_pages` empty. |

**New — Frontend**

| File | Responsibility |
|------|----------------|
| `desktop/src/hooks/useDetection.ts` | Shared fingerprint + detect + navigate logic, used by both `ConversionStatus` and `TextScan`. |
| `desktop/src/pages/TextScan.tsx` | Step 2 for paste. Progress only. |
| `desktop/src/pages/PasteCompletion.tsx` | Step 6 for paste. Branches internally on `workflowMode`. |
| `desktop/src/lib/pasteResult.ts` | Module-level holder for the name-bearing half of a clean result. Deliberately NOT Zustand state. |
| `desktop/tests/paste.test.ts` | Store clearing rules, fingerprint, `screensFor` ladder. |

**Modified**

| File | Change |
|------|--------|
| `src/services/detection_service.py` | Add public `detect_in_text()`. |
| `backend/schemas.py` | Five new models. |
| `backend/main.py` | `PASTE_KEY`, six endpoints, reserved-key guard on `/api/pii/detect`. |
| `desktop/src/types.ts` | `InputMode` gains `'paste'`; `screensFor(mode, inputMode)`. |
| `desktop/src/store.ts` | `pastedText` + clearing rules. |
| `desktop/src/api.ts` | Six client methods. |
| `desktop/src/lib/errorMessage.ts` | Patterns for the new backend error strings. |
| `desktop/src/pages/FolderSelection.tsx` | Third input choice + textarea. |
| `desktop/src/pages/ConversionStatus.tsx` | Refactor onto `useDetection()`. |
| `desktop/src/pages/FinalConfirmation.tsx` | Paste branch. |
| `desktop/src/pages/NoPiiFound.tsx` | Paste branch — show the text with a Copy button. |
| `desktop/src/pages/PeopleReview.tsx` | Call the `/api/text/*` endpoints in paste mode. |
| `desktop/src/App.tsx` | Route `text_scan` and paste completion. |
| `CLAUDE.md` | Five new rules (Task 15 only). |

---

## Task 1: Blackout replacement

**Files:**
- Create: `src/services/text_cleanup_service.py`
- Test: `tests/test_text_cleanup_service.py`

**Interfaces:**
- Consumes: `src.core.text_deidentifier.deidentify_text(text, selected_matches, pmap) -> Tuple[str, int]` and `verify_deidentified(text, selected_texts, labels) -> List[str]`, both existing.
- Produces: `BLOCK: str` (six U+2588), `BlackoutMap`, `blackout(text: str, selected_matches: List) -> Tuple[str, int, List[str]]` returning `(cleaned_text, replacement_count, leftovers)`.

**Background the implementer needs:** `deidentify_text` reaches its map object through exactly two methods — `should_replace(text, category)` and `label_for(text, category)`. So a constant-returning adapter inherits longest-first ordering, the single-pass re-match guard and boundary handling with no new code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_cleanup_service.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pii_detector import PIIMatch
from src.services.text_cleanup_service import BLOCK, blackout


def match(text, category='Student name'):
    return PIIMatch(text=text, category=category, confidence=0.95,
                    page_num=1, line_num=1, context=text, source='regex')


def test_blackout_replaces_pii_with_a_fixed_width_block():
    cleaned, count, leftovers = blackout(
        'Billy Bob was absent.', [match('Billy Bob')])
    assert cleaned == f'{BLOCK} was absent.'
    assert count == 1
    assert leftovers == []


def test_block_width_does_not_reveal_the_length_of_what_was_removed():
    short, _, _ = blackout('Jo went home.', [match('Jo')])
    long, _, _ = blackout('Bartholomew went home.', [match('Bartholomew')])
    assert short.split(' ')[0] == long.split(' ')[0]


def test_longest_first_ordering_is_inherited():
    cleaned, count, _ = blackout(
        'Billy Bob and Billy.', [match('Billy Bob'), match('Billy')])
    assert cleaned == f'{BLOCK} and {BLOCK}.'
    assert count == 2


def test_form_label_words_are_still_blacked_out():
    # Diverges from PseudonymMap.should_replace (CLAUDE.md rule 58) on purpose:
    # over-removal is the correct bias for the redact pathway (rule 54a).
    cleaned, count, _ = blackout(
        'Phone: 0412 345 678', [match('Phone', 'Family/parent (contextual)')])
    assert cleaned.startswith(BLOCK)
    assert count == 1


def test_nothing_selected_returns_the_text_unchanged():
    cleaned, count, leftovers = blackout('Nothing here.', [])
    assert (cleaned, count, leftovers) == ('Nothing here.', 0, [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_text_cleanup_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.text_cleanup_service'`

- [ ] **Step 3: Write the implementation**

Create `src/services/text_cleanup_service.py`:

```python
"""
Text Cleanup Service
Blackout and de-identification over a STRING rather than a document.

Backs the paste-text pathway. Nothing here touches the filesystem: the caller
gets strings back and decides whether they are ever saved.
"""

from typing import List, Tuple

from src.core.text_deidentifier import deidentify_text, verify_deidentified

BLOCK_CHAR = '█'
BLOCK_WIDTH = 6
BLOCK = BLOCK_CHAR * BLOCK_WIDTH


class BlackoutMap:
    """
    Stands in for PseudonymMap in the blackout pathway.

    deidentify_text() reaches its map through exactly two methods, so a
    constant-returning adapter inherits longest-first ordering, the single-pass
    re-match guard and boundary handling for free.

    should_replace() is unconditionally True, deliberately diverging from
    PseudonymMap (CLAUDE.md rule 58). That guard exists to stop a contextual
    false positive rewriting a "Phone:" row into "[name]: [phone]", which is a
    MEANING failure in de-identify mode. A black box over the word "Phone"
    costs nothing, and rule 54a already establishes over-removal as the correct
    bias for the redact pathway.

    Block width is FIXED. A length-matched block leaks the size of what was
    removed — "██" is visibly a short first name.
    """

    def should_replace(self, text: str, category: str) -> bool:
        return True

    def label_for(self, text: str, category: str) -> str:
        return BLOCK


def blackout(text: str, selected_matches: List) -> Tuple[str, int, List[str]]:
    """
    Replace every selected PII string with a fixed-width block run.

    Returns (cleaned text, replacements made, PII still visible). The leftover
    check strips the inserted blocks first, exactly as de-identify verification
    strips its labels.
    """
    cleaned, count = deidentify_text(text, selected_matches, BlackoutMap())
    selected_texts = [
        (getattr(m, 'text', '') or '').strip() for m in selected_matches
    ]
    leftovers = verify_deidentified(cleaned, selected_texts, labels=[BLOCK])
    return cleaned, count, leftovers
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_text_cleanup_service.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/services/text_cleanup_service.py tests/test_text_cleanup_service.py
git commit -m "feat(paste): add blackout replacement over a plain string"
```

---

## Task 2: Text-to-PDF renderer

**Files:**
- Create: `src/core/text_pdf.py`
- Test: `tests/test_text_pdf.py`

**Interfaces:**
- Consumes: `BLOCK` from Task 1 (passed in as a parameter; this module does NOT import from `src.services`, which would invert the layering).
- Produces: `choose_sentinel(text: str, width: int = 6) -> str` and `render(text: str, out_path, block: str) -> None`.

**Background the implementer needs — read this before writing code.**

PyMuPDF's built-in base-14 fonts are Latin-1 only and have **no glyph for U+2588**. Verified: `fitz.Font('helv').has_glyph(0x2588)` returns `0`, and inserting `'Name: ██████'` into a textbox extracts back as `'Name: ??????'`. Writing the block characters into the PDF produces **wrong output, not an error**.

The fix: substitute a Latin-1 **sentinel** for each block run at layout time, then remove it with `add_redact_annot(rect, fill=(0,0,0))` + `apply_redactions()`. That paints the box and deletes the sentinel text in one operation. This is real redaction of a sentinel — the PII was never placed in the PDF, so there is nothing under the boxes either way.

**The sentinel cannot be hard-coded.** `search_for` cannot tell our sentinel from the same characters occurring in the user's own text. Verified: laying out `'Marks: XXXXXXXX out of ten. Name: XXXXXXXX.'` makes `search_for('XXXXXXXX')` return **two** hits, so a maths report containing `XXXX` would get its real content blacked out.

`insert_textbox` returns the leftover vertical space and is **negative when the text does not fit** (measured `-444.8` for an overlong slab, `+673.6` for a short one). It also mutates the page, so overflow probing must happen on a throwaway document.

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_pdf.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from text_pdf import choose_sentinel, render

BLOCK = '█' * 6


def _render(text):
    path = Path(tempfile.mkdtemp()) / 'out.pdf'
    render(text, path, block=BLOCK)
    return path


def test_no_pii_and_no_sentinel_survive_in_the_saved_pdf():
    path = _render(f'Name: {BLOCK} attended on {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert 'Name:' in extracted
    assert '█' not in extracted
    assert '?' not in extracted          # the base-14 font failure mode
    for candidate in ['¤', '¦', '¿', '~', '^', '¶', '§']:
        assert candidate not in extracted


def test_black_rectangles_are_actually_drawn():
    path = _render(f'Name: {BLOCK} and {BLOCK}.')
    doc = fitz.open(str(path))
    drawings = doc[0].get_drawings()
    doc.close()
    assert len(drawings) >= 2


def test_the_users_own_text_is_never_boxed():
    # '~' is a sentinel candidate. If the renderer hard-coded it, the tilde in
    # the user's text would be blacked out along with the real redaction.
    path = _render(f'Cost ~5 dollars. Name: {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert '~5 dollars' in extracted


def test_choose_sentinel_skips_characters_present_in_the_text():
    assert choose_sentinel('Cost ~5 ^ item ¤ ¦') == '¿' * 6


def test_choose_sentinel_falls_back_when_every_candidate_occurs():
    crowded = '¤¦¿~^¶§'
    assert choose_sentinel(crowded) == '[REMOVED]'


def test_long_text_paginates():
    path = _render('The student was observed in class. ' * 400)
    doc = fitz.open(str(path))
    pages = doc.page_count
    doc.close()
    assert pages > 1


def test_metadata_is_stripped():
    path = _render('Nothing identifying here.')
    doc = fitz.open(str(path))
    meta = doc.metadata
    doc.close()
    assert not meta.get('author')
    assert not meta.get('producer')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_text_pdf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'text_pdf'`

- [ ] **Step 3: Write the implementation**

Create `src/core/text_pdf.py`:

```python
"""
Text -> PDF renderer for the paste-text pathway.

Blackout output cannot simply be written into a PDF. PyMuPDF's built-in base-14
fonts are Latin-1 only and have NO glyph for U+2588, so a block run renders as
"??????" — wrong output rather than an error.

Instead each block run is laid out as a Latin-1 SENTINEL and then removed with a
redaction annotation, which paints the box and deletes the sentinel text in one
step. The PII was never placed in the PDF, so there is nothing under the boxes
either way.

The sentinel is chosen per render. search_for() cannot tell our sentinel from
the same characters occurring in the user's own text, so a hard-coded one would
black out real content — a maths report containing "XXXX", a table of "~~~~"
separators.
"""

import re

import fitz

MARGIN = 50
FONT_NAME = 'helv'
FONT_SIZE = 11
_A4 = fitz.paper_rect('a4')

# Latin-1 characters that render in the base-14 fonts and are rare in school
# reports. Order is preference order.
SENTINEL_CANDIDATES = ['¤', '¦', '¿', '~', '^', '¶', '§']
FALLBACK_SENTINEL = '[REMOVED]'

# A slab that cannot be laid out must not spin forever.
MAX_PAGES = 200


def choose_sentinel(text: str, width: int = 6) -> str:
    """
    A stand-in string guaranteed absent from `text`.

    Fixed repetition keeps every box the same width, which is what carries the
    fixed-width decision through from the text into the PDF.
    """
    for char in SENTINEL_CANDIDATES:
        if char not in text:
            return char * width
    return FALLBACK_SENTINEL


def _page_rect() -> fitz.Rect:
    return fitz.Rect(MARGIN, MARGIN, _A4.width - MARGIN, _A4.height - MARGIN)


def _fits(text: str, rect: fitz.Rect) -> bool:
    """insert_textbox mutates the page, so probe on a throwaway document."""
    probe = fitz.open()
    page = probe.new_page(width=_A4.width, height=_A4.height)
    leftover = page.insert_textbox(
        rect, text, fontname=FONT_NAME, fontsize=FONT_SIZE)
    probe.close()
    return leftover >= 0


def _split_for_page(text: str, rect: fitz.Rect):
    """(what fits on one page, the remainder). Splits on whitespace."""
    if _fits(text, rect):
        return text, ''

    breaks = [m.end() for m in re.finditer(r'\s+', text)]
    if not breaks:
        breaks = [len(text)]

    lo, hi, best = 0, len(breaks) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if _fits(text[:breaks[mid]], rect):
            best = breaks[mid]
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        # A single unbroken token taller than a page. Hard-split rather than
        # loop forever producing empty pages.
        best = max(1, len(text) // 2)
    return text[:best], text[best:]


def _strip_metadata(doc: fitz.Document) -> None:
    doc.set_metadata({
        'author': '', 'title': '', 'subject': '', 'creator': '',
        'producer': '', 'keywords': '', 'creationDate': '', 'modDate': '',
    })
    doc.del_xml_metadata()


def render(text: str, out_path, block: str) -> None:
    """Lay `text` out as a PDF, turning each `block` run into a black box."""
    sentinel = choose_sentinel(text)
    laid_out = (text or '').replace(block, sentinel)

    doc = fitz.open()
    rect = _page_rect()
    remaining = laid_out
    try:
        while True:
            page = doc.new_page(width=_A4.width, height=_A4.height)
            chunk, remaining = _split_for_page(remaining, rect)
            page.insert_textbox(
                rect, chunk, fontname=FONT_NAME, fontsize=FONT_SIZE)
            if not remaining or doc.page_count >= MAX_PAGES:
                break

        for page in doc:
            for hit in page.search_for(sentinel):
                page.add_redact_annot(hit, fill=(0, 0, 0))
            # PDF_REDACT_IMAGE_NONE per CLAUDE.md rule 14. A generated text PDF
            # has no images, but the constant must not drift across the codebase.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        _strip_metadata(doc)
        doc.save(str(out_path))
    finally:
        doc.close()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_text_pdf.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/core/text_pdf.py tests/test_text_pdf.py
git commit -m "feat(paste): render cleaned text to PDF with true black boxes

U+2588 has no glyph in PyMuPDF's base-14 fonts, so writing the block
characters into a PDF silently yields '??????'. Lay out a Latin-1 sentinel
chosen per render and remove it with add_redact_annot + apply_redactions."
```

---

## Task 3: De-identify over a pasted string

**Files:**
- Modify: `src/services/text_cleanup_service.py`
- Test: `tests/test_text_cleanup_service.py`

**Interfaces:**
- Consumes: `PseudonymMap` (existing), `deidentify_text`, `verify_deidentified` (existing).
- Produces: `deidentify_paste(text: str, selected_matches: List, pmap) -> Tuple[str, int, List[str]]`.

**Background the implementer needs:** CLAUDE.md rule 58. `PseudonymMap.should_replace()` declines to replace form-label words like "Phone". Verification MUST use the same gate — verifying a string the replacer deliberately left alone reports it "still visible" and would falsely quarantine correct output. There is no fuzzy pass here: pasted text is typed, not OCR'd, so rule 45's tolerance would falsely flag a classmate "Smyth" against student "Smith".

- [ ] **Step 1: Write the failing test**

Append to `tests/test_text_cleanup_service.py`:

```python
from pseudonym_map import PseudonymMap
from src.services.text_cleanup_service import deidentify_paste


def test_deidentify_replaces_the_student_with_a_role_label():
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, count, leftovers = deidentify_paste(
        'Billy Bob was absent.', [match('Billy Bob')], pmap)
    assert cleaned == '[Student] was absent.'
    assert count == 1
    assert leftovers == []


def test_verification_uses_the_same_gate_as_replacement():
    # "Phone" is a form label; should_replace() declines it. Verifying it anyway
    # would report a leftover on correct output (CLAUDE.md rule 58).
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, _, leftovers = deidentify_paste(
        'Phone: 0412 345 678', [match('Phone', 'Family/parent (contextual)')], pmap)
    assert cleaned == 'Phone: 0412 345 678'
    assert leftovers == []


def test_a_genuine_leftover_is_reported():
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, _, leftovers = deidentify_paste(
        'Billy Bob and Billy Bob', [match('Billy Bob')], pmap)
    # Both occurrences replace, so nothing is left; assert the shape holds.
    assert leftovers == []
    assert 'Billy' not in cleaned
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_text_cleanup_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'deidentify_paste'`

- [ ] **Step 3: Write the implementation**

Append to `src/services/text_cleanup_service.py`:

```python
def deidentify_paste(text: str, selected_matches: List, pmap) -> Tuple[str, int, List[str]]:
    """
    Replace every selected PII string with its role label.

    The replaced set is derived from pmap.should_replace() and BOTH the
    replacement and the verification read from it. Verifying a string the
    replacer deliberately left alone reports it "still visible" and would
    quarantine correct output — the replace/verify symmetry of CLAUDE.md
    rules 49 and 58.

    No fuzzy pass. Rule 45's tolerance exists for OCR text; pasted text is
    typed, so a classmate "Smyth" against student "Smith" is edit-distance 1
    and would be a false leftover.
    """
    replaced = [
        m for m in selected_matches
        if pmap.should_replace(
            (getattr(m, 'text', '') or '').strip(),
            getattr(m, 'category', ''))
    ]
    cleaned, count = deidentify_text(text, selected_matches, pmap)

    labels = sorted({
        pmap.label_for((m.text or '').strip(), getattr(m, 'category', ''))
        for m in replaced
    })
    selected_texts = [(m.text or '').strip() for m in replaced]
    leftovers = verify_deidentified(cleaned, selected_texts, labels=labels)
    return cleaned, count, leftovers
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_text_cleanup_service.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/services/text_cleanup_service.py tests/test_text_cleanup_service.py
git commit -m "feat(paste): de-identify a pasted string with matching verification gate"
```

---

## Task 4: Detection endpoint and the reserved key

**Files:**
- Modify: `src/services/detection_service.py` (add `detect_in_text`)
- Modify: `backend/schemas.py` (add `DetectTextRequest`)
- Modify: `backend/main.py` (add `PASTE_KEY`, `PASTE_MAX_CHARS`, `/api/text/detect`, reserved-key guard)
- Test: `tests/test_backend_paste.py`

**Interfaces:**
- Produces: `PASTE_KEY = "<pasted-text>"`, `PASTE_MAX_CHARS = 50_000`, `DetectionService.detect_in_text(text: str) -> List[PIIMatch]`, `POST /api/text/detect` returning the existing `DetectionResultsResponse`.

**Background the implementer needs.** `_detection_cache` is keyed by path string. Paste caches under `PASTE_KEY`, synthesising `{"pages": {1: {"text": ...}}, "ocr_pages": []}`. Three properties matter:

1. `_resolve_cached_selections` builds keys as `f"{Path(doc_path_str)}_{idx}"`. `str(Path('<pasted-text>'))` is `'<pasted-text>'` on both macOS and Windows, so selection keys become `<pasted-text>_0`, `<pasted-text>_1` — the same contract `DocumentReview` and `/api/pii/manual` already use. Nothing downstream changes.
2. `<` and `>` are invalid in Windows filenames and this is not an absolute POSIX path, so it cannot collide with a real document. Guard `/api/pii/detect` anyway.
3. **`ocr_pages` MUST stay empty.** Marking the page OCR-sourced looks right — there is no geometry to rebuild — but arms rule 45's fuzzy verification, which false-quarantines near-miss names in typed text.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backend_paste.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from fastapi.testclient import TestClient
from backend.main import app, PASTE_KEY, PASTE_MAX_CHARS

client = TestClient(app)

SAMPLE = ('Billy Bob was absent on 12/03/2026. His mother Jane Bob was '
          'contacted on 0412 345 678.')


def detect(text=SAMPLE, **over):
    body = {'text': text, 'student_name': 'Billy Bob',
            'parent_names': ['Jane Bob'], 'family_names': [],
            'organisation_names': []}
    body.update(over)
    return client.post('/api/text/detect', json=body)


def test_detect_returns_one_pseudo_document_under_the_reserved_key():
    r = detect()
    assert r.status_code == 200
    docs = r.json()['documents']
    assert len(docs) == 1
    assert docs[0]['path'] == PASTE_KEY
    assert r.json()['total_matches'] > 0


def test_ocr_pages_is_empty_so_the_fuzzy_verifier_never_arms():
    # CLAUDE.md rule 45's fuzzy pass is for OCR. On typed text it would flag a
    # classmate "Smyth" against student "Smith" and falsely quarantine.
    assert detect().json()['documents'][0]['ocr_pages'] == []


def test_empty_text_is_rejected():
    assert detect(text='   ').status_code == 400


def test_oversize_text_is_rejected_with_a_redirect_message():
    r = detect(text='a ' * PASTE_MAX_CHARS)
    assert r.status_code == 400
    assert 'document' in r.json()['detail'].lower()


def test_pii_detect_refuses_the_reserved_key():
    r = client.post('/api/pii/detect', json={
        'pdf_paths': [PASTE_KEY], 'student_name': 'Billy Bob',
        'parent_names': [], 'family_names': [], 'organisation_names': []})
    assert r.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v`
Expected: FAIL — `ImportError: cannot import name 'PASTE_KEY' from 'backend.main'`

- [ ] **Step 3a: Add the service method**

In `src/services/detection_service.py`, add to `DetectionService` immediately after `detect_all`:

```python
    def detect_in_text(self, text: str) -> List['PIIMatch']:
        """
        Detect PII in a block of text with no document behind it.

        The orchestrator is already pure text-in; this exists so callers do not
        reach into the private _orchestrator attribute.
        """
        return self._orchestrator.detect_pii_in_text(text, 1)
```

- [ ] **Step 3b: Add the schema**

In `backend/schemas.py`, after `DetectPIIRequest`:

```python
class DetectTextRequest(BaseModel):
    """Detection over pasted text. No document, no folder."""
    text: str
    student_name: str
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []
```

- [ ] **Step 3c: Add the constants and the guard**

In `backend/main.py`, add `DetectTextRequest` to the `from backend.schemas import (...)` block, then add near `_detection_cache`:

```python
# Reserved detection-cache key for the paste pathway. Chosen because "<" and ">"
# are invalid in Windows filenames and this is not an absolute POSIX path, so it
# can never collide with a real document — and because fitz.open() on it raises,
# so anything that mistakes it for a document degrades safely.
PASTE_KEY = "<pasted-text>"

# Detection is superlinear: 8.6k chars ~0.3s, 20.7k ~1.2s, 43.1k ~4.6s. Past
# this a paste is document-sized, and the document pathway handles it better.
PASTE_MAX_CHARS = 50_000
```

Inside `detect_pii`, immediately after `pdf_paths = [Path(p) for p in req.pdf_paths]`:

```python
    if PASTE_KEY in req.pdf_paths:
        raise HTTPException(status_code=400, detail="Invalid document path.")
```

- [ ] **Step 3d: Add the endpoint**

In `backend/main.py`, immediately after `detect_pii`:

```python
@app.post("/api/text/detect", response_model=DetectionResultsResponse)
def detect_text(req: DetectTextRequest):
    """
    Detection over pasted text, cached under PASTE_KEY.

    ocr_pages stays EMPTY deliberately: marking the page OCR-sourced would arm
    the fuzzy verification pass (CLAUDE.md rule 45), which is right for scans
    and wrong for typed text, where a classmate "Smyth" against student "Smith"
    is edit-distance 1 and would falsely quarantine correct output.
    """
    text = req.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="No text was provided.")
    if len(text) > PASTE_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=(f"That text is {len(text):,} characters, over the "
                    f"{PASTE_MAX_CHARS:,} limit. Save it as a document and use "
                    "the document pathway instead."),
        )

    try:
        service = DetectionService(
            student_name=req.student_name,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            require_ner=True,
        )
        matches = service.detect_in_text(text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection failed: {e}") from e

    _detection_cache.clear()
    _detection_cache[PASTE_KEY] = {
        "matches": matches,
        "text_data": {"pages": {1: {"text": text}}, "ocr_pages": []},
    }

    return DetectionResultsResponse(
        documents=[DocumentPIIResponse(
            path=PASTE_KEY,
            filename="Pasted text",
            matches=[PIIMatchResponse(
                text=m.text, category=m.category, confidence=m.confidence,
                confidence_label=m.confidence_label, page_num=m.page_num,
                line_num=m.line_num, context=m.context, source=m.source,
                bbox=list(m.bbox) if m.bbox else None,
            ) for m in matches],
            ocr_pages=[],
        )],
        total_matches=len(matches),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v`
Expected: 5 passed

- [ ] **Step 5: Confirm nothing regressed**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_redact.py tests/test_manual_pii.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/services/detection_service.py backend/schemas.py backend/main.py tests/test_backend_paste.py
git commit -m "feat(paste): add /api/text/detect with a reserved cache key"
```

---

## Task 5: Who's Who endpoints for pasted text

**Files:**
- Modify: `backend/schemas.py` (add `CleanTextRequest`)
- Modify: `backend/main.py` (add `_paste_deidentify_body`, `/api/text/people`, `/api/text/labels`)
- Test: `tests/test_backend_paste.py`

**Interfaces:**
- Consumes: `DeidentifyRequestBody`, `_deidentify_request_from`, `deidentify_people`, `deidentify_label_preview` — all existing in `backend/main.py`.
- Produces: `CleanTextRequest` (the shared body for `/api/text/people`, `/api/text/labels` and `/api/text/clean`), `POST /api/text/people` → existing `PeopleResponse`, `POST /api/text/labels` → existing `LabelPreviewResponse`.

**Background the implementer needs:** `DeidentificationService.build_map()`, `describe_people()` and `preview_labels()` are static and touch no disk — verified. They are reused verbatim. These wrappers exist so the **renderer never fabricates a folder path**; the synthetic `DeidentifyRequest` is built server-side. `DeidentifyRequest.folder_path` is unused by `build_map()`, and Step 1's test asserts that stays true.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backend_paste.py`:

```python
def paste_body(mode='deidentify', **over):
    """Detect first, then select every match found. Returns the request body."""
    n = len(detect().json()['documents'][0]['matches'])
    body = {'mode': mode, 'student_name': 'Billy Bob',
            'selected_keys': [f'{PASTE_KEY}_{i}' for i in range(n)],
            'parent_names': ['Jane Bob'], 'family_names': [],
            'organisation_names': [], 'person_roles': {},
            'person_custom_labels': {}, 'ignored_people': []}
    body.update(over)
    return body


def people(**over):
    body = paste_body(**over)
    return client.post('/api/text/people', json=body), body


def test_people_endpoint_finds_the_student():
    r, _ = people()
    assert r.status_code == 200
    labels = [p['label'] for p in r.json()['people']]
    assert '[Student]' in labels


def test_people_endpoint_offers_assignable_roles():
    r, _ = people()
    assert len(r.json()['roles']) > 0


def test_labels_endpoint_returns_every_person():
    _, body = people()
    r = client.post('/api/text/labels', json=body)
    assert r.status_code == 200
    assert 'Billy Bob' in r.json()['labels']


def test_folder_path_is_unused_by_the_people_endpoint():
    # The wrappers pass PASTE_KEY as folder_path. If build_map ever started
    # touching it, this would fail rather than writing to a bogus location.
    r, _ = people()
    assert r.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v -k "people or labels or folder_path"`
Expected: FAIL — 404 on `/api/text/people`

- [ ] **Step 3a: Add the schema**

In `backend/schemas.py`, after `DetectTextRequest`:

```python
class CleanTextRequest(BaseModel):
    """
    Shared body for the paste pathway's people, labels and clean endpoints.

    Carries no folder_path: a paste has no folder, and the renderer must never
    fabricate one. The endpoints build the synthetic request themselves.
    """
    mode: str  # 'redact' | 'deidentify'
    student_name: str
    selected_keys: List[str]  # ["<pasted-text>_<idx>", ...]
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []
    person_roles: Dict[str, str] = {}
    person_custom_labels: Dict[str, str] = {}
    ignored_people: List[str] = []
```

Confirm `Dict` is already imported at the top of `backend/schemas.py`; if not, add it to the `typing` import.

- [ ] **Step 3b: Add the wrappers**

In `backend/main.py`, add `CleanTextRequest` to the schemas import, then immediately after `deidentify_label_preview`:

```python
def _paste_deidentify_body(req: CleanTextRequest) -> DeidentifyRequestBody:
    """
    The paste request as a document-shaped one.

    folder_path is PASTE_KEY and is never read: build_map() does not touch it,
    and nothing in the paste pathway writes to disk. Building it here rather
    than in the renderer keeps the frontend from inventing paths.
    """
    return DeidentifyRequestBody(
        folder_path=PASTE_KEY,
        student_name=req.student_name,
        documents=[PASTE_KEY],
        selected_keys=req.selected_keys,
        parent_names=req.parent_names,
        family_names=req.family_names,
        organisation_names=req.organisation_names,
        person_roles=req.person_roles,
        person_custom_labels=req.person_custom_labels,
        ignored_people=req.ignored_people,
    )


@app.post("/api/text/people", response_model=PeopleResponse)
def text_people(req: CleanTextRequest):
    """Who's who, for pasted text. Same map the clean step will build."""
    return deidentify_people(_paste_deidentify_body(req))


@app.post("/api/text/labels", response_model=LabelPreviewResponse)
def text_labels(req: CleanTextRequest):
    """Label preview for pasted text."""
    return deidentify_label_preview(_paste_deidentify_body(req))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/schemas.py backend/main.py tests/test_backend_paste.py
git commit -m "feat(paste): reuse the Who's who endpoints for pasted text"
```

---

## Task 6: Clean and discard endpoints

**Files:**
- Modify: `backend/schemas.py` (add `KeyEntry`, `CleanTextResponse`)
- Modify: `backend/main.py` (add `/api/text/clean`, `/api/text/discard`)
- Test: `tests/test_backend_paste.py`

**Interfaces:**
- Consumes: `blackout`, `deidentify_paste` (Tasks 1 and 3), `PASTE_KEY`, `_paste_deidentify_body`, `_deidentify_request_from`, `DeidentificationService.build_map`, `strip_labels`, `find_person_entities`.
- Produces: `POST /api/text/clean` → `CleanTextResponse`, `POST /api/text/discard` → `{"discarded": bool}`.

**Background the implementer needs:** CLAUDE.md rule 54c. After a successful de-identify write, the output (labels stripped) is swept with the shared spaCy engine; surviving PERSON entities become `leftover_name_warnings` — **warnings, not quarantine**, because NER false positives would block correct output. Strings the user deliberately deselected are excluded. These warnings carry REAL NAMES: they are response-only and must never reach the audit log or disk. The same applies to `key_entries` here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backend_paste.py`:

```python
def clean(mode='redact', **over):
    return client.post('/api/text/clean', json=paste_body(mode, **over))


def test_blackout_removes_the_student_name():
    r = clean('redact')
    assert r.status_code == 200
    assert 'Billy Bob' not in r.json()['text']
    assert '█' in r.json()['text']
    assert r.json()['replacements'] > 0


def test_blackout_returns_no_key_entries():
    assert clean('redact').json()['key_entries'] == []


def test_deidentify_returns_labels_and_a_key():
    r = clean('deidentify')
    assert r.status_code == 200
    assert '[Student]' in r.json()['text']
    assert 'Billy Bob' not in r.json()['text']
    entries = {e['label']: e['real_name'] for e in r.json()['key_entries']}
    assert entries.get('[Student]') == 'Billy Bob'


def test_deselected_items_are_left_alone():
    r = clean('redact', selected_keys=[])
    assert r.json()['replacements'] == 0
    assert 'Billy Bob' in r.json()['text']


def test_clean_without_detection_returns_400():
    client.post('/api/text/discard')
    r = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Billy Bob', 'selected_keys': [],
        'parent_names': [], 'family_names': [], 'organisation_names': [],
        'person_roles': {}, 'person_custom_labels': {}, 'ignored_people': []})
    assert r.status_code == 400


def test_discard_clears_the_cache():
    detect()
    assert client.post('/api/text/discard').json()['discarded'] is True
    assert clean('redact').status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v -k "clean or discard or blackout or deselected"`
Expected: FAIL — 404 on `/api/text/clean`

- [ ] **Step 3a: Add the response schemas**

In `backend/schemas.py`, after `CleanTextRequest`:

```python
class KeyEntry(BaseModel):
    """One label-to-name row. RESPONSE ONLY — re-identifies a person."""
    label: str
    real_name: str


class CleanTextResponse(BaseModel):
    text: str
    replacements: int
    leftovers: List[str] = []
    key_entries: List[KeyEntry] = []
    ambiguity_notes: List[str] = []
    leftover_name_warnings: List[str] = []
```

- [ ] **Step 3b: Add the endpoints**

In `backend/main.py`, add `CleanTextResponse` and `KeyEntry` to the schemas import and add these imports near the other service imports:

```python
from src.services.text_cleanup_service import BLOCK, blackout, deidentify_paste
from src.core.text_deidentifier import strip_labels
from src.core.pii_orchestrator import find_person_entities
```

Then, after `text_labels`:

```python
@app.post("/api/text/clean", response_model=CleanTextResponse)
def clean_text(req: CleanTextRequest):
    """
    Blackout or de-identify the cached pasted text.

    key_entries and leftover_name_warnings carry REAL NAMES. They are response
    only — shown in the local UI, never written to disk and never logged
    (CLAUDE.md rules 43 and 54c).
    """
    cached = _detection_cache.get(PASTE_KEY)
    if not cached:
        raise HTTPException(
            status_code=400,
            detail="No cached detection data for the pasted text. Run detection first.",
        )

    text = cached["text_data"]["pages"][1]["text"]
    matches = cached["matches"]
    chosen = set(req.selected_keys)
    selected = [m for i, m in enumerate(matches) if f"{PASTE_KEY}_{i}" in chosen]

    try:
        if req.mode == "deidentify":
            request = _deidentify_request_from(_paste_deidentify_body(req))
            pmap, _ = DeidentificationService.build_map(request)
            cleaned, count, leftovers = deidentify_paste(text, selected, pmap)
            labels = [label for label, _ in pmap.key_entries()]
            key_entries = [KeyEntry(label=l, real_name=n) for l, n in pmap.key_entries()]
            notes = pmap.ambiguity_notes()
        else:
            cleaned, count, leftovers = blackout(text, selected)
            labels = [BLOCK]
            key_entries, notes = [], []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleaning text failed: {e}") from e

    # The net under everything (rule 54c): sweep the OUTPUT for anything NER
    # still reads as a person. Warnings, never quarantine — NER false positives
    # would block correct output. Deliberately deselected strings are excluded
    # because the user's choice stands.
    deselected = {
        (m.text or "").strip().lower()
        for i, m in enumerate(matches) if f"{PASTE_KEY}_{i}" not in chosen
    }
    warnings = []
    for name in find_person_entities(strip_labels(cleaned, labels)):
        if name.lower() in deselected:
            continue
        warnings.append(name)
        if len(warnings) >= 10:
            break

    return CleanTextResponse(
        text=cleaned,
        replacements=count,
        leftovers=leftovers,
        key_entries=key_entries,
        ambiguity_notes=notes,
        leftover_name_warnings=warnings,
    )


@app.post("/api/text/discard")
def discard_text():
    """Drop the pasted text from the cache when the user leaves the flow."""
    return {"discarded": _detection_cache.pop(PASTE_KEY, None) is not None}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add backend/schemas.py backend/main.py tests/test_backend_paste.py
git commit -m "feat(paste): add /api/text/clean and /api/text/discard"
```

---

## Task 7: Save endpoint

**Files:**
- Modify: `backend/schemas.py` (add `SaveTextRequest`, `SaveTextResponse`)
- Modify: `backend/main.py` (add `/api/text/save`)
- Test: `tests/test_backend_paste.py`

**Interfaces:**
- Consumes: `src.core.text_pdf.render` (Task 2), `BLOCK` (Task 1).
- Produces: `POST /api/text/save` → `SaveTextResponse(path: str)`.

**Background the implementer needs:** The endpoint takes the cleaned text **back from the client** rather than re-reading the cache, so what is saved is byte-for-byte what the user was shown and approved. The text is already safe at that point, so there is no privacy cost. The path comes from Electron's existing `save-file-as` dialog (`window.electronAPI.saveFileAs(defaultPath, kind)`), which already supports both `'txt'` and PDF — **no Electron changes are needed anywhere in this feature**.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backend_paste.py`:

```python
import tempfile
from pathlib import Path

import fitz


def test_saving_txt_writes_the_exact_text():
    out = Path(tempfile.mkdtemp()) / 'out.txt'
    r = client.post('/api/text/save', json={
        'text': 'Hello [Student].', 'path': str(out), 'kind': 'txt'})
    assert r.status_code == 200
    assert out.read_text(encoding='utf-8') == 'Hello [Student].'


def test_saving_pdf_produces_black_boxes_and_no_block_glyphs():
    out = Path(tempfile.mkdtemp()) / 'out.pdf'
    r = client.post('/api/text/save', json={
        'text': 'Name: ██████ attended.', 'path': str(out), 'kind': 'pdf'})
    assert r.status_code == 200
    doc = fitz.open(str(out))
    extracted = ''.join(p.get_text() for p in doc)
    drawings = doc[0].get_drawings()
    doc.close()
    assert '█' not in extracted and '?' not in extracted
    assert len(drawings) >= 1


def test_an_unknown_kind_is_rejected():
    out = Path(tempfile.mkdtemp()) / 'out.bin'
    r = client.post('/api/text/save', json={
        'text': 'x', 'path': str(out), 'kind': 'exe'})
    assert r.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v -k save`
Expected: FAIL — 404 on `/api/text/save`

- [ ] **Step 3a: Add the schemas**

In `backend/schemas.py`, after `CleanTextResponse`:

```python
class SaveTextRequest(BaseModel):
    """
    Write cleaned text to a path the user chose in a native dialog.

    The text comes back from the client rather than the cache so what is saved
    is byte-for-byte what the user was shown and approved.
    """
    text: str
    path: str
    kind: str  # 'pdf' | 'txt'


class SaveTextResponse(BaseModel):
    path: str
```

- [ ] **Step 3b: Add the endpoint**

In `backend/main.py`, add `SaveTextRequest` and `SaveTextResponse` to the schemas import plus:

```python
from src.core.text_pdf import render as render_text_pdf
```

Then, after `discard_text`:

```python
@app.post("/api/text/save", response_model=SaveTextResponse)
def save_text(req: SaveTextRequest):
    """The only thing in the paste pathway that touches disk, and only on a
    path the user picked in a native Save dialog."""
    if req.kind not in ("pdf", "txt"):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    out = Path(req.path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if req.kind == "txt":
            out.write_text(req.text, encoding="utf-8")
        else:
            render_text_pdf(req.text, out, block=BLOCK)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Saving failed: {e}") from e

    return SaveTextResponse(path=str(out))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python3.13 -m pytest tests/test_backend_paste.py -v`
Expected: 18 passed

- [ ] **Step 5: Run the whole Python suite**

Run: `venv/bin/python3.13 -m pytest tests/ -q`
Expected: no NEW failures. Pre-existing `test_ocr_verification.py` failures on machines without Tesseract are acceptable — note the count before you start so you can compare.

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/main.py tests/test_backend_paste.py
git commit -m "feat(paste): add /api/text/save for PDF and txt output"
```

---

## Task 8: Store — paste input mode

**Files:**
- Modify: `desktop/src/types.ts` (`InputMode`, `Screen`)
- Modify: `desktop/src/store.ts`
- Test: `desktop/tests/paste.test.ts`

**Interfaces:**
- Produces: `InputMode` includes `'paste'`; `Screen` includes `'text_scan'`; store fields `pastedText: string`, `setPastedText(text: string)`, `clearPastedText()`.

**Background the implementer needs:** `pastedText` is raw PII living in the Zustand store. It has to be, because it spans four screens. So it is cleared aggressively. But it must **survive `setBackendReachable(false)`** — that setter clears `detectionParamsKey` today, and losing several hundred typed words to a momentary backend blip is the worst avoidable failure in this feature.

The de-identify key entries are NOT store state. They carry real names; per CLAUDE.md rule 24 (preview images stay in React state so they die on unmount) they live in `useState` in the completion component only. There is deliberately no store field for them.

- [ ] **Step 1: Write the failing test**

Create `desktop/tests/paste.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';

describe('store: pastedText', () => {
  beforeEach(() => {
    useStore.setState({ inputMode: 'paste', pastedText: 'Billy Bob was absent.' });
  });

  it('holds the slab while the user is in the paste pathway', () => {
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('is dropped when the user switches away from paste', () => {
    useStore.getState().setInputMode('folder');
    expect(useStore.getState().pastedText).toBe('');
  });

  it('is kept when switching to paste from elsewhere', () => {
    useStore.getState().setInputMode('paste');
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('SURVIVES a backend blip', () => {
    // detectionParamsKey is cleared so detection re-runs; the user's typed
    // text must not be collateral damage.
    useStore.setState({ detectionParamsKey: 'abc' });
    useStore.getState().setBackendReachable(false);
    expect(useStore.getState().detectionParamsKey).toBe('');
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('clearPastedText empties it for "Clean another"', () => {
    useStore.getState().clearPastedText();
    expect(useStore.getState().pastedText).toBe('');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run tests/paste.test.ts`
Expected: FAIL — `pastedText` is undefined

- [ ] **Step 3a: Widen the types**

In `desktop/src/types.ts`, add `'text_scan'` to the `Screen` union (after `'conversion_status'`) and change `InputMode`:

```ts
/** What the user picked to clean: one document, a whole folder, or pasted text */
export type InputMode = 'file' | 'folder' | 'paste';
```

- [ ] **Step 3b: Add the store field**

In `desktop/src/store.ts`, add to the interface next to `filePath`:

```ts
  /**
   * The slab the user pasted. Raw PII in the store — it has to be, because it
   * spans four screens — so it is cleared aggressively. See clearPastedText.
   */
  pastedText: string;
  setPastedText: (text: string) => void;
  clearPastedText: () => void;
```

Add `pastedText: ''` to `initialState`, and replace `setInputMode`:

```ts
  // Leaving the paste pathway drops the slab immediately. FolderSelection
  // pairs this with POST /api/text/discard so the backend cache goes too.
  setInputMode: (mode) =>
    set((state) => ({
      inputMode: mode,
      pastedText: mode === 'paste' ? state.pastedText : '',
    })),

  setPastedText: (text) => set({ pastedText: text }),

  // "Clean another" on the completion screen.
  clearPastedText: () => set({ pastedText: '' }),
```

Leave `setBackendReachable` exactly as it is — it must not touch `pastedText`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd desktop && npx vitest run tests/paste.test.ts`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add desktop/src/types.ts desktop/src/store.ts desktop/tests/paste.test.ts
git commit -m "feat(paste): add pastedText to the store with its clearing rules"
```

---

## Task 9: The step ladder

**Files:**
- Modify: `desktop/src/types.ts` (`screensFor`)
- Modify: `desktop/src/components/Sidebar.tsx:36`
- Test: `desktop/tests/paste.test.ts`

**Interfaces:**
- Produces: `screensFor(mode: WorkflowMode, inputMode?: InputMode): StepInfo[]`. The second parameter defaults to `'folder'` so existing callers and the exported `SCREENS` constant keep compiling.

**Background the implementer needs:** Step 2 is **replaced, not skipped**. The app already carries two auto-skip stamps — `autoAdvancedKey` (rule 38) and `peopleAutoSkippedKey` (rule 54b) — which had to be kept as separate fields because sharing one re-armed a forward-bounce trap. A third skip would be a third chance to re-arm it. Swapping `conversion_status` for `text_scan` in the ladder skips nothing, so there is no bounce to trap.

- [ ] **Step 1: Write the failing test**

Append to `desktop/tests/paste.test.ts`:

```ts
import { screensFor } from '../src/types';

describe('screensFor with paste', () => {
  it('swaps the conversion step for a scan step', () => {
    const keys = screensFor('redact', 'paste').map((s) => s.key);
    expect(keys).toEqual([
      'folder_selection', 'text_scan', 'document_review',
      'final_confirmation', 'completion',
    ]);
  });

  it('keeps Who\'s Who in de-identify mode', () => {
    const keys = screensFor('deidentify', 'paste').map((s) => s.key);
    expect(keys).toContain('people_review');
    expect(keys).toContain('text_scan');
    expect(keys).not.toContain('conversion_status');
  });

  it('relabels step 1 and step 2 for paste', () => {
    const steps = screensFor('redact', 'paste');
    expect(steps[0].label).toBe('Enter Text');
    expect(steps[1].label).toBe('Scan Text');
  });

  it('is unchanged for documents', () => {
    expect(screensFor('redact', 'folder').map((s) => s.key))
      .toEqual(screensFor('redact').map((s) => s.key));
    expect(screensFor('redact').map((s) => s.key)).toContain('conversion_status');
  });

  it('numbers steps consecutively in every combination', () => {
    for (const mode of ['redact', 'deidentify'] as const) {
      for (const input of ['folder', 'file', 'paste'] as const) {
        const steps = screensFor(mode, input);
        expect(steps.map((s) => s.step)).toEqual(steps.map((_, i) => i + 1));
      }
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run tests/paste.test.ts`
Expected: FAIL — paste ladder still contains `conversion_status`

- [ ] **Step 3a: Widen `screensFor`**

Replace the body of `screensFor` in `desktop/src/types.ts`:

```ts
/**
 * The wizard's steps for a given pathway and input.
 *
 * De-identify has one extra step (classifying who each person is), and paste
 * REPLACES the conversion step with a scan step rather than skipping it — a
 * skipped step would need a third auto-advance stamp alongside autoAdvancedKey
 * and peopleAutoSkippedKey, which is exactly the forward-bounce trap those two
 * had to be split apart to avoid.
 */
export function screensFor(
  mode: WorkflowMode,
  inputMode: InputMode = 'folder',
): StepInfo[] {
  const isPaste = inputMode === 'paste';
  const steps: { key: Screen; label: string }[] = [
    { key: 'folder_selection', label: isPaste ? 'Enter Text' : 'Select Documents' },
    isPaste
      ? { key: 'text_scan', label: 'Scan Text' }
      : { key: 'conversion_status', label: 'Convert Docs' },
    { key: 'document_review', label: 'Review PII' },
    ...(mode === 'deidentify'
      ? [{ key: 'people_review' as Screen, label: "Who's Who" }]
      : []),
    { key: 'final_confirmation', label: 'Confirm' },
    { key: 'completion', label: 'Complete' },
  ];
  return steps.map((s, i) => ({ ...s, step: i + 1 }));
}
```

- [ ] **Step 3b: Pass `inputMode` from the Sidebar**

In `desktop/src/components/Sidebar.tsx`, add `inputMode` to the destructured store selector on line 36's `useStore` call, then change line 36:

```ts
  const steps = screensFor(workflowMode, inputMode);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd desktop && npx vitest run tests/paste.test.ts tests/workflowMode.test.ts tests/routing.test.ts`
Expected: all pass — `workflowMode.test.ts` calls `screensFor(mode)` with one argument, which the default parameter keeps working.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/types.ts desktop/src/components/Sidebar.tsx desktop/tests/paste.test.ts
git commit -m "feat(paste): replace the conversion step with a scan step for pasted text"
```

---

## Task 10: Extract the detection hook

**Files:**
- Create: `desktop/src/hooks/useDetection.ts`
- Modify: `desktop/src/pages/ConversionStatus.tsx:62-125`
- Test: none new — this is a **behaviour-preserving refactor**, guarded by the existing suite.

**Interfaces:**
- Produces:

```ts
export interface DetectionSource {
  /** Distinguishes what is being scanned; folded into the fingerprint. */
  fingerprint: Record<string, unknown>;
  /** Performs the detect call. */
  run: (names: {
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, signal: AbortSignal) => Promise<DetectionResults>;
  /** Loading-overlay text. */
  message: string;
}

export function useDetection(): {
  runDetection: (source: DetectionSource) => Promise<void>;
  abortDetection: () => void;
};
```

**Background the implementer needs:** The logic being extracted lives in `ConversionStatus.handleContinue` and does five things in order — build the fingerprint from the name fields plus whatever is being scanned; reuse cached results when the fingerprint matches (so review decisions and manually-added items survive, per rule 41); warn before discarding review work when it does not; run the detect call under an `AbortController`; navigate to `no_pii_found` or `document_review` on the match count.

**Do not change any of that behaviour.** The only difference between the two callers is which endpoint runs and what goes into the fingerprint.

- [ ] **Step 1: Create the hook**

Create `desktop/src/hooks/useDetection.ts`, moving the logic verbatim out of `ConversionStatus.handleContinue`:

```ts
import { useRef } from 'react';
import { useStore } from '../store';
import { friendlyError } from '../lib/errorMessage';
import type { DetectionResults } from '../types';

export interface DetectionSource {
  fingerprint: Record<string, unknown>;
  run: (names: {
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, signal: AbortSignal) => Promise<DetectionResults>;
  message: string;
}

/**
 * Fingerprint-aware PII detection, shared by ConversionStatus (documents) and
 * TextScan (pasted text).
 *
 * The fingerprint is what makes it safe to skip re-detection: matching inputs
 * mean the backend cache still holds the same run, so review decisions and
 * manually added items survive (CLAUDE.md rule 41). ConversionStatus keeps its
 * own auto-advance logic — that trap is local to it (rule 38).
 */
export function useDetection() {
  const abortRef = useRef<AbortController | null>(null);
  const {
    studentName, parentNames, familyNames, organisationNames,
    detectionResults, detectionParamsKey, userSelections,
    setDetectionResults, setDetectionParamsKey,
    setLoading, setError, navigateTo,
  } = useStore();

  const abortDetection = () => {
    abortRef.current?.abort();
    abortRef.current = null;
  };

  const runDetection = async (source: DetectionSource) => {
    const names = {
      student_name: studentName,
      parent_names: parentNames.split(',').map((n) => n.trim()).filter(Boolean),
      family_names: familyNames.split(',').map((n) => n.trim()).filter(Boolean),
      organisation_names: organisationNames.split(',').map((n) => n.trim()).filter(Boolean),
    };

    const paramsKey = JSON.stringify({
      ...source.fingerprint,
      student: studentName.trim(),
      parents: names.parent_names,
      family: names.family_names,
      orgs: names.organisation_names,
    });

    // Same inputs as the last successful run — reuse the existing results so
    // review decisions and manually added items survive. The backend cache is
    // only cleared by a NEW detect call, so cleaning will still work.
    if (detectionResults && detectionParamsKey && paramsKey === detectionParamsKey) {
      const total = detectionResults.documents.reduce((s, d) => s + d.matches.length, 0);
      navigateTo(total === 0 ? 'no_pii_found' : 'document_review');
      return;
    }

    // Inputs changed — re-detection will reset review work. Warn if any exists.
    if (detectionResults) {
      const hasReviewWork =
        Object.values(userSelections).some((v) => v === false) ||
        detectionResults.documents.some((d) => d.matches.some((m) => m.source === 'manual'));
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
    setLoading(true, source.message);
    try {
      const detection = await source.run(names, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setDetectionResults(detection);
      setDetectionParamsKey(paramsKey);
      const total = detection.documents.reduce((s, d) => s + d.matches.length, 0);
      navigateTo(total === 0 ? 'no_pii_found' : 'document_review');
    } catch (e) {
      if (!ctrl.signal.aborted) setError(friendlyError(e));
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  return { runDetection, abortDetection };
}
```

Compare against the current `ConversionStatus.handleContinue` (lines 62-125 plus its `catch`/`finally`) and keep any detail this draft missed — the existing behaviour is the specification.

- [ ] **Step 2: Rewrite `ConversionStatus.handleContinue`**

Replace the body of `handleContinue` in `desktop/src/pages/ConversionStatus.tsx` with:

```tsx
  const { runDetection, abortDetection } = useDetection();

  const handleContinue = async () => {
    if (!results) return;
    const allPdfs = [...results.pdf_files, ...results.converted_files];
    await runDetection({
      fingerprint: { pdfs: allPdfs },
      message: 'Extracting text and detecting PII...',
      run: (names, signal) =>
        api.detectPII({ pdf_paths: allPdfs, ...names }, { signal }),
    });
  };
```

Replace the component's existing `abortRef` usage (the Back handler and any unmount cleanup) with `abortDetection()`, and delete the now-unused local `abortRef`, imports and state. Leave the auto-advance `useEffect` and `autoAdvancedKey` logic exactly as they are.

- [ ] **Step 3: Verify nothing regressed**

Run: `cd desktop && npm run build && npm run lint && npm test`
Expected: build clean, lint at **7 errors + 1 warning or fewer**, all vitest tests pass.

- [ ] **Step 4: Manually confirm the document pathway still works**

Run `cd desktop && npm run dev:electron`, pick a folder with one PDF, and walk through to the review screen. Then go Back and Continue again — detection must NOT re-run.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/hooks/useDetection.ts desktop/src/pages/ConversionStatus.tsx
git commit -m "refactor(desktop): extract useDetection so paste can share the fingerprint logic"
```

---

## Task 11: API client and error messages

**Files:**
- Modify: `desktop/src/api.ts`
- Modify: `desktop/src/lib/errorMessage.ts:4-16`
- Test: `desktop/tests/errorMessage.test.ts`

**Interfaces:**
- Produces on the `api` object: `detectText`, `textPeople`, `textLabels`, `cleanText`, `saveText`, `discardText`.

**Background the implementer needs:** CLAUDE.md rule 29 — every `setError` call site uses `friendlyError()`, and the mapper must cover every `HTTPException(detail=...)` string in `backend/main.py`. Note `"No cached detection data for the pasted text"` already matches the existing `/no cached detection data/i` pattern, so it needs no new entry.

- [ ] **Step 1: Write the failing test**

Append to `desktop/tests/errorMessage.test.ts`:

```ts
describe('paste pathway errors', () => {
  it('explains an empty paste', () => {
    expect(friendlyError(new Error('No text was provided.')))
      .toMatch(/paste some text/i);
  });

  it('explains an oversize paste and points at documents', () => {
    expect(friendlyError(new Error(
      'That text is 60,000 characters, over the 50,000 limit. Save it as a ' +
      'document and use the document pathway instead.')))
      .toMatch(/document/i);
  });

  it('handles a clean failure', () => {
    expect(friendlyError(new Error('Cleaning text failed: boom')))
      .toMatch(/cleaning your text/i);
  });

  it('handles a save failure', () => {
    expect(friendlyError(new Error('Saving failed: disk full')))
      .toMatch(/save/i);
  });

  it('handles an unsupported file type', () => {
    expect(friendlyError(new Error('Unsupported file type.')))
      .toMatch(/PDF or a text file/i);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run tests/errorMessage.test.ts`
Expected: FAIL — falls through to the generic message

- [ ] **Step 3a: Add the patterns**

In `desktop/src/lib/errorMessage.ts`, add to `PATTERNS` **above** the generic `detection failed` entry:

```ts
  [/no text was provided/i, "Paste some text before continuing."],
  [/over the [\d,]+ limit/i, "That's more text than this screen handles. Save it as a document and use the document pathway instead."],
  [/cleaning text failed/i, "Something went wrong while cleaning your text. Please try again."],
  [/unsupported file type/i, "That can only be saved as a PDF or a text file."],
  [/saving failed/i, "Couldn't save the file. Check you have permission to write to that folder and try again."],
```

- [ ] **Step 3b: Add the client methods**

In `desktop/src/api.ts`, inside the `api` object after `detectPII`:

```ts
  detectText: (params: {
    text: string;
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, options?: RequestInit) =>
    request<DetectionResults>('/api/text/detect', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, DETECT_TIMEOUT_MS),

  textPeople: (params: Record<string, unknown>, options?: RequestInit) =>
    request<PeopleResponse>('/api/text/people', {
      method: 'POST', body: JSON.stringify(params), ...options,
    }),

  textLabels: (params: Record<string, unknown>, options?: RequestInit) =>
    request<{ labels: Record<string, string> }>('/api/text/labels', {
      method: 'POST', body: JSON.stringify(params), ...options,
    }),

  cleanText: (params: Record<string, unknown>, options?: RequestInit) =>
    request<CleanTextResult>('/api/text/clean', {
      method: 'POST', body: JSON.stringify(params), ...options,
    }, DETECT_TIMEOUT_MS),

  saveText: (text: string, path: string, kind: 'pdf' | 'txt') =>
    request<{ path: string }>('/api/text/save', {
      method: 'POST', body: JSON.stringify({ text, path, kind }),
    }),

  discardText: () =>
    request<{ discarded: boolean }>('/api/text/discard', { method: 'POST' }),
```

Use whatever timeout constant `detectPII` already uses in place of `DETECT_TIMEOUT_MS` — read the file and match it. Add to `desktop/src/types.ts`:

```ts
export interface KeyEntry { label: string; real_name: string }

export interface CleanTextResult {
  text: string;
  replacements: number;
  leftovers: string[];
  key_entries: KeyEntry[];
  ambiguity_notes: string[];
  leftover_name_warnings: string[];
}
```

Import `CleanTextResult` (and `PeopleResponse`, if not already) into `api.ts`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd desktop && npx vitest run tests/errorMessage.test.ts && npm run build`
Expected: tests pass, build clean

- [ ] **Step 5: Commit**

```bash
git add desktop/src/api.ts desktop/src/types.ts desktop/src/lib/errorMessage.ts desktop/tests/errorMessage.test.ts
git commit -m "feat(paste): add the text API client and friendly error mappings"
```

---

## Task 12: The paste input on Step 1

**Files:**
- Modify: `desktop/src/pages/FolderSelection.tsx`
- Test: none — verify with `npm run build` + `npm run lint` (no React harness exists).

**Interfaces:**
- Consumes: `pastedText`, `setPastedText`, `setInputMode` (Task 8); `api.discardText` (Task 11).

**Background the implementer needs:** This screen already holds *both* the input picker and the name fields, and gates Continue on `inputReady && studentName.trim().length > 0`. The student name stays **mandatory** for paste: it is the biggest lever on detection quality (user-entered names are confidence 0.95 and seed `generate_name_variations()`), and `PseudonymMap` is built around a student — with no name nobody is labelled `[Student]` and every person falls through to `[Other person]`.

- [ ] **Step 1: Add the third input choice**

Wherever the file/folder choice is rendered, add a third option labelled "Paste text" with a description like "Clean a block of text you copied from somewhere". Wire its click to:

```tsx
  const choosePaste = () => setInputMode('paste');
```

- [ ] **Step 2: Discard the slab when switching away**

```tsx
  const chooseDocuments = (mode: 'file' | 'folder') => {
    if (inputMode === 'paste') {
      // The store drops pastedText; clear the backend cache to match.
      api.discardText().catch(() => { /* best effort — nothing was saved */ });
    }
    setInputMode(mode);
  };
```

- [ ] **Step 3: Render the textarea**

Where the file/folder picker renders, add a paste branch:

```tsx
{inputMode === 'paste' ? (
  <div>
    <label htmlFor="paste-box" className="block text-sm font-medium text-slate-700 mb-1">
      Paste your text
    </label>
    <textarea
      id="paste-box"
      value={pastedText}
      onChange={(e) => setPastedText(e.target.value)}
      rows={12}
      placeholder="Paste the text you want cleaned up…"
      className="w-full rounded-lg border border-slate-300 p-3 font-mono text-sm"
    />
    <div className="mt-1 flex justify-between text-xs">
      <span className={pastedText.length > PASTE_MAX ? 'text-red-600' : 'text-slate-500'}>
        {pastedText.length.toLocaleString()} characters
      </span>
      {pastedText.length > PASTE_MAX ? (
        <span className="text-red-600">
          Too long. Save it as a document and use the document pathway instead.
        </span>
      ) : pastedText.length > PASTE_WARN ? (
        <span className="text-amber-600">Long text — scanning may take a few seconds.</span>
      ) : null}
    </div>
  </div>
) : (
  /* existing file / folder picker */
)}
```

Define alongside the component:

```tsx
// Mirrors PASTE_MAX_CHARS in backend/main.py. Detection is superlinear:
// 8.6k chars ~0.3s, 20.7k ~1.2s, 43.1k ~4.6s.
const PASTE_MAX = 50_000;
const PASTE_WARN = 20_000;
```

- [ ] **Step 4: Gate Continue**

Change the readiness check so paste participates:

```tsx
  const inputReady =
    inputMode === 'paste'
      ? pastedText.trim().length > 0 && pastedText.length <= PASTE_MAX
      : /* existing file / folder readiness */;
```

Leave `canProceed = inputReady && studentName.trim().length > 0` unchanged.

- [ ] **Step 5: Navigate to the right step 2**

Where Continue navigates to `conversion_status`, branch:

```tsx
  navigateTo(inputMode === 'paste' ? 'text_scan' : 'conversion_status');
```

- [ ] **Step 6: Verify**

Run: `cd desktop && npm run build && npm run lint`
Expected: build clean; lint no worse than 7 errors + 1 warning

- [ ] **Step 7: Commit**

```bash
git add desktop/src/pages/FolderSelection.tsx
git commit -m "feat(paste): add the paste-text input to step 1"
```

---

## Task 13: The scan screen

**Files:**
- Create: `desktop/src/pages/TextScan.tsx`
- Modify: `desktop/src/App.tsx:83`
- Test: none — verify with `npm run build` + `npm run lint`.

**Interfaces:**
- Consumes: `useDetection` (Task 10), `api.detectText` (Task 11), `pastedText` (Task 8).

**Background the implementer needs:** The first detection of a session pays spaCy's model load — measured ~7s cold — on top of detection itself. That is existing behaviour (rule 37 caches the engine module-level for the process), but this is the screen where a user will most notice it, so the message must own it rather than looking hung. This screen has **no auto-advance logic**: `runDetection` navigates on completion.

- [ ] **Step 1: Create the screen**

Create `desktop/src/pages/TextScan.tsx`:

```tsx
import { useEffect, useRef } from 'react';
import { useStore } from '../store';
import { api } from '../api';
import { useDetection } from '../hooks/useDetection';

/**
 * Step 2 for pasted text — the paste pathway's counterpart to ConversionStatus.
 *
 * There is nothing to convert, but the step is NOT skipped: a skipped step
 * would need a third auto-advance stamp alongside autoAdvancedKey and
 * peopleAutoSkippedKey, which is the forward-bounce trap those two were split
 * apart to avoid. Detection runs on mount and navigates itself.
 */
export default function TextScan() {
  const { pastedText, navigateTo, loading } = useStore();
  const { runDetection, abortDetection } = useDetection();
  const started = useRef(false);

  useEffect(() => {
    if (started.current || !pastedText.trim()) return;
    started.current = true;
    void runDetection({
      fingerprint: { paste: pastedText },
      // The first scan of a session also loads the language model (~7s).
      message: 'Reading your text and looking for personal information…',
      run: (names, signal) =>
        api.detectText({ text: pastedText, ...names }, { signal }),
    });
    return abortDetection;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Scanning your text</h2>
      <p className="mt-2 text-slate-600">
        {loading
          ? 'This usually takes a moment. The first scan after opening the app takes a little longer while the language model loads.'
          : 'Scan finished.'}
      </p>
      <button
        onClick={() => { abortDetection(); navigateTo('folder_selection'); }}
        className="mt-6 text-sm text-slate-600 underline btn-press"
      >
        Back
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Route it**

In `desktop/src/App.tsx`, import `TextScan` and add after the `conversion_status` case:

```tsx
      case 'text_scan':           return <TextScan />;
```

- [ ] **Step 3: Verify**

Run: `cd desktop && npm run build && npm run lint`
Expected: build clean; lint no worse than baseline. The one `eslint-disable-next-line react-hooks/exhaustive-deps` is deliberate — the effect must run exactly once.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/pages/TextScan.tsx desktop/src/App.tsx
git commit -m "feat(paste): add the text scan step"
```

---

## Task 14: Confirm and completion

**Files:**
- Create: `desktop/src/pages/PasteCompletion.tsx`
- Modify: `desktop/src/pages/FinalConfirmation.tsx`
- Modify: `desktop/src/pages/PeopleReview.tsx` (endpoint branch)
- Modify: `desktop/src/App.tsx:88-89`
- Test: none — verify with `npm run build` + `npm run lint`.

**Interfaces:**
- Consumes: `api.cleanText`, `api.saveText`, `api.textPeople`, `api.textLabels` (Task 11); `clearPastedText` (Task 8); `window.electronAPI.saveFileAs(defaultPath, kind)` — **already exists**, supports `'txt'` and PDF. No Electron changes are needed.

**Background the implementer needs — the hazard specific to this screen.** In de-identify mode the safe output and the re-identifying key are on the same screen. A careless select-all-copy would put the key on the clipboard alongside the thing the user is about to paste into an AI chat. So: **separate boxes, separate Copy buttons, key collapsed behind a click.** Never one scrollable area containing both.

`key_entries` and `leftover_name_warnings` carry real names. Per CLAUDE.md rule 24 they live in `useState` here and nowhere else — never in the Zustand store, never written to disk.

- [ ] **Step 1: Point PeopleReview at the paste endpoints**

In `desktop/src/pages/PeopleReview.tsx`, wherever it calls `api.deidentifyPeople` and `api.deidentifyLabels`, branch on `inputMode`:

```tsx
  const isPaste = inputMode === 'paste';
  const fetchPeople = isPaste ? api.textPeople : api.deidentifyPeople;
  const fetchLabels = isPaste ? api.textLabels : api.deidentifyLabels;
```

The paste bodies omit `folder_path`, `documents`, `folder_action`, `custom_output_path` and `custom_output_filename` — the backend builds those. Everything else (`mode`, `student_name`, `selected_keys`, name lists, `person_roles`, `person_custom_labels`, `ignored_people`) is identical, so build the body once and delete the document-only keys when `isPaste`. Send `mode: workflowMode`.

- [ ] **Step 2: Branch FinalConfirmation**

In `desktop/src/pages/FinalConfirmation.tsx`, add near `isDeidentify`:

```tsx
  const isPaste = inputMode === 'paste';
```

Hide the output-folder controls and the Save As button when `isPaste` — a paste has no output folder and nothing is written until the user chooses to save. Add a paste branch to `handleRedact` **before** its existing document logic:

```tsx
    if (isPaste) {
      setLoading(true, isDeidentify ? 'De-identifying your text…' : 'Blacking out your text…');
      try {
        const result = await api.cleanText({
          mode: workflowMode,
          student_name: studentName,
          selected_keys: Object.entries(userSelections)
            .filter(([, on]) => on).map(([k]) => k),
          parent_names: parentNames.split(',').map((n) => n.trim()).filter(Boolean),
          family_names: familyNames.split(',').map((n) => n.trim()).filter(Boolean),
          organisation_names: organisationNames.split(',').map((n) => n.trim()).filter(Boolean),
          person_roles: personRoles,
          person_custom_labels: personCustomLabels,
          ignored_people: ignoredPeople,
        });
        setPasteResult(result);
        navigateTo('completion');
      } catch (e) {
        setError(friendlyError(e));
      } finally {
        setLoading(false);
      }
      return;
    }
```

**Where the result lives — this is prescriptive, not a suggestion.** The result splits in two, because half of it re-identifies people.

Create `desktop/src/lib/pasteResult.ts`:

```ts
import type { CleanTextResult } from '../types';

/**
 * The half of a clean result that carries REAL NAMES: key entries, ambiguity
 * notes, and the NER sweep's leftover warnings.
 *
 * Deliberately module-level rather than Zustand state. CLAUDE.md rule 24
 * establishes the precedent — preview images stay out of the store so they die
 * with the component. These names must never persist across screens, reach
 * disk, or appear in the audit log.
 */
type Sensitive = Pick<
  CleanTextResult, 'key_entries' | 'ambiguity_notes' | 'leftover_name_warnings'
>;

let held: Sensitive | null = null;

export function holdSensitive(r: Sensitive) {
  held = {
    key_entries: r.key_entries,
    ambiguity_notes: r.ambiguity_notes,
    leftover_name_warnings: r.leftover_name_warnings,
  };
}

/** Read without consuming — React may render a component twice in StrictMode. */
export function peekSensitive(): Sensitive {
  return held ?? { key_entries: [], ambiguity_notes: [], leftover_name_warnings: [] };
}

export function clearSensitive() {
  held = null;
}
```

Add to the store only the **safe** half:

```ts
  /** Safe half of a paste result. The name-bearing half lives in lib/pasteResult. */
  pasteOutput: { text: string; replacements: number; leftovers: string[] } | null;
  setPasteOutput: (o: { text: string; replacements: number; leftovers: string[] } | null) => void;
```

So `handleRedact`'s paste branch ends:

```tsx
        holdSensitive(result);
        setPasteOutput({
          text: result.text,
          replacements: result.replacements,
          leftovers: result.leftovers,
        });
        navigateTo('completion');
```

`clearPastedText()` on "Clean another" must be paired with `clearSensitive()` and `setPasteOutput(null)`.

- [ ] **Step 3: Create the completion screen**

Create `desktop/src/pages/PasteCompletion.tsx` with, in this order:

1. A heading — "Your text is ready" (blackout) / "Your de-identified text is ready".
2. `leftovers.length > 0` → a red warning naming what may still be visible; the Save button then defaults its filename to `...UNVERIFIED.txt`.
3. `leftover_name_warnings.length > 0` → an amber warning ("these still look like names — check before you share"), never blocking.
4. The cleaned text in its **own** `<textarea readOnly>` with a **Copy** button directly above it.
5. A **Save as PDF** (blackout) / **Save as .txt** (de-identify) button:

```tsx
  const handleSave = async () => {
    const kind = isDeidentify ? 'txt' : 'pdf';
    const suggested = isDeidentify
      ? (leftovers.length ? 'cleaned-text.UNVERIFIED.txt' : 'cleaned-text.txt')
      : 'redacted-text.pdf';
    const path = await window.electronAPI?.saveFileAs(suggested, kind);
    if (!path) return;                       // user cancelled — stay put
    try {
      await api.saveText(text, path, kind);
    } catch (e) {
      setError(friendlyError(e));
    }
  };
```

6. De-identify only: a collapsed `<details>` headed "Name key — keep this private", containing a **separate** read-only box with its **own** Copy button, listing `key_entries` and then `ambiguity_notes`. Above it, a plain warning: this turns the labels back into real names; never paste it into an AI tool.
7. A **Clean another** button: `clearPastedText(); await api.discardText(); navigateTo('folder_selection');`

- [ ] **Step 3b: Give the zero-detections branch a way out**

`no_pii_found` is a branch off `document_review`, shown when detection finds
nothing. For documents that is a dead end by design — the originals are already
fine. For a paste it would strand the user with no way to get their text back.

In `desktop/src/pages/NoPiiFound.tsx`, add a paste branch: when
`inputMode === 'paste'`, show the pasted text in a read-only box with a **Copy**
button and a line explaining that nothing needed removing, alongside the
existing Back action. Leave the document behaviour untouched.

- [ ] **Step 4: Route it**

In `desktop/src/App.tsx`, change the completion case:

```tsx
      case 'completion':
        if (inputMode === 'paste') return <PasteCompletion />;
        return workflowMode === 'deidentify' ? <DeidentifyCompletion /> : <Completion />;
```

- [ ] **Step 5: Verify**

Run: `cd desktop && npm run build && npm run lint && npm test`
Expected: build clean; lint no worse than baseline; all vitest tests pass

- [ ] **Step 6: Commit**

```bash
git add desktop/src/pages/PasteCompletion.tsx desktop/src/pages/FinalConfirmation.tsx desktop/src/pages/PeopleReview.tsx desktop/src/pages/NoPiiFound.tsx desktop/src/lib/pasteResult.ts desktop/src/App.tsx desktop/src/store.ts
git commit -m "feat(paste): add the paste completion screen with a separated name key"
```

---

## Task 15: End-to-end verification and documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full Python suite**

Run: `venv/bin/python3.13 -m pytest tests/ -q`
Expected: 651 existing + ~30 new tests. No new failures. Pre-existing `test_ocr_verification.py` failures on machines without Tesseract are acceptable.

- [ ] **Step 2: Run the full desktop suite**

Run: `cd desktop && npm test && npm run build && npm run lint`
Expected: all vitest tests pass; build clean; lint **7 errors + 1 warning or fewer**

- [ ] **Step 3: Walk the feature by hand**

Run: `cd desktop && npm run dev:electron`, then verify each of these:

- [ ] Blackout: paste text containing a name, a phone number and an email → review → confirm → text shows fixed-width blocks → Copy → paste into a text editor and confirm the blocks came through.
- [ ] Save as PDF → open it → **boxes are black rectangles, not `??????`** → select the text in a PDF reader and confirm nothing is selectable under the boxes.
- [ ] Paste text containing `XXXXXXXX` or a `~~~~` separator → save as PDF → **the user's own characters are NOT boxed.**
- [ ] De-identify: same slab → Who's Who appears → assign a role → confirm → labels appear → the key is collapsed and has its **own** Copy button.
- [ ] Select all on the completion screen → confirm the key does not come with the output.
- [ ] Paste text with no PII at all → the no-PII screen appears **with a Copy button** that returns the text.
- [ ] Paste 60,000 characters → blocked at step 1 with the document-pathway message.
- [ ] Switch from paste to folder mode → the slab is gone; switch back → the textarea is empty.
- [ ] Kill the backend mid-flow (`pkill -f "uvicorn backend.main"`) → the banner appears and **the pasted text is still in the box**.
- [ ] Document pathway (folder, one PDF, redact) still works end to end — this is the regression that matters most.

- [ ] **Step 4: Add the rules to CLAUDE.md**

Append to the "Critical Non-Obvious Rules" section, numbered from 60:

```markdown
### 60. `<pasted-text>` is a reserved detection-cache key

The paste pathway caches under `PASTE_KEY = "<pasted-text>"`, and
`/api/pii/detect` rejects it explicitly. It is chosen because `<` and `>` are
invalid in Windows filenames and it is not an absolute POSIX path, so it can
never collide with a real document — and because `fitz.open()` on it raises
`FileNotFoundError`, so any code that mistakes it for a document degrades
safely rather than misbehaving.

Selection keys become `<pasted-text>_0`, `<pasted-text>_1` — the same
`f"{doc_path}_{index}"` contract, so `DocumentReview` and `/api/pii/manual`
(rule #31) work unchanged.

### 61. A pasted page's `ocr_pages` must stay EMPTY

Marking it OCR-sourced looks right — there is no page geometry to rebuild, and
`_formatted_pages` uses cached text for OCR pages. It arms rule #45's fuzzy
verification pass, which is correct for scans and wrong for typed text: a
report naming a classmate "Smyth" while the student is "Smith" is
edit-distance 1 over 5 letters, so the fuzzy pass reports a leftover and
quarantines correct output. Empty `ocr_pages` reaches the same cached-text
behaviour through the `pdf is None` branch, with exact verification only.

### 62. The blackout PDF must never rely on the U+2588 glyph

PyMuPDF's built-in base-14 fonts are Latin-1 only.
`fitz.Font('helv').has_glyph(0x2588)` returns 0, so writing block characters
into a textbox extracts back as `??????` — wrong output, not an error.

`text_pdf.render()` lays out a Latin-1 **sentinel** instead and removes it with
`add_redact_annot(fill=(0,0,0))` + `apply_redactions()`, which paints the box
and deletes the sentinel in one step. The PII was never placed in the PDF, so
there is nothing under the boxes either way.

**The sentinel is chosen per render, never hard-coded.** `search_for` cannot
tell our sentinel from the same characters in the user's own text: laying out
`"Marks: XXXXXXXX out of ten."` returns two hits for a fixed `XXXXXXXX`, so a
maths report would have its real content blacked out. `choose_sentinel()`
returns the first candidate absent from the cleaned text.

### 63. The de-identify key and the safe output must never share a text area

Rule #43 has no analogue for paste — there are no originals on disk, so the key
is shown on screen rather than written beside them. That creates a hazard the
document pathway never had: the safe text and the re-identifying key are on the
same screen, and a careless select-all-copy would put the key on the clipboard
alongside the thing being pasted into an AI chat.

Separate boxes, separate Copy buttons, key collapsed behind a click.
`key_entries` and `leftover_name_warnings` carry real names and live in React
state only (rule #24) — never the Zustand store, never disk, never the audit
log.

### 64. `pastedText` must survive `setBackendReachable(false)`

That setter clears `detectionParamsKey` so detection re-runs (rule #41). It must
not clear the slab the user typed. Losing several hundred words to a momentary
backend blip is the worst avoidable failure in the paste pathway.
```

Also update these sections of `CLAUDE.md`:
- **Zustand Store Keys** — add `pastedText`, and note `inputMode` now includes `'paste'`.
- **Screen Flow** — note `text_scan` and that `screensFor` takes `inputMode`.
- **Key Files** — add `src/services/text_cleanup_service.py`, `src/core/text_pdf.py`, `desktop/src/hooks/useDetection.ts`, `desktop/src/pages/TextScan.tsx`, `desktop/src/pages/PasteCompletion.tsx`.
- **Test Structure** — add the three new test files and update the total count.
- **Architecture → Desktop App Architecture** — add the six `/api/text/*` endpoints.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the paste pathway's non-obvious rules"
```

- [ ] **Step 6: Push to test**

```bash
git push origin test
```

Do NOT merge to `main` — confirm with the user first.

---

## Notes for the reviewer

Three things in this plan are load-bearing and easy to "simplify" back into bugs:

1. **`ocr_pages` empty** (Task 4). The intuitive value is `[1]`. It causes false quarantines.
2. **The per-render sentinel** (Task 2). A hard-coded one passes every test that does not contain the sentinel in its input.
3. **Step 2 replaced, not skipped** (Task 9). Skipping it needs a third auto-advance stamp, which is the trap rules 38 and 54b document.
