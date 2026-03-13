# Fix Over-Redaction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix systematic over-redaction by tightening NER entity scope, raising confidence thresholds, filtering out location and general-date entities, and enforcing word-boundary matching at redaction time.

**Architecture:** Five targeted changes across three files. Options B (entity filtering + confidence tuning) and C (word-boundary enforcement) are independent and can be implemented in either order. Each change has its own failing test written first. All changes degrade gracefully — if NER engines are absent, the regex engine still runs unchanged.

**Tech Stack:** Python 3.13, pytest, PyMuPDF (`fitz`), presidio-analyzer, gliner

---

## Background: What's Over-Redacting and Why

From analysis of the sample IEP document, five distinct root causes were identified:

| Root cause | Affected file | Symptom |
|---|---|---|
| GLiNER `"date"` label | `gliner_provider.py` | Meeting dates, review dates redacted |
| GLiNER `"location"` label | `gliner_provider.py` | Suburbs (e.g. "Essendon") redacted |
| GLiNER threshold 0.5 too low | `gliner_provider.py` | "Concerta", "Tashi", "MacqLit" flagged as persons |
| Presidio LOCATION/GPE/FAC + DATE_TIME | `pii_orchestrator.py` | Same as GLiNER location + date issues via spaCy NER |
| Presidio score_threshold 0.4 too low | `pii_orchestrator.py` | Low-confidence proper nouns treated as PII |
| `_detect_contextual_names` exclude list | `pii_detector.py` | "Dad" extracted as a parent name after "Carer: Dad" |
| No min-length filter on NER output | `pii_orchestrator.py` | 1-2 char entities passed to redactor, erase partial words |
| `_redact_text_search` no word-boundary | `redactor.py` | Short text (e.g. "Jo") erases "Joe" → "be" |

**Scope decisions (confirmed with user):**
- All names of real people should be redacted (NER person detection is intentional and correct)
- DOB dates only — meeting dates, review dates should NOT be redacted
- Only school names and student-tied locations — general suburbs and city names should NOT be redacted

---

## Task 1: Fix GLiNER entity labels and raise threshold

**Files:**
- Modify: `src/core/gliner_provider.py` (lines 26–35, 41)
- Test: `tests/test_gliner_provider.py`

The `ENTITY_LABELS` list currently includes `"date"` and `"location"`. These cause GLiNER to redact any date (meeting dates, review dates) and any location name (suburbs, cities). Both must be removed. The threshold of `0.5` is too permissive — at 50% confidence, common program names ("MacqLit"), book characters ("Tashi"), and medications ("Concerta") are incorrectly classified as persons.

**Step 1: Write the failing tests**

Add to `tests/test_gliner_provider.py` inside the `TestGLiNERDetector` class:

```python
def test_general_date_not_detected(self, detector):
    """Meeting dates must not be flagged — only DOB label triggers date redaction."""
    matches = detector.detect(
        "Meeting date: 15 March 2025. Review scheduled for June 2025.",
        page_num=1,
    )
    date_matches = [m for m in matches if "date" in m.category.lower() and "birth" not in m.category.lower()]
    assert len(date_matches) == 0, f"Expected no general date matches, got: {date_matches}"

def test_location_suburb_not_detected(self, detector):
    """Suburb names must not be flagged as PII."""
    matches = detector.detect(
        "The student attends school in Essendon.",
        page_num=1,
    )
    location_matches = [m for m in matches if "location" in m.category.lower()]
    assert len(location_matches) == 0, f"Expected no location matches, got: {location_matches}"

def test_threshold_filters_low_confidence_proper_nouns(self, detector):
    """Program names and medication names must not be detected as persons."""
    matches = detector.detect(
        "The student uses MacqLit and has read Tashi. Concerta is prescribed.",
        page_num=1,
    )
    # None of these proper nouns should appear in matches at threshold 0.65
    false_positive_texts = {"MacqLit", "Tashi", "Concerta"}
    flagged = [m.text for m in matches if m.text in false_positive_texts]
    assert len(flagged) == 0, f"False positives found: {flagged}"
```

**Step 2: Run to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
source venv/bin/activate
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_general_date_not_detected -v
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_location_suburb_not_detected -v
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_threshold_filters_low_confidence_proper_nouns -v
```

Expected: FAIL (currently `"date"` and `"location"` are in labels; threshold is 0.5)

**Step 3: Implement the fix**

In `src/core/gliner_provider.py`, make two changes:

Change `ENTITY_LABELS` (remove `"date"` and `"location"`):

```python
# BEFORE
ENTITY_LABELS = [
    "person",
    "address",
    "phone number",
    "email",
    "date of birth",
    "identification number",
    "date",
    "location",
]

