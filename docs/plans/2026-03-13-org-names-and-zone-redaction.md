# Organisation Names, User Guidance & Header/Footer Zone Redaction

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add organisation name detection as a new PII category, add header/footer zone blanking, and add user guidance text explaining why providing names improves accuracy.

**Architecture:** Organisation names flow through the same pipeline as parent/family names — stored as a comma-separated string in session state, split into a list, passed through DetectionService → PIIOrchestrator → PIIDetector. Each org name also generates word-level variations (3+ chars). Header/footer zone redaction is a new Stage 0 in `redact_pdf()` that runs before all other stages, blanking the top 12% and bottom 8% of every page. User guidance is an `st.info()` block on the folder selection screen.

**Tech Stack:** Python, Streamlit, PyMuPDF (fitz), PIL, pytesseract, pytest

---

## Task 1: Add `organisation_names` to Session State

**Files:**
- Modify: `src/core/session_state.py:23` (after `family_names` init)

**Step 1: Write the failing test**

Create file `tests/test_session_state.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import unittest
from unittest.mock import patch, MagicMock


class TestSessionStateInit:
    """Verify session state initialises organisation_names and redact_header_footer."""

    @patch('streamlit.session_state', new_callable=dict)
    @patch('streamlit.rerun')
    def test_organisation_names_initialised(self, mock_rerun, mock_state):
        # Re-import after patching
        import importlib
        import session_state as ss
        importlib.reload(ss)

        ss.init_session_state()
        assert mock_state.get('organisation_names') == ''

    @patch('streamlit.session_state', new_callable=dict)
    @patch('streamlit.rerun')
    def test_redact_header_footer_initialised(self, mock_rerun, mock_state):
        import importlib
        import session_state as ss
        importlib.reload(ss)

        ss.init_session_state()
        assert mock_state.get('redact_header_footer') is True
```

**Step 2: Run test to verify it fails**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && source venv/bin/activate && pytest tests/test_session_state.py -v`
Expected: FAIL — keys not found in session state

**Step 3: Add the two new keys to `init_session_state()`**

In `src/core/session_state.py`, after line 23 (`family_names`), add:

```python
    if 'organisation_names' not in st.session_state:
        st.session_state.organisation_names = ''
    if 'redact_header_footer' not in st.session_state:
        st.session_state.redact_header_footer = True
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/session_state.py tests/test_session_state.py
git commit -m "feat: add organisation_names and redact_header_footer to session state"
```

---

## Task 2: Add `organisation_names` to PIIDetector

**Files:**
- Modify: `src/core/pii_detector.py:123` (constructor signature)
- Modify: `src/core/pii_detector.py:356` (`_detect_contextual_names` method)
- Test: `tests/test_pii_detector_names.py`

**Step 1: Write the failing tests**

Append to `tests/test_pii_detector_names.py`:

```python
# ---------------------------------------------------------------------------
# TestOrganisationNameDetection
# ---------------------------------------------------------------------------