# AFTER
ENTITY_LABELS = [
    "person",
    "address",
    "phone number",
    "email",
    "date of birth",
    "identification number",
]
```

Change `GLiNERDetector.__init__` default threshold:

```python
# BEFORE
def __init__(self, model_name: str = "urchade/gliner_multi_pii-v1", threshold: float = 0.5):

# AFTER
def __init__(self, model_name: str = "urchade/gliner_multi_pii-v1", threshold: float = 0.65):
```

**Step 4: Run to verify they pass**

```bash
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_general_date_not_detected -v
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_location_suburb_not_detected -v
pytest tests/test_gliner_provider.py::TestGLiNERDetector::test_threshold_filters_low_confidence_proper_nouns -v
```

Expected: PASS

**Step 5: Run full suite to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: All 142 tests pass (GLiNER-marked tests will skip if model unavailable)

**Step 6: Commit**

```bash
git add src/core/gliner_provider.py tests/test_gliner_provider.py
git commit -m "fix: remove date/location from GLiNER labels and raise threshold to 0.65"
```

---

## Task 2: Fix Presidio entity type filtering and raise score threshold

**Files:**
- Modify: `src/core/pii_orchestrator.py` (lines 12–26 PRESIDIO_CATEGORY_MAP, line 150 score_threshold)
- Test: `tests/test_pii_orchestrator.py`

Presidio's spaCy NER produces `LOCATION`, `GPE`, `FAC`, and `DATE_TIME` entity types for general location names and dates. These are too broad. The custom Australian recognizers use more specific types (`AU_DOB`, `AU_PHONE`, etc.) and are unaffected. Raising `score_threshold` from `0.4` to `0.55` reduces low-confidence false positives.

**Step 1: Write the failing tests**

Add to `tests/test_pii_orchestrator.py`, inside `TestPresidioIntegration`:

```python
def test_general_location_not_flagged_via_presidio(self):
    """Suburb names from Presidio LOCATION/GPE should be filtered out."""
    orch = PIIOrchestrator("Tom Jones")
    matches = orch.detect_pii_in_text(
        "The student lives in Essendon and attends school in Moonee Ponds.",
        page_num=1,
    )
    # No location entity should appear in results
    location_matches = [
        m for m in matches
        if m.source == "presidio" and "location" in m.category.lower()
    ]
    assert len(location_matches) == 0, f"Got location matches: {location_matches}"

def test_general_date_not_flagged_via_presidio(self):
    """Meeting dates from Presidio DATE_TIME should be filtered out."""
    orch = PIIOrchestrator("Tom Jones")
    matches = orch.detect_pii_in_text(
        "The IEP meeting was held on 15 March 2025. Review date: June 2025.",
        page_num=1,
    )
    date_matches = [
        m for m in matches
        if m.source == "presidio" and "date" in m.category.lower() and "birth" not in m.category.lower()
    ]
    assert len(date_matches) == 0, f"Got date matches: {date_matches}"

def test_person_still_detected_after_location_filter(self):
    """PERSON entity should still come through — only location/date types are filtered."""
    orch = PIIOrchestrator("Tom Jones")
    matches = orch.detect_pii_in_text(
        "Dr. Sarah Williams examined the student in Essendon.",
        page_num=1,
    )
    person_matches = [
        m for m in matches
        if m.source == "presidio" and "person" in m.category.lower()
    ]
    assert len(person_matches) > 0
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_general_location_not_flagged_via_presidio -v
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_general_date_not_flagged_via_presidio -v
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_person_still_detected_after_location_filter -v
```

Expected: FAIL

**Step 3: Implement the fix**

In `src/core/pii_orchestrator.py`:

Add a skip-set constant just below the `PRESIDIO_CATEGORY_MAP` dict:

```python
# Entity types from Presidio that are too broad for this use case.
# LOCATION/GPE/FAC: general place names — the regex ADDRESS_PATTERN is more precise.
# DATE_TIME: general dates — only AU_DOB (custom recognizer) should trigger date redaction.
PRESIDIO_SKIP_TYPES = {"LOCATION", "GPE", "FAC", "DATE_TIME"}
```

In `_run_presidio()`, add a skip check at the top of the `for result in results:` loop:

```python
for result in results:
    # Skip entity types that are too broad (locations, general dates)
    if result.entity_type in PRESIDIO_SKIP_TYPES:
        continue

    # ... rest of existing code ...
```

Raise `score_threshold` in the `analyze()` call:

```python
# BEFORE
results = self.presidio_analyzer.analyze(
    text=text,
    language="en",
    score_threshold=0.4,
)

# AFTER
results = self.presidio_analyzer.analyze(
    text=text,
    language="en",
    score_threshold=0.55,
)
```

**Step 4: Run to verify they pass**

```bash
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_general_location_not_flagged_via_presidio -v
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_general_date_not_flagged_via_presidio -v
pytest tests/test_pii_orchestrator.py::TestPresidioIntegration::test_person_still_detected_after_location_filter -v
```

Expected: PASS

**Step 5: Run full suite to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: All 142 tests pass

**Step 6: Commit**

```bash
git add src/core/pii_orchestrator.py tests/test_pii_orchestrator.py
git commit -m "fix: skip LOCATION/GPE/FAC/DATE_TIME from Presidio and raise threshold to 0.55"
```

---

## Task 3: Add minimum-length filter for NER results in the orchestrator

**Files:**
- Modify: `src/core/pii_orchestrator.py` (`detect_pii_in_text` method, ~lines 112–140)
- Test: `tests/test_pii_orchestrator.py`

The regex engine already enforces a 3-character minimum on name variations. NER engines (Presidio and GLiNER) have no such guard. A 1–2 character entity passed to `_redact_text_search` will match inside any word containing those characters, causing partial erasure. Example: "Jo" detected by GLiNER → `search_for("Jo")` erases "Jo" inside "Joe", leaving "be".

**Step 1: Write the failing tests**

Add to `TestOrchestratorBasic` in `tests/test_pii_orchestrator.py`:

```python
def test_ner_result_shorter_than_3_chars_is_filtered(self):
    """A 1-2 char NER result must never reach the output list."""
    orch = PIIOrchestrator("Jo Li")
    # Inject a synthetic 2-char match as if from Presidio
    short_match = PIIMatch(
        text="Jo", category="Person name (NER)", confidence=0.9,
        page_num=1, line_num=1, context="Jo Li", source="presidio"
    )
    result = orch._deduplicate([short_match])
    # Even if it made it to _deduplicate, the filter in detect_pii_in_text should drop it
    # Test detect_pii_in_text directly to confirm filtering happens before dedup
    # Patch presidio to inject the short match
    original = orch._run_presidio
    orch._run_presidio = lambda text, page_num: [short_match]
    orch.presidio_analyzer = object()  # non-None to trigger presidio path
    matches = orch.detect_pii_in_text("Jo Li lives here.", page_num=1)
    orch._run_presidio = original
    # The 2-char NER match "Jo" must not appear in final results from presidio source
    short_ner = [m for m in matches if m.source == "presidio" and len(m.text) < 3]
    assert len(short_ner) == 0, f"Short NER result slipped through: {short_ner}"

def test_ner_result_exactly_3_chars_is_kept(self):
    """A 3-char NER result (e.g. a real 3-letter first name) must not be filtered."""
    orch = PIIOrchestrator("Tom Jones")
    three_char = PIIMatch(
        text="Tom", category="Person name (NER)", confidence=0.9,
        page_num=1, line_num=1, context="Tom Jones", source="presidio"
    )
    original = orch._run_presidio
    orch._run_presidio = lambda text, page_num: [three_char]
    orch.presidio_analyzer = object()
    matches = orch.detect_pii_in_text("Tom Jones is here.", page_num=1)
    orch._run_presidio = original
    ner_tom = [m for m in matches if m.source == "presidio" and m.text == "Tom"]
    assert len(ner_tom) == 1
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_pii_orchestrator.py::TestOrchestratorBasic::test_ner_result_shorter_than_3_chars_is_filtered -v
pytest tests/test_pii_orchestrator.py::TestOrchestratorBasic::test_ner_result_exactly_3_chars_is_kept -v
```

Expected: FAIL

**Step 3: Implement the fix**

In `src/core/pii_orchestrator.py`, in `detect_pii_in_text`, filter NER results immediately after collecting them:

```python
# BEFORE
if self.presidio_analyzer:
    presidio_matches = self._run_presidio(text, page_num)
    all_matches.extend(presidio_matches)