class TestOrganisationNameDetection:
    """Organisation names provided by the user should be detected as PII."""

    def test_full_org_name_detected(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood Primary School"])
        matches = detector.detect_pii_in_text("Report prepared by Greenwood Primary School", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1
        assert any("Greenwood Primary School" in m.text for m in org_matches)

    def test_org_name_individual_words_detected(self):
        """Individual significant words from org name should also match."""
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood Primary School"])
        matches = detector.detect_pii_in_text("The Greenwood campus is located nearby", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1

    def test_org_name_short_words_excluded(self):
        """Words shorter than 3 chars from org names should not become variations."""
        detector = PIIDetector("Jane Smith", organisation_names=["St Mary's"])
        # "St" is only 2 chars — should not match standalone
        matches = detector.detect_pii_in_text("St Patrick went to the store", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        # Should NOT match "St" alone — only full "St Mary's" or "Mary's" (5 chars)
        assert not any(m.text == "St" for m in org_matches)

    def test_org_name_confidence_is_095(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Riverside Clinic"])
        matches = detector.detect_pii_in_text("Riverside Clinic assessment results", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1
        assert org_matches[0].confidence == 0.95

    def test_multiple_org_names(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood PS", "Dr Kim Psychology"])
        matches = detector.detect_pii_in_text("Referred by Dr Kim Psychology to Greenwood PS", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 2

    def test_org_name_none_defaults_to_empty(self):
        """Passing None for organisation_names should not crash."""
        detector = PIIDetector("Jane Smith", organisation_names=None)
        assert detector.organisation_names == []

    def test_org_name_source_is_regex(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Riverside Clinic"])
        matches = detector.detect_pii_in_text("Riverside Clinic report", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert all(m.source == 'regex' for m in org_matches)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pii_detector_names.py::TestOrganisationNameDetection -v`
Expected: FAIL — `organisation_names` is not a valid parameter

**Step 3: Implement organisation name detection**

In `src/core/pii_detector.py`:

**3a. Update constructor (line 123):**

Change the signature from:
```python
def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None):
```
to:
```python
def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None, organisation_names: List[str] = None):
```

After line 134 (`self.family_names = ...`), add:
```python
        self.organisation_names = [n.strip() for n in (organisation_names or [])]
```

**3b. Add `_detect_organisation_names` method** (new method, add after `_detect_contextual_names` at ~line 419):

```python
    def _detect_organisation_names(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect user-provided organisation names and their significant words."""
        matches = []

        for org_name in self.organisation_names:
            # Full org name match
            pattern = re.compile(r'\b' + re.escape(org_name) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Organisation name',
                    confidence=0.95,
                    page_num=page_num,
                    line_num=line_num,
                    context=context,
                    source='regex',
                ))

            # Individual word variations (3+ chars, skip common words)
            for word in org_name.split():
                if len(word) < 3:
                    continue
                if word.lower() in _CONTEXTUAL_NAME_EXCLUDE:
                    continue
                # Skip generic words like "School", "Primary", "Clinic", "Centre"
                if word.lower() in {'school', 'primary', 'secondary', 'college', 'clinic',
                                    'centre', 'center', 'hospital', 'practice', 'academy',
                                    'institute', 'university', 'department', 'service',
                                    'services', 'psychology', 'medical', 'health', 'group',
                                    'the', 'and', 'for', 'inc', 'ltd', 'pty'}:
                    continue
                word_pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                for match in word_pattern.finditer(line):
                    context = self._get_context(line, match.start(), match.end())
                    matches.append(PIIMatch(
                        text=match.group(),
                        category='Organisation name',
                        confidence=0.95,
                        page_num=page_num,
                        line_num=line_num,
                        context=context,
                        source='regex',
                    ))

        return matches
```

**3c. Wire it into `detect_pii_in_text` (line 206):**

After the `_detect_contextual_names` call (line 206), add:
```python
            # Detect organisation names
            matches.extend(self._detect_organisation_names(line, page_num, line_num))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pii_detector_names.py::TestOrganisationNameDetection -v`
Expected: ALL PASS

**Step 5: Run full test suite to check nothing broke**

Run: `pytest tests/test_pii_detector_names.py tests/test_pii_detector.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/core/pii_detector.py tests/test_pii_detector_names.py
git commit -m "feat: add organisation name detection as new PII category"
```

---

## Task 3: Pass `organisation_names` Through Orchestrator and Services

**Files:**
- Modify: `src/core/pii_orchestrator.py:42` (constructor)
- Modify: `src/services/detection_service.py:41` (constructor)
- Test: `tests/test_pii_orchestrator.py`

**Step 1: Write the failing test**

Append to `tests/test_pii_orchestrator.py`:

```python
class TestOrganisationNamePassthrough:
    """Verify organisation names flow through orchestrator to detector."""

    def test_org_names_passed_to_detector(self):
        orch = PIIOrchestrator("Jane Smith", organisation_names=["Greenwood PS"])
        assert orch.regex_detector.organisation_names == ["Greenwood PS"]

    def test_org_names_detected_via_orchestrator(self):
        orch = PIIOrchestrator("Jane Smith", organisation_names=["Greenwood PS"])
        matches = orch.detect_pii_in_text("Report from Greenwood PS", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pii_orchestrator.py::TestOrganisationNamePassthrough -v`
Expected: FAIL — `organisation_names` not accepted

**Step 3: Update PIIOrchestrator**

In `src/core/pii_orchestrator.py`, update the constructor (line ~42):

Change from:
```python
def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None):
```
to:
```python
def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None, organisation_names: List[str] = None):
```

Add after `self.family_names = ...`:
```python
        self.organisation_names = organisation_names or []
```

Update the PIIDetector instantiation to pass `organisation_names`:
```python
        self.regex_detector = PIIDetector(
            self.student_name,
            parent_names=self.parent_names,
            family_names=self.family_names,
            organisation_names=self.organisation_names,
        )
```

**Step 4: Update DetectionService**

In `src/services/detection_service.py`, update the constructor (line ~41):

Change from:
```python
def __init__(
    self,
    student_name: str,
    parent_names: List[str] = None,
    family_names: List[str] = None,
):
```
to:
```python
def __init__(
    self,
    student_name: str,
    parent_names: List[str] = None,
    family_names: List[str] = None,
    organisation_names: List[str] = None,
):
```

Update the PIIOrchestrator instantiation:
```python
        self._orchestrator = PIIOrchestrator(
            student_name=student_name,
            parent_names=parent_names or [],
            family_names=family_names or [],
            organisation_names=organisation_names or [],
        )
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pii_orchestrator.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/core/pii_orchestrator.py src/services/detection_service.py tests/test_pii_orchestrator.py
git commit -m "feat: pass organisation_names through orchestrator and detection service"
```

---

## Task 4: Add `organisation_names` to RedactionRequest and Filename Stripping

**Files:**
- Modify: `src/services/redaction_service.py:17-30` (RedactionRequest dataclass)
- Modify: `src/services/redaction_service.py:104-114` (execute method — name_variations builder)
- Test: `tests/test_filename_redaction.py`

**Step 1: Write the failing test**

Append to `tests/test_filename_redaction.py`:

```python
class TestOrganisationNameInFilename:
    """Organisation names in filenames should be replaced with [REDACTED]."""

    def test_org_name_stripped_from_filename(self):
        result = strip_pii_from_filename(
            "Greenwood PS - Jane Smith Report.pdf",
            ["Jane Smith", "Jane", "Smith", "Greenwood PS"]
        )
        assert "Greenwood" not in result
        assert "Jane" not in result
        assert "[REDACTED]" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_filename_redaction.py::TestOrganisationNameInFilename -v`
Expected: This test should actually PASS already since `strip_pii_from_filename` takes a list of names — it's just a matter of the caller passing org names in the list. Verify first.

**Step 3: Update RedactionRequest and execute()**

In `src/services/redaction_service.py`:

**3a. Add field to RedactionRequest (after line 30):**
```python
    organisation_names: List[str] = field(default_factory=list)
```

**3b. Update name_variations builder in execute() (after line 114):**

After the existing loop that appends parent/family names, add:
```python
        for name in request.organisation_names:
            if len(name) >= 3 and name not in name_variations:
                name_variations.append(name)
            # Also add individual significant words from org names
            for word in name.split():
                if len(word) >= 3 and word not in name_variations:
                    if word.lower() not in {'school', 'primary', 'secondary', 'college',
                                            'clinic', 'centre', 'center', 'hospital',
                                            'practice', 'academy', 'the', 'and', 'for',
                                            'inc', 'ltd', 'pty'}:
                        name_variations.append(word)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_filename_redaction.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/services/redaction_service.py tests/test_filename_redaction.py
git commit -m "feat: add organisation_names to RedactionRequest and filename stripping"
```

---

## Task 5: Add `redact_header_footer` to Redaction Pipeline

**Files:**
- Modify: `src/core/redactor.py:87` (`redact_pdf` signature and body)
- Create: `tests/test_zone_redaction.py`

**Step 1: Write the failing tests**

Create `tests/test_zone_redaction.py`:

```python
"""Tests for header/footer zone redaction (Stage 0)."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import tempfile
from pathlib import Path
from redactor import PDFRedactor, RedactionItem

# Constants matching redactor.py
HEADER_ZONE_FRACTION = 0.12
FOOTER_ZONE_FRACTION = 0.08


def _create_pdf_with_text(text_positions):
    """
    Create a test PDF with text at specific vertical positions.

    Args:
        text_positions: list of (text, y_fraction) where y_fraction is 0.0 (top) to 1.0 (bottom)

    Returns:
        Path to temporary PDF
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    for text, y_frac in text_positions:
        y = page.rect.height * y_frac
        point = fitz.Point(50, y)
        page.insert_text(point, text, fontsize=12)

    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    doc.save(tmp.name)
    doc.close()
    return Path(tmp.name)


class TestZoneRedaction:
    """Header/footer zone blanking."""

    def test_header_text_removed_when_enabled(self):
        """Text in top 12% of page should be gone after zone redaction."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),   # In header zone (5% from top)
            ("Main body text here", 0.50),  # In body (50%)
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        # Need at least one redaction item (even empty list is fine for zone-only)
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" not in text
        assert "Main body text" in text
        doc.close()

        # Cleanup
        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_footer_text_removed_when_enabled(self):
        """Text in bottom 8% of page should be gone after zone redaction."""
        pdf_path = _create_pdf_with_text([
            ("Main body text here", 0.50),
            ("123 School St, Sydney NSW 2000", 0.96),  # In footer zone
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "123 School St" not in text
        assert "Main body text" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zones_not_redacted_when_disabled(self):
        """When redact_header_footer=False, header/footer text should survive."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),
            ("Main body text here", 0.50),
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=False)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zone_redaction_default_is_false(self):
        """Default behaviour should NOT redact zones (backwards compatible)."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),
            ("Main body text here", 0.50),
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        # No redact_header_footer param — should default to False
        success, msg = redactor.redact_pdf(pdf_path, output, [])

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zone_redaction_runs_on_all_pages(self):
        """Zone redaction should apply to EVERY page, not just pages with PII."""
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=595, height=842)
            page.insert_text(fitz.Point(50, 42), f"HEADER PAGE {i+1}", fontsize=12)
            page.insert_text(fitz.Point(50, 421), f"Body page {i+1}", fontsize=12)

        tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(tmp.name)
        doc.close()
        pdf_path = Path(tmp.name)
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        for i in range(3):
            text = doc[i].get_text()
            assert f"HEADER PAGE {i+1}" not in text
            assert f"Body page {i+1}" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_zone_redaction.py -v`
Expected: FAIL — `redact_pdf` doesn't accept `redact_header_footer` parameter

**Step 3: Implement zone redaction in `redactor.py`**

**3a. Add constants at module level** (after the imports, before `RedactionItem` class, around line 15):

```python
# Zone redaction: fraction of page height to blank
HEADER_ZONE_FRACTION = 0.12   # Top 12% (~3.6cm on A4)
FOOTER_ZONE_FRACTION = 0.08   # Bottom 8% (~2.4cm on A4)
```

**3b. Update `redact_pdf` signature** (line 87):

Change from:
```python
def redact_pdf(self, input_pdf: Path, output_pdf: Path, redaction_items: List[RedactionItem]) -> Tuple[bool, str]:
```
to:
```python
def redact_pdf(self, input_pdf: Path, output_pdf: Path, redaction_items: List[RedactionItem], redact_header_footer: bool = False) -> Tuple[bool, str]:
```

**3c. Add Stage 0 — zone redaction** (inside `redact_pdf`, after `doc = fitz.open(...)` at line 100, BEFORE the `redactions_by_page` grouping):

```python
            # Stage 0: Header/footer zone blanking (runs on EVERY page)
            if redact_header_footer:
                for page in doc:
                    self._redact_zones(page)
```

**3d. Add `_redact_zones` method** (new method on PDFRedactor, after `_is_image_only_page`):

```python
    def _redact_zones(self, page: fitz.Page) -> None:
        """
        Blank header and footer zones on a page.

        For text-layer pages: uses PyMuPDF redaction annotations.
        For image-only pages: renders at 300 DPI and draws black rectangles via PIL.
        """
        rect = page.rect
        header_rect = fitz.Rect(0, 0, rect.width, rect.height * HEADER_ZONE_FRACTION)
        footer_rect = fitz.Rect(0, rect.height * (1 - FOOTER_ZONE_FRACTION), rect.width, rect.height)

        if self._is_image_only_page(page):
            # Image-only: render → PIL → draw black rects → replace page
            import io
            from PIL import Image, ImageDraw

            scale = 300 / 72  # 300 DPI
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)

            # Header zone in pixel space
            h_y1 = int(pix.height * HEADER_ZONE_FRACTION)
            draw.rectangle([0, 0, pix.width, h_y1], fill="black")

            # Footer zone in pixel space
            f_y0 = int(pix.height * (1 - FOOTER_ZONE_FRACTION))
            draw.rectangle([0, f_y0, pix.width, pix.height], fill="black")

            # Replace page content
            img_bytes = io.BytesIO()
            img.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()

            page.clean_contents()
            doc = page.parent
            for xref in page.get_contents():
                doc.update_stream(xref, b"")
            page.insert_image(page.rect, stream=img_bytes, overlay=True)
        else:
            # Text-layer: use redaction annotations
            page.add_redact_annot(header_rect, fill=(0, 0, 0))
            page.add_redact_annot(footer_rect, fill=(0, 0, 0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_zone_redaction.py -v`
Expected: ALL PASS

**Step 5: Run existing redactor tests to check nothing broke**

Run: `pytest tests/test_redactor.py tests/test_ocr_redaction.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/core/redactor.py tests/test_zone_redaction.py
git commit -m "feat: add header/footer zone redaction (Stage 0) to redact_pdf"
```

---

## Task 6: Wire `redact_header_footer` Through RedactionService

**Files:**
- Modify: `src/services/redaction_service.py:17-30` (RedactionRequest — add field)
- Modify: `src/services/redaction_service.py:86+` (execute method — pass to redactor)

**Step 1: Add field to RedactionRequest**

In `src/services/redaction_service.py`, add to the `RedactionRequest` dataclass (after the `organisation_names` field added in Task 4):

```python
    redact_header_footer: bool = True
```

**Step 2: Pass flag through to `redact_pdf()` calls**

Find where `self._redactor.redact_pdf(...)` is called in `_process_document()`. Add `redact_header_footer=request.redact_header_footer` to the call. Since `_process_document` doesn't currently receive the request object, you'll need to pass the flag through.

Read the `_process_document` method signature and update it to accept `redact_header_footer: bool = False` as a parameter. Then in `execute()`, pass `redact_header_footer=request.redact_header_footer` when calling `_process_document`.

In the `_process_document` body, where `self._redactor.redact_pdf(...)` is called, add:
```python
redact_header_footer=redact_header_footer
```

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS (existing tests use default `redact_header_footer=False` so behaviour unchanged)

**Step 4: Commit**

```bash
git add src/services/redaction_service.py
git commit -m "feat: wire redact_header_footer through RedactionService to redactor"
```

---

## Task 7: Update UI — Organisation Names Input, Guidance Text, Zone Checkbox

**Files:**
- Modify: `src/ui/screens.py:16-86` (folder_selection_screen)
- Modify: `src/ui/screens.py:186-211` (_run_detection)
- Modify: `src/ui/screens.py:349-417` (_run_redaction / final_confirmation_screen)

**Step 1: Add user guidance text to folder_selection_screen**

In `src/ui/screens.py`, inside `folder_selection_screen()`, BEFORE the "Student Information" heading (line 43), add:

```python
    # User guidance
    st.info(
        "💡 **How this tool works**\n\n"
        "This tool scans your documents for personal information — names, phone numbers, "
        "emails, addresses, and more — then permanently blacks them out.\n\n"
        "**The more names you provide below, the more accurate the redaction.** "
        "Names can be hidden inside images, logos, and letterheads that are hard to spot manually. "
        "By entering organisation names (schools, clinics, practices), parent names, and family "
        "member names, you give the tool the best chance of finding and removing all identifying "
        "information.\n\n"
        "The tool may still miss some items — especially in low-quality scans — but providing "
        "more details significantly improves accuracy."
    )
```

**Step 2: Add organisation names input field**

After the `family_names` text input (line 63), add:

```python
    organisation_names = st.text_input(
        "Organisation names (optional, comma-separated):",
        value=st.session_state.organisation_names,
        placeholder="e.g., Greenwood Primary School, Dr Kim Psychology",
        help="Schools, clinics, medical practices — any organisation name that appears in the documents"
    )
```

After line 69 (`st.session_state.family_names = family_names`), add:
```python
    st.session_state.organisation_names = organisation_names
```

**Step 3: Add header/footer zone checkbox**

After the organisation names input and before the divider, add:

```python
    st.divider()
    st.markdown("#### Redaction Options")

    redact_header_footer = st.checkbox(
        "Redact header and footer zones on every page",
        value=st.session_state.redact_header_footer,
        help="Blanks the top ~12% and bottom ~8% of every page. Useful for removing letterheads, "
             "school logos, and footer contact details. May remove non-PII content in those zones."
    )
    st.session_state.redact_header_footer = redact_header_footer
```

**Step 4: Update `_run_detection()` to pass organisation_names**

In `_run_detection()` (around line 186–211), after the `family_list` split, add:

```python
    org_list = [n.strip() for n in st.session_state.organisation_names.split(',') if n.strip()]
```

Update the `DetectionService` instantiation:
```python
    service = DetectionService(
        student_name=st.session_state.student_name,
        parent_names=parent_list,
        family_names=family_list,
        organisation_names=org_list,
    )
```

**Step 5: Update `_run_redaction()` to pass organisation_names and redact_header_footer**

In `_run_redaction()` (around line 349–417), after the `_family_list` split, add:

```python
    _org_list = [n.strip() for n in st.session_state.organisation_names.split(',') if n.strip()]
```

Update the `RedactionRequest` instantiation:
```python
    request = RedactionRequest(
        folder_path=st.session_state.folder_path,
        student_name=st.session_state.student_name,
        documents=st.session_state.documents,
        detected_pii=st.session_state.detected_pii,
        user_selections=st.session_state.user_selections,
        folder_action=folder_action,
        parent_names=_parent_list,
        family_names=_family_list,
        organisation_names=_org_list,
        redact_header_footer=st.session_state.redact_header_footer,
    )
```

**Step 6: Manual smoke test**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && source venv/bin/activate && streamlit run app.py`

Verify:
1. Guidance text appears above "Student Information"
2. Organisation names input field is visible
3. "Redact header and footer zones" checkbox appears, checked by default
4. All fields save to session state on page reload

**Step 7: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: add org names input, guidance text, and zone redaction checkbox to UI"
```

---

## Task 8: Update FastAPI Backend Schemas and Endpoints

**Files:**
- Modify: `backend/schemas.py:37-41` (DetectPIIRequest — add field)
- Modify: `backend/schemas.py` (RedactRequest — add fields)
- Modify: `backend/main.py` (detect and redact endpoints)

**Step 1: Update DetectPIIRequest**

In `backend/schemas.py`, update `DetectPIIRequest` (line 37):

```python
class DetectPIIRequest(BaseModel):
    pdf_paths: List[str]
    student_name: str
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []
```

**Step 2: Find and update RedactRequest**

Find the redact request schema in `backend/schemas.py` and add:
```python
    organisation_names: List[str] = []
    redact_header_footer: bool = True
```

**Step 3: Update detect endpoint in `backend/main.py`**

In the `detect_pii` endpoint, pass `organisation_names`:

```python
    service = DetectionService(
        student_name=req.student_name,
        parent_names=req.parent_names,
        family_names=req.family_names,
        organisation_names=req.organisation_names,
    )
```

**Step 4: Update redact endpoint in `backend/main.py`**

In the redact endpoint, pass `organisation_names` and `redact_header_footer` to `RedactionRequest`:

```python
    request = RedactionRequest(
        ...
        organisation_names=req.organisation_names,
        redact_header_footer=req.redact_header_footer,
    )
```

**Step 5: Commit**

```bash
git add backend/schemas.py backend/main.py
git commit -m "feat: add organisation_names and redact_header_footer to API layer"
```

---

## Task 9: Run Full Test Suite and Fix Any Failures

**Step 1: Run all tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && source venv/bin/activate && pytest tests/ -v`

Expected: All tests pass (212 existing + ~15 new = ~227 total). The 5 pre-existing `test_ocr_verification.py` failures (Tesseract env issue) are known and not related to this work.

**Step 2: Fix any failures**

If any tests fail, fix them. Common issues:
- Tests that instantiate `PIIDetector` or `PIIOrchestrator` without the new `organisation_names` param should still work (it defaults to `None`/`[]`).
- Tests that mock `redact_pdf` may need the new `redact_header_footer` param in their mock signature.

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve test failures from org names and zone redaction changes"
```

---

## Task 10: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update Session State Keys table**

Add to the session state keys table:

| Key | Type | Purpose |
|-----|------|---------|
| `organisation_names` | str | Comma-separated organisation names |
| `redact_header_footer` | bool | Whether to blank header/footer zones |

**Step 2: Add rule about zone redaction to Critical Non-Obvious Rules**

Add as rule 19:

```
### 19. Zone redaction is Stage 0 — runs before all other redaction stages

`_redact_zones()` runs on EVERY page in the document when `redact_header_footer=True`. It blanks the top 12% (header) and bottom 8% (footer) of each page. It runs before text-layer redaction, OCR redaction, embedded image scanning, and widget deletion. For text-layer pages it uses PyMuPDF redaction annotations; for image-only pages it uses the PIL ImageDraw path (same as `_redact_ocr_page`).
```

**Step 3: Add rule about organisation names**

Add as rule 20:

```
### 20. Organisation names generate word-level variations but skip generic words

When the user provides "Greenwood Primary School", the detector creates variations: the full name plus individual words that are 3+ chars and NOT in a generic-words skip list (school, primary, clinic, centre, etc.). This means "Greenwood" matches but "Primary" and "School" don't. The skip list is in `_detect_organisation_names()`.
```

**Step 4: Update Detection Confidence Values table**

Add:

| Category | Confidence | Rationale |
|----------|-----------|-----------|
| Organisation name (user-provided) | 0.95 | High — user explicitly named them |

**Step 5: Update Test Structure**

Add the new test files to the test structure listing with their test counts.

**Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with org names, zone redaction rules and session state"
```

---

## Execution Order Summary

| Task | What | Depends On |
|------|------|-----------|
| 1 | Session state keys | — |
| 2 | PIIDetector org name detection | — |
| 3 | Orchestrator + service passthrough | Tasks 1, 2 |
| 4 | RedactionRequest + filename stripping | Task 2 |
| 5 | Zone redaction in redactor.py | — |
| 6 | Wire zone flag through RedactionService | Tasks 1, 5 |
| 7 | UI changes (guidance, inputs, checkbox) | Tasks 1, 3, 4, 6 |
| 8 | FastAPI backend updates | Tasks 3, 4, 6 |
| 9 | Full test suite run | All above |
| 10 | CLAUDE.md updates | All above |

Tasks 1, 2, and 5 are independent and can run in parallel.
Tasks 3 and 4 depend on Task 2.
Task 6 depends on Tasks 1 and 5.
Tasks 7 and 8 depend on everything before them.
Tasks 9 and 10 are final validation.