if self.gliner_detector:
    gliner_matches = self.gliner_detector.detect(text, page_num)
    all_matches.extend(gliner_matches)

# AFTER
if self.presidio_analyzer:
    presidio_matches = self._run_presidio(text, page_num)
    # Filter out NER results shorter than 3 chars — prevents partial-word erasure
    all_matches.extend(m for m in presidio_matches if len(m.text) >= 3)

if self.gliner_detector:
    gliner_matches = self.gliner_detector.detect(text, page_num)
    # Filter out NER results shorter than 3 chars — prevents partial-word erasure
    all_matches.extend(m for m in gliner_matches if len(m.text) >= 3)
```

**Step 4: Run to verify they pass**

```bash
pytest tests/test_pii_orchestrator.py::TestOrchestratorBasic::test_ner_result_shorter_than_3_chars_is_filtered -v
pytest tests/test_pii_orchestrator.py::TestOrchestratorBasic::test_ner_result_exactly_3_chars_is_kept -v
```

Expected: PASS

**Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: All 142 tests pass

**Step 6: Commit**

```bash
git add src/core/pii_orchestrator.py tests/test_pii_orchestrator.py
git commit -m "fix: filter NER results shorter than 3 chars to prevent partial-word erasure"
```

---

## Task 4: Fix contextual name false positives in `_detect_contextual_names`

**Files:**
- Modify: `src/core/pii_detector.py` (lines 344–345 in `_detect_contextual_names`)
- Test: `tests/test_pii_detector_names.py`

`_detect_contextual_names` matches a keyword (e.g. `Carer`) followed by a colon/space then a capitalized word, capturing that word as a parent/guardian name. The exclude list prevents common stop words from being captured, but currently excludes none of the family relationship words themselves. This means text like `"Carer: Dad"` extracts `"Dad"` as a parent name and subsequently redacts it — then every instance of "Dad" in the document gets erased.

**Step 1: Write the failing tests**

Add to `tests/test_pii_detector_names.py`:

```python
class TestContextualNameExcludeList:

    def test_dad_after_carer_not_extracted_as_name(self):
        """'Dad' after a keyword is a relationship word, not a person name."""
        from pii_detector import PIIDetector
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Dad", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        flagged_texts = [m.text for m in contextual]
        assert "Dad" not in flagged_texts, f"'Dad' should not be extracted as a name, got: {flagged_texts}"

    def test_mum_after_carer_not_extracted_as_name(self):
        from pii_detector import PIIDetector
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Mum", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text in ("Mum", "Mom") for m in contextual)

    def test_mother_after_lives_with_not_extracted(self):
        from pii_detector import PIIDetector
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Lives with Mother and siblings.", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text == "Mother" for m in contextual)

    def test_real_name_after_carer_still_extracted(self):
        """A real name after 'Carer:' must still be captured."""
        from pii_detector import PIIDetector
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Sarah Thompson", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert any("Sarah" in m.text or "Thompson" in m.text for m in contextual), \
            "Real name after 'Carer:' should be extracted"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_pii_detector_names.py::TestContextualNameExcludeList -v
```

Expected: First three tests FAIL (Dad, Mum, Mother currently not excluded)

**Step 3: Implement the fix**

In `src/core/pii_detector.py`, replace the inline exclude list in `_detect_contextual_names` with a module-level set and expand it:

Add this constant at module level, after the class-level pattern constants (around line 99):

```python
# Words that should never be extracted as a name by contextual detection.
# Includes family relationship terms (to prevent "Carer: Dad" → "Dad" as a parent name),
# titles, articles, prepositions, and common auxiliary verbs.
_CONTEXTUAL_NAME_EXCLUDE = {
    # Titles
    'dr', 'mr', 'mrs', 'ms', 'miss',
    # Family relationship words — these are roles, not names
    'dad', 'mum', 'mom', 'mother', 'father',
    'brother', 'sister', 'sibling',
    'guardian', 'parent', 'carer', 'caregiver',
    'nan', 'nana', 'grandmother', 'grandfather', 'grandma', 'grandpa',
    # Articles, prepositions
    'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for',
    'with', 'from', 'by', 'as',
    # Auxiliary verbs
    'is', 'are', 'was', 'were', 'been', 'be',
    'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'should', 'can', 'could',
    'may', 'might', 'must', 'shall',
}
```

In `_detect_contextual_names`, replace the inline list check:

```python
# BEFORE
if name.lower() not in ['dr', 'mr', 'mrs', 'ms', 'miss', 'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'from', 'by', 'as', 'is', 'are', 'was', 'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'can', 'could', 'may', 'might', 'must', 'shall']:

# AFTER
if name.lower() not in _CONTEXTUAL_NAME_EXCLUDE:
```

**Step 4: Run to verify they pass**

```bash
pytest tests/test_pii_detector_names.py::TestContextualNameExcludeList -v
```

Expected: All four tests PASS

**Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: All 142 tests pass

**Step 6: Commit**

```bash
git add src/core/pii_detector.py tests/test_pii_detector_names.py
git commit -m "fix: expand contextual name exclude list to include family relationship words"
```

---

## Task 5: Word-boundary enforcement in `_redact_text_search`

**Files:**
- Modify: `src/core/redactor.py` (`_redact_text_search` method, lines 90–104)
- Create: `tests/test_redactor.py` (new file — no redactor tests exist yet)

`page.search_for(text)` is a pure substring search. For short texts like "Ann" or "Jo", it matches inside longer words: "Annual" → selects the "Ann" substring and erases it, leaving "ual Review". Tasks 1–4 prevent most short strings from reaching the redactor, but this is a belt-and-suspenders fix for any that slip through. For texts ≤ 6 characters, we verify that the text appears as a standalone word before redacting.

`page.get_text("words")` returns a list of `(x0, y0, x1, y1, text, block_no, line_no, word_no)` tuples. We compare each found rect from `search_for` against the word bbox list to confirm exact-word alignment.

**Step 1: Create the test file**

Create `tests/test_redactor.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
import fitz  # PyMuPDF
from redactor import PDFRedactor


def _make_page_with_text(text: str) -> fitz.Page:
    """Create a single-page in-memory PDF containing the given text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    return page, doc


class TestRedactTextSearch:

    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_very_short_text_under_3_chars_is_skipped(self):
        """Text shorter than 3 characters must never be searched or redacted."""
        page, doc = _make_page_with_text("Jo Smith")
        self.redactor._redact_text_search(page, "Jo")
        # No redact annotation should be added for a 2-char string
        annots = list(page.annots())
        assert len(annots) == 0, "2-char string should not create redaction annotations"
        doc.close()

    def test_short_text_that_is_not_a_whole_word_is_skipped(self):
        """'Ann' must not be redacted when it only appears inside 'Annual'."""
        page, doc = _make_page_with_text("Annual Review completed.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) == 0, "'Ann' inside 'Annual' should not be redacted"
        doc.close()

    def test_short_text_that_is_a_whole_word_is_redacted(self):
        """'Ann' must be redacted when it appears as a standalone word."""
        page, doc = _make_page_with_text("Ann Smith attended the meeting.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) >= 1, "'Ann' as a standalone word should be redacted"
        doc.close()

    def test_long_text_over_6_chars_redacted_without_word_check(self):
        """Texts longer than 6 chars bypass word-boundary check (low false-match risk)."""
        page, doc = _make_page_with_text("Jennifer Smith attended.")
        self.redactor._redact_text_search(page, "Jennifer")
        annots = list(page.annots())
        assert len(annots) >= 1, "8-char name should be redacted normally"
        doc.close()

    def test_short_whole_word_not_redacted_inside_longer_word_on_same_page(self):
        """When 'Ann' appears both standalone AND inside 'Annual', only standalone is redacted."""
        page, doc = _make_page_with_text("Annual review. Ann Smith attended.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        # Should redact 'Ann' in 'Ann Smith' but not 'Ann' in 'Annual'
        # Exactly 1 annotation expected
        assert len(annots) == 1, f"Expected 1 redaction (standalone 'Ann'), got {len(annots)}"
        doc.close()
```

**Step 2: Run to verify tests fail**

```bash
pytest tests/test_redactor.py -v
```

Expected: All 5 tests FAIL (current implementation has no length guard or word-boundary check)

**Step 3: Implement the fix**

In `src/core/redactor.py`, replace `_redact_text_search` and add `_is_whole_word_match` helper:

```python
def _redact_text_search(self, page: fitz.Page, text: str):
    """
    Search for text and redact all whole-word instances.

    For texts ≤ 6 characters, each match rect is verified against the page
    word list to avoid partial-word erasure (e.g. 'Ann' inside 'Annual').
    Texts shorter than 3 characters are skipped entirely.
    """
    if len(text) < 3:
        return

    text_instances = page.search_for(text, flags=fitz.TEXT_PRESERVE_WHITESPACE)
    if not text_instances:
        return

    if len(text) <= 6:
        # Short text: verify each rect aligns with a complete word to avoid partial erasure
        word_rects = [(fitz.Rect(w[:4]), w[4]) for w in page.get_text("words")]
        for rect in text_instances:
            if self._is_whole_word_match(rect, text, word_rects):
                page.add_redact_annot(rect + (-1, -1, 1, 1), fill=(0, 0, 0))
    else:
        for rect in text_instances:
            page.add_redact_annot(rect + (-1, -1, 1, 1), fill=(0, 0, 0))

def _is_whole_word_match(
    self,
    match_rect: fitz.Rect,
    text: str,
    word_rects: list,
) -> bool:
    """
    Return True if match_rect substantially overlaps a word whose text
    exactly equals `text` (case-insensitive).

    Args:
        match_rect: Rect returned by page.search_for()
        text: The text we searched for
        word_rects: List of (fitz.Rect, word_text) tuples from page.get_text("words")
    """
    for word_rect, word_text in word_rects:
        if word_text.strip().lower() == text.strip().lower():
            intersection = match_rect & word_rect
            if intersection.is_valid and intersection.get_area() >= 0.7 * match_rect.get_area():
                return True
    return False
```

**Step 4: Run to verify they pass**

```bash
pytest tests/test_redactor.py -v
```

Expected: All 5 tests PASS

**Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: All tests pass (142 original + 5 new = 147 total)

**Step 6: Commit**

```bash
git add src/core/redactor.py tests/test_redactor.py
git commit -m "fix: enforce word-boundary for short texts in _redact_text_search"
```

---

## Task 6: Final verification

**Step 1: Run the complete test suite one final time**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
source venv/bin/activate
pytest tests/ -v
```

Expected: All tests pass. Note the final count — it should be higher than 142 (new redactor tests added).

**Step 2: Manual smoke test against the sample document**

```bash
streamlit run app.py
```

Open the app and run detection against `sample/Joe Bloggs IEP S2 2025.docx (1).pdf`. Verify:
- [ ] Student name "Joe Bloggs" is redacted
- [ ] Staff names (e.g. therapists, psychologists) are redacted via NER
- [ ] Meeting dates (e.g. "15 March 2025", "June 2025") are **not** redacted
- [ ] Suburb names (e.g. "Essendon", "Moonee Ponds") are **not** redacted
- [ ] Program names (MacqLit, F&P, DIBELS) are **not** redacted
- [ ] Medication names (Concerta) are **not** redacted
- [ ] Phone numbers, email addresses are still redacted
- [ ] DOB (if present in document) is still redacted

**Step 3: Push to test branch**

```bash
git push origin test
```

---

## Summary of Changes

| File | Change | Rationale |
|---|---|---|
| `src/core/gliner_provider.py` | Remove `"date"` and `"location"` from `ENTITY_LABELS`; threshold `0.5 → 0.65` | Prevents general dates and suburbs from being flagged; reduces false positives on proper nouns |
| `src/core/pii_orchestrator.py` | Skip `LOCATION`, `GPE`, `FAC`, `DATE_TIME` from Presidio; `score_threshold 0.4 → 0.55`; 3-char min-length filter on NER output | Matches GLiNER fix; raises quality bar; prevents 1-2 char entities reaching redactor |
| `src/core/pii_detector.py` | Expand `_CONTEXTUAL_NAME_EXCLUDE` to include family relationship words | Prevents "Carer: Dad" from extracting "Dad" as a parent name |
| `src/core/redactor.py` | Add length guard (< 3 chars skipped) + word-boundary check for texts ≤ 6 chars in `_redact_text_search` | Belt-and-suspenders — if a short entity does reach the redactor, it won't erase partial words |
| `tests/test_redactor.py` | New file — 5 tests for word-boundary enforcement | These tests did not exist before |
| `tests/test_gliner_provider.py` | 3 new tests | Regression coverage for entity label and threshold changes |
| `tests/test_pii_orchestrator.py` | 5 new tests | Regression coverage for location filter, date filter, and min-length filter |
| `tests/test_pii_detector_names.py` | 4 new tests | Regression coverage for contextual name exclude list |
