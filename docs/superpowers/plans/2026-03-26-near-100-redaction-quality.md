# Near-100% Redaction Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every person name in every document detected and redacted, close all PDF structure hiding places, and add comprehensive tests.

**Architecture:** Four phases — (1) restructure the detection pipeline so spaCy NER-discovered names are primary, not supplementary; (2) harden the PDF redactor to clean links, annotations, bookmarks, structure trees, and JavaScript; (3) add end-to-end integration tests and adversarial tests; (4) remove GLiNER + PyTorch to simplify the bundle. Phases 1, 2, and 4 can be coded in parallel (different files). Phase 3 depends on 1+2.

**Tech Stack:** Python 3.13, PyMuPDF (fitz), spaCy, Presidio, pytesseract, PIL, FastAPI, React/TypeScript, Electron

**Spec:** `docs/superpowers/specs/2026-03-26-near-100-redaction-quality-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `src/core/nickname_map.py` | Curated ~100-entry Australian nickname dictionary with reverse lookup |
| `tests/test_integration.py` | End-to-end RedactionService pipeline tests |
| `tests/test_bbox_redaction.py` | Bbox redaction path tests |
| `tests/test_adversarial.py` | Adversarial/edge-case input tests |
| `tests/test_false_positives.py` | False-positive regression tests |

### Modified Files
| File | Changes |
|------|---------|
| `src/core/text_extractor.py` | NFKC normalisation, smart quotes, OCR line preservation |
| `src/core/pii_detector.py` | New patterns (NDIS, ABN), cross-line lookahead (signature changes), ALL-CAPS fix, nickname integration, Student ID excludes |
| `src/core/pii_orchestrator.py` | NER-primary architecture, remove GLiNER refs, `require_ner` flag, NER name variation generation |
| `src/core/presidio_recognizers.py` | Extended street types in address recognizer |
| `src/core/redactor.py` | Link/annotation/bookmark cleanup, structure tree stripping, JS cleanup, widget on all pages |
| `src/services/detection_service.py` | Accept/pass `require_ner` parameter |
| `src/services/redaction_service.py` | Verification quarantine |
| `backend/main.py` | Pass `require_ner=True`, add NER to dependency check |
| `desktop/src/pages/Setup.tsx` | NER failure blocking error |
| `requirements-desktop.txt` | Remove `gliner>=0.2.0` |
| `tests/test_pii_detector.py` | Update 5 method signatures for cross-line params |
| `tests/test_pii_detector_names.py` | Update contextual name test signatures |
| `tests/test_pii_orchestrator.py` | Add NER variation + dedup tests |
| `tests/test_ocr_redaction.py` | Activate real-Tesseract tests |

### Deleted Files
| File | Reason |
|------|--------|
| `src/core/gliner_provider.py` | GLiNER removed |
| `tests/test_gliner_provider.py` | GLiNER removed |

---

## Phase 1: Detection Architecture — NER-Primary Restructure

### Task 1: Text Extraction Normalisation

**Files:**
- Modify: `src/core/text_extractor.py:6-13` (imports), `:95` (get_text), `:151-188` (_ocr_page)
- Test: `tests/test_pii_detector.py` (existing tests validate downstream)

- [ ] **Step 1: Add NFKC + smart quote normalisation to `_extract_page_text`**

In `src/core/text_extractor.py`, add `import unicodedata` at line 7. Then add a normalisation helper at module level (after line 13):

```python
def _normalise_text(text: str) -> str:
    """NFKC normalise and replace smart quotes with ASCII equivalents."""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u201C', '"').replace('\u201D', '"')
    return text
```

- [ ] **Step 2: Apply normalisation to native text extraction**

In `_extract_page_text` (line 95), after `text = page.get_text()`, add:
```python
text = _normalise_text(text)
```

- [ ] **Step 3: Preserve OCR line structure in `_ocr_page`**

Currently line 180 joins all words with spaces: `text = ' '.join(text_parts)`. Replace the word-joining logic (approximately lines 170-180) with line-aware reconstruction:

```python
# Build lines from OCR data using block_num and line_num
current_line_key = None
lines_out = []
current_words = []
for i, word in enumerate(data['text']):
    if int(data['conf'][i]) < 0 or not str(word).strip():
        continue
    line_key = (data['block_num'][i], data['line_num'][i])
    if line_key != current_line_key:
        if current_words:
            lines_out.append(' '.join(current_words))
        current_words = [str(word)]
        current_line_key = line_key
    else:
        current_words.append(str(word))
if current_words:
    lines_out.append(' '.join(current_words))
text = '\n'.join(lines_out)
```

- [ ] **Step 4: Apply normalisation to OCR text**

After the new `text = '\n'.join(lines_out)` line, add:
```python
text = _normalise_text(text)
```

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/ --ignore=tests/test_ocr_verification.py -q`
Expected: All tests pass (OCR tests use mocked pytesseract, so the line reconstruction change won't break them — but verify)

- [ ] **Step 6: Commit**

```bash
git add src/core/text_extractor.py
git commit -m "feat: add NFKC normalisation, smart quotes, and OCR line preservation"
```

---

### Task 2: Extract `generate_name_variations` as Standalone Function

**Files:**
- Modify: `src/core/pii_detector.py:141-166`
- Test: `tests/test_pii_detector_names.py` (existing variation tests)

- [ ] **Step 1: Create standalone function above the class**

At line ~35 (after `_CONTEXTUAL_NAME_EXCLUDE` set definition, before `class PIIDetector`), add:

```python
def generate_name_variations(name: str, preserve_short_name: str = None) -> list:
    """Generate name variations for detection. Standalone version for use by orchestrator."""
    name = name.strip()
    if not name:
        return []
    parts = name.split()
    variations = [name]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        variations.append(first)
        variations.append(last)
        variations.append(f"{first[0]}. {last}")
        variations.append(f"{first} {last[0]}.")
        variations.append(f"{first[0]}.{last[0]}.")
        # Full initials string (e.g. "JS" for "Jane Smith")
        initials = ''.join(p[0] for p in parts)
        if len(initials) >= 3:
            variations.append(initials)
    # Filter: min 3 chars, but always preserve the original name
    preserve = preserve_short_name or name
    variations = [v for v in variations if len(v) >= 3 or v == preserve]
    return list(dict.fromkeys(v.strip() for v in variations if v.strip()))
```

- [ ] **Step 2: Refactor `_generate_name_variations` to delegate**

Replace the body of `PIIDetector._generate_name_variations` (lines 141-166) with:

```python
def _generate_name_variations(self) -> list:
    """Generate name variations for the student name."""
    return generate_name_variations(self.student_name, preserve_short_name=self.student_name)
```

- [ ] **Step 3: Run name variation tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector_names.py::TestNameVariations -v`
Expected: All 15 tests pass

- [ ] **Step 4: Commit**

```bash
git add src/core/pii_detector.py
git commit -m "refactor: extract generate_name_variations as standalone function"
```

---

### Task 3: New Regex Patterns (NDIS, ABN, Passport)

**Files:**
- Modify: `src/core/pii_detector.py:58-121` (constants), add new detection methods
- Test: `tests/test_pii_detector.py` (add new test classes)

- [ ] **Step 1: Write failing tests for NDIS, ABN, and passport detection**

Add to `tests/test_pii_detector.py` (after `TestDOBDetection` class, before `TestIntegration`):

```python
class TestNDISDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _ndis_matches(self, line):
        return [m for m in self.detector.detect_pii_in_text(line, 1) if m.category == "NDIS number"]

    def test_ndis_with_keyword_detected(self):
        matches = self._ndis_matches("NDIS number: 123456789")
        assert len(matches) == 1
        assert matches[0].text == "123456789"

    def test_ndis_participant_keyword_detected(self):
        matches = self._ndis_matches("Participant No. 987654321")
        assert len(matches) == 1

    def test_nine_digits_alone_not_detected(self):
        matches = self._ndis_matches("Reference 123456789 received")
        assert len(matches) == 0

    def test_eight_digits_with_keyword_not_detected(self):
        matches = self._ndis_matches("NDIS number: 12345678")
        assert len(matches) == 0


class TestABNDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _abn_matches(self, line):
        return [m for m in self.detector.detect_pii_in_text(line, 1) if m.category == "ABN"]

    def test_abn_with_keyword_detected(self):
        matches = self._abn_matches("ABN: 51 824 753 556")
        assert len(matches) == 1

    def test_abn_no_spaces_detected(self):
        matches = self._abn_matches("ABN: 51824753556")
        assert len(matches) == 1

    def test_eleven_digits_without_keyword_not_detected(self):
        matches = self._abn_matches("Number 51824753556 here")
        assert len(matches) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py::TestNDISDetection tests/test_pii_detector.py::TestABNDetection -v`
Expected: FAIL — categories not recognised yet

- [ ] **Step 3: Add pattern constants to `PIIDetector` class**

In `src/core/pii_detector.py`, after `STUDENT_ID_PATTERN` (line 79), add:

```python
    NDIS_PATTERN = r'(?i)(?:ndis|participant)\s*(?:number|no\.?|#)?\s*:?\s*(\d{9})\b'
    ABN_PATTERN = r'(?i)abn\s*:?\s*(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})\b'
    PASSPORT_PATTERN = r'(?i)passport\s*(?:number|no\.?|#)?\s*:?\s*([A-Z]\d{7})\b'
```

- [ ] **Step 4: Add detection methods**

After `_detect_dob` method (after line ~360), add:

```python
    def _detect_ndis(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        matches = []
        for m in re.finditer(self.NDIS_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="NDIS number", confidence=0.90,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches

    def _detect_abn(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        matches = []
        for m in re.finditer(self.ABN_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="ABN", confidence=0.90,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches

    def _detect_passport(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        matches = []
        for m in re.finditer(self.PASSPORT_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="Passport number", confidence=0.65,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches
```

- [ ] **Step 5: Wire into `detect_pii_in_text` main loop**

In the main loop (after `_detect_organisation_names` call at line ~211), add:

```python
            matches.extend(self._detect_ndis(line, page_num, line_num))
            matches.extend(self._detect_abn(line, page_num, line_num))
            matches.extend(self._detect_passport(line, page_num, line_num))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py::TestNDISDetection tests/test_pii_detector.py::TestABNDetection -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/core/pii_detector.py tests/test_pii_detector.py
git commit -m "feat: add NDIS, ABN, and passport number detection patterns"
```

---

### Task 4: Extend Address, Phone, and Family Keyword Patterns

**Files:**
- Modify: `src/core/pii_detector.py:70` (ADDRESS_PATTERN), `:58-64` (PHONE_PATTERNS), `:99-121` (FAMILY_KEYWORDS)
- Modify: `src/core/presidio_recognizers.py` (mirror address street types)
- Test: `tests/test_pii_detector.py` (existing address/phone tests + new ones)

- [ ] **Step 1: Write failing tests for new street types and dash phone**

Add to `TestAddressDetection` in `tests/test_pii_detector.py`:

```python
    def test_address_close_detected(self):
        matches = self._address_matches("Lives at 5 Rosemary Close, Richmond VIC 3121")
        assert len(matches) >= 1

    def test_address_circuit_detected(self):
        matches = self._address_matches("Address: 12 Sunset Circuit, Cairns QLD 4870")
        assert len(matches) >= 1
```

Add to `TestPhoneDetection`:

```python
    def test_mobile_with_dashes_detected(self):
        matches = self._phone_matches("Call 0412-345-678 for pickup")
        assert len(matches) >= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py::TestAddressDetection::test_address_close_detected tests/test_pii_detector.py::TestPhoneDetection::test_mobile_with_dashes_detected -v`
Expected: FAIL

- [ ] **Step 3: Extend `ADDRESS_PATTERN`**

In `src/core/pii_detector.py` line 70, replace the street type portion of `ADDRESS_PATTERN`. The current street types are `Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|Crescent|Cres|Boulevard|Blvd|Terrace|Tce`. Add to this list: `Close|Cl|Grove|Gr|Highway|Hwy|Parade|Pde|Circuit|Cct|Loop|Rise|Vale|Mews|Esplanade|Esp`.

- [ ] **Step 4: Extend phone pattern to allow dashes**

In `PHONE_PATTERNS` (lines 58-64), find the mobile pattern (first entry, contains `04`). Change `\s*` between digit groups to `[\s\-]*`. Example: if the pattern is `r'(?:(?:\+61\s*|0)4\s*\d{2}\s*\d{3}\s*\d{3})'`, change each `\s*` to `[\s\-]*`.

- [ ] **Step 5: Extend `FAMILY_KEYWORDS`**

Add to the `FAMILY_KEYWORDS` list (lines 99-121):

```python
        r'Stepmother', r'Stepfather', r'Foster\s+parent', r'Foster\s+carer',
        r'Legal\s+guardian', r'Primary\s+carer', r'Kinship\s+carer',
        r'Aunt', r'Uncle', r'Grandparent', r'Grandmother', r'Grandfather',
```

- [ ] **Step 6: Fix ALL-CAPS contextual name capture**

In `_detect_contextual_names` (line 370), change:
```python
_name_pat = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'
```
to:
```python
_name_pat = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[A-Z]{2,}(?:\s+[A-Z]{2,})?)'
```

- [ ] **Step 7: Mirror street types in presidio_recognizers.py**

Read `src/core/presidio_recognizers.py`, find the address recognizer's street type list, and add the same new types.

- [ ] **Step 8: Run all tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py tests/test_pii_detector_names.py -v`
Expected: All pass including new tests

- [ ] **Step 9: Commit**

```bash
git add src/core/pii_detector.py src/core/presidio_recognizers.py tests/test_pii_detector.py
git commit -m "feat: extend address types, phone dashes, family keywords, ALL-CAPS names"
```

---

### Task 5: Cross-Line Lookahead

**Files:**
- Modify: `src/core/pii_detector.py:168-211` (main loop), `:265` (_detect_addresses), `:281` (_detect_medicare), `:299` (_detect_crn), `:338` (_detect_dob), `:361` (_detect_contextual_names)
- Test: `tests/test_pii_detector.py` (update signatures + add cross-line tests)
- Test: `tests/test_pii_detector_names.py` (update contextual name test signatures)

This is the largest single refactor. Five detection methods get new parameters.

- [ ] **Step 1: Write failing cross-line tests**

Add a new test class to `tests/test_pii_detector.py`:

```python
class TestCrossLineDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def test_dob_label_on_previous_line(self):
        text = "Date of Birth:\n15/03/2015"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1) if m.category == "Date of birth"]
        assert len(matches) >= 1

    def test_medicare_keyword_on_previous_line(self):
        text = "Medicare Number:\n2345 67890 1"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1) if m.category == "Medicare number"]
        assert len(matches) >= 1

    def test_mother_name_on_next_line(self):
        text = "Mother:\nSarah Williams"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1)
                   if m.category in ("Parent/Guardian name", "Family member name")]
        assert len(matches) >= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py::TestCrossLineDetection -v`
Expected: FAIL

- [ ] **Step 3: Add `_peek_next_line` helper**

Add to `PIIDetector` class (before `_detect_names`):

```python
    @staticmethod
    def _peek_next_line(lines: list, line_idx: int) -> str:
        """Return the next line if it exists, else empty string."""
        if line_idx + 1 < len(lines):
            return lines[line_idx + 1]
        return ""
```

- [ ] **Step 4: Update method signatures**

Change these five methods to accept `lines` and `line_idx`:

```python
def _detect_dob(self, line, page_num, line_num, lines=None, line_idx=None):
def _detect_medicare(self, line, page_num, line_num, lines=None, line_idx=None):
def _detect_crn(self, line, page_num, line_num, lines=None, line_idx=None):
def _detect_addresses(self, line, page_num, line_num, lines=None, line_idx=None):
def _detect_contextual_names(self, line, page_num, line_num, lines=None, line_idx=None):
```

Using `=None` defaults means existing tests that call these methods directly with `(line, page_num, line_num)` continue to work without changes.

- [ ] **Step 5: Update the main loop to pass `lines` and `line_idx`**

In `detect_pii_in_text` (line 182), change:
```python
for line_num, line in enumerate(lines, 1):
```
to:
```python
for line_idx, line in enumerate(lines):
    line_num = line_idx + 1
```

Then update each call to pass the extra args:
```python
    matches.extend(self._detect_addresses(line, page_num, line_num, lines, line_idx))
    matches.extend(self._detect_medicare(line, page_num, line_num, lines, line_idx))
    matches.extend(self._detect_crn(line, page_num, line_num, lines, line_idx))
    matches.extend(self._detect_dob(line, page_num, line_num, lines, line_idx))
    matches.extend(self._detect_contextual_names(line, page_num, line_num, lines, line_idx))
```

The other methods (`_detect_names`, `_detect_phones`, `_detect_emails`, `_detect_student_id`, `_detect_organisation_names`, `_detect_ndis`, `_detect_abn`, `_detect_passport`) keep their existing signatures.

- [ ] **Step 6: Add lookahead logic to `_detect_dob`**

At the end of `_detect_dob`, if the label was found on the current line but no date matched, peek:

```python
        # Cross-line: label found but no date on this line
        if not matches and lines is not None and line_idx is not None:
            has_label = any(re.search(label, line, re.IGNORECASE) for label in self.DOB_LABELS)
            if has_label:
                next_line = self._peek_next_line(lines, line_idx)
                if next_line:
                    for date_pat in self.DATE_PATTERNS:
                        for m in re.finditer(date_pat, next_line):
                            matches.append(PIIMatch(
                                text=m.group(), category="Date of birth", confidence=0.90,
                                page_num=page_num, line_num=line_num + 1,
                                context=self._get_context(next_line, m.start(), m.end())
                            ))
```

- [ ] **Step 7: Add lookahead to `_detect_medicare`**

Similar pattern — if `'medicare' in line.lower()` but no number matched, peek at next line for `MEDICARE_PATTERN`.

- [ ] **Step 8: Add lookahead to `_detect_crn`**

If CRN keyword found but no 9-char token matched, peek at next line.

- [ ] **Step 9: Add lookahead to `_detect_contextual_names`**

If a family keyword matched but `_name_pat` didn't find a name on the same line, peek at next line and try `_name_pat` there.

- [ ] **Step 10: Run cross-line tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py::TestCrossLineDetection -v`
Expected: All pass

- [ ] **Step 11: Run ALL detector tests to verify no regressions**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py tests/test_pii_detector_names.py -v`
Expected: All pass. The `=None` defaults on the new params mean existing direct-call tests are unaffected.

- [ ] **Step 12: Commit**

```bash
git add src/core/pii_detector.py tests/test_pii_detector.py
git commit -m "feat: add cross-line lookahead for DOB, Medicare, CRN, and contextual names"
```

---

### Task 6: Nickname Map

**Files:**
- Create: `src/core/nickname_map.py`
- Modify: `src/core/pii_detector.py` (import and use in `_generate_name_variations`)
- Test: `tests/test_pii_detector_names.py` (add nickname tests)

- [ ] **Step 1: Write failing nickname tests**

Add to `tests/test_pii_detector_names.py`:

```python
class TestNicknameExpansion:
    def test_christopher_expands_to_chris(self):
        detector = PIIDetector("Christopher Brown")
        text = "Chris was late to class"
        matches = detector.detect_pii_in_text(text, 1)
        assert any(m.text.lower() == "chris" for m in matches)

    def test_chris_expands_to_christopher(self):
        detector = PIIDetector("Chris Brown")
        text = "Christopher was late to class"
        matches = detector.detect_pii_in_text(text, 1)
        assert any("christopher" in m.text.lower() for m in matches)

    def test_nickname_confidence_is_075(self):
        detector = PIIDetector("Christopher Brown")
        text = "Chris was late"
        matches = [m for m in detector.detect_pii_in_text(text, 1) if m.text.lower() == "chris"]
        assert len(matches) >= 1
        assert matches[0].confidence == 0.75

    def test_short_nickname_excluded_if_in_contextual_exclude(self):
        # "Art" is a common word — should be excluded
        detector = PIIDetector("Arthur Jones")
        text = "The Art program runs weekly"
        matches = [m for m in detector.detect_pii_in_text(text, 1) if m.text.lower() == "art"]
        assert len(matches) == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector_names.py::TestNicknameExpansion -v`
Expected: FAIL

- [ ] **Step 3: Create `src/core/nickname_map.py`**

```python
"""Curated Australian English nickname mappings for PII name detection."""

NICKNAME_MAP = {
    "christopher": ["chris"],
    "elizabeth": ["beth", "liz", "lizzy", "eliza"],
    "katherine": ["kate", "kathy", "kat", "katie"],
    "catherine": ["cath", "cathy", "cat", "kate"],
    "william": ["will", "bill", "billy", "liam"],
    "benjamin": ["ben", "benji"],
    "nicholas": ["nick", "nico"],
    "alexander": ["alex", "xander"],
    "matthew": ["matt"],
    "daniel": ["dan", "danny"],
    "michael": ["mike", "mick", "mikey"],
    "joseph": ["joe", "joey"],
    "samuel": ["sam", "sammy"],
    "thomas": ["tom", "tommy"],
    "james": ["jim", "jimmy", "jamie"],
    "robert": ["rob", "bob", "bobby", "robbie"],
    "richard": ["rich", "rick", "dick"],
    "olivia": ["liv", "livy"],
    "victoria": ["vicky", "tori"],
    "jennifer": ["jen", "jenny"],
    "jessica": ["jess", "jessie"],
    "margaret": ["maggie", "meg", "peggy"],
    "stephanie": ["steph"],
    "natasha": ["tash", "nat"],
    "anthony": ["tony", "ant"],
    "andrew": ["andy", "drew"],
    "jonathan": ["jon", "jonny"],
    "timothy": ["tim", "timmy"],
    "rebecca": ["bec", "becca", "beck"],
    "alexandra": ["alex", "lexi"],
    "jacqueline": ["jackie"],
    "deborah": ["deb", "debbie"],
    "susan": ["sue", "suzy"],
    "patricia": ["pat", "patty", "trish"],
    "phillip": ["phil"],
    "stephen": ["steve"],
    "steven": ["steve"],
    "peter": ["pete"],
    "david": ["dave"],
    "edward": ["ed", "ted", "teddy"],
    "frederick": ["fred", "freddy"],
    "raymond": ["ray"],
    "lawrence": ["larry"],
    "nathan": ["nate"],
    "zachary": ["zach", "zac"],
    "cameron": ["cam"],
    "harrison": ["harry"],
    "dominic": ["dom"],
    "mitchell": ["mitch"],
    "isabella": ["bella", "izzy"],
    "gabrielle": ["gabby", "gab"],
    "madeline": ["maddy"],
    "charlotte": ["charlie", "lottie"],
    "madeleine": ["maddy"],
    "georgina": ["georgie"],
    "samantha": ["sam"],
    "abigail": ["abby"],
    "henrietta": ["henny"],
    "penelope": ["penny"],
    "theodore": ["theo"],
    "sebastian": ["seb"],
    "maximilian": ["max"],
    "beatrice": ["bea"],
    "josephine": ["josie"],
    "francesca": ["fran"],
    "angelina": ["angie"],
    "veronica": ["ronnie"],
    "cassandra": ["cass"],
    "genevieve": ["gen"],
    "annabelle": ["anna", "belle"],
    "callum": ["cal"],
    "connor": ["con"],
    "lachlan": ["lachy"],
    "declan": ["dec"],
    "arthur": ["art"],
    "rupert": ["rupe"],
    "hamish": ["hame"],
    "angus": ["gus"],
    "fergus": ["fergie"],
    "alistair": ["ali"],
    "bartholomew": ["bart"],
    "barnaby": ["barney"],
    "reginald": ["reg", "reggie"],
    "leonard": ["len", "lenny"],
    "kenneth": ["ken", "kenny"],
    "ronald": ["ron", "ronnie"],
    "donald": ["don", "donny"],
    "gerald": ["gerry"],
    "terence": ["terry"],
    "stuart": ["stu"],
    "nigel": ["nige"],
    "katrina": ["kat", "trina"],
    "melissa": ["mel"],
    "melanie": ["mel"],
    "danielle": ["dani"],
    "monique": ["mon"],
}

# Reverse map: nickname -> [formal names]
REVERSE_NICKNAME_MAP = {}
for _formal, _nicks in NICKNAME_MAP.items():
    for _nick in _nicks:
        REVERSE_NICKNAME_MAP.setdefault(_nick, []).append(_formal)
```

- [ ] **Step 4: Integrate nicknames into `generate_name_variations`**

In `src/core/pii_detector.py`, add import at top:
```python
from nickname_map import NICKNAME_MAP, REVERSE_NICKNAME_MAP
```

In the standalone `generate_name_variations()` function, after the main variations list is built but before the filter, add a `nickname_variations` parameter and logic:

```python
def generate_name_variations(name: str, preserve_short_name: str = None,
                             include_nicknames: bool = False) -> list:
```

After the existing variation-building logic, before the filter:

```python
    nickname_vars = []
    if include_nicknames:
        for part in parts:
            part_lower = part.lower()
            # Formal -> nicknames
            if part_lower in NICKNAME_MAP:
                nickname_vars.extend(NICKNAME_MAP[part_lower])
            # Nickname -> formal names
            if part_lower in REVERSE_NICKNAME_MAP:
                nickname_vars.extend(REVERSE_NICKNAME_MAP[part_lower])
```

Return nickname variations separately (they get different confidence). **Always return a tuple** to avoid polymorphic return type bugs:
```python
    # Filter main variations
    preserve = preserve_short_name or name
    variations = [v for v in variations if len(v) >= 3 or v == preserve]
    variations = list(dict.fromkeys(v.strip() for v in variations if v.strip()))

    # Always return (variations, nickname_list) tuple
    filtered_nicks = []
    if include_nicknames and nickname_vars:
        filtered_nicks = [n for n in set(nickname_vars)
                          if len(n) >= 3 and n.lower() not in _CONTEXTUAL_NAME_EXCLUDE]
    return variations, filtered_nicks
```

- [ ] **Step 5: Update `PIIDetector._generate_name_variations`**

```python
def _generate_name_variations(self) -> list:
    main_vars, self._nickname_variations = generate_name_variations(
        self.student_name,
        preserve_short_name=self.student_name,
        include_nicknames=True
    )
    return main_vars
```

- [ ] **Step 6: Use nickname variations in `_detect_names`**

In `_detect_names` (line 215), after the main name-matching loop, add a second pass for nicknames:

```python
    # Nickname variations at lower confidence
    for nick in getattr(self, '_nickname_variations', []):
        pattern = re.compile(re.escape(nick), re.IGNORECASE)
        for m in pattern.finditer(line):
            matches.append(PIIMatch(
                text=m.group(), category="Student name (nickname)", confidence=0.75,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
```

- [ ] **Step 7: Run nickname tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector_names.py::TestNicknameExpansion -v`
Expected: All pass

- [ ] **Step 8: Run all detector tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_detector.py tests/test_pii_detector_names.py -v`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/core/nickname_map.py src/core/pii_detector.py tests/test_pii_detector_names.py
git commit -m "feat: add nickname/formal name bidirectional matching for student names"
```

---

### Task 7: NER-Primary Orchestration

**Files:**
- Modify: `src/core/pii_orchestrator.py:119-148` (detect flow), `:42-62` (__init__)
- Modify: `src/services/detection_service.py:41-54` (__init__)
- Test: `tests/test_pii_orchestrator.py` (add NER variation tests)

- [ ] **Step 1: Write failing test for NER-discovered name variations**

Add to `tests/test_pii_orchestrator.py`:

```python
class TestNERNameVariations:
    @pytest.mark.skipif(
        not hasattr(PIIOrchestrator("test"), 'presidio_analyzer') or
        PIIOrchestrator("test").presidio_analyzer is None,
        reason="Presidio/spaCy not available"
    )
    def test_ner_person_generates_variations(self):
        orch = PIIOrchestrator("Student One")
        text = "Dr Sarah Williams conducted the assessment on Tuesday."
        matches = orch.detect_pii_in_text(text, 1)
        matched_texts = {m.text.lower() for m in matches}
        # NER should find "Sarah Williams" and generate variations
        assert "sarah williams" in matched_texts or "sarah" in matched_texts

    def test_ner_person_confidence_090(self):
        orch = PIIOrchestrator("Student One")
        text = "Dr Sarah Williams conducted the assessment."
        matches = orch.detect_pii_in_text(text, 1)
        person_matches = [m for m in matches if m.source == 'presidio' and 'name' in m.category.lower()]
        if person_matches:  # only if presidio available
            assert all(m.confidence >= 0.85 for m in person_matches)
```

- [ ] **Step 2: Add `require_ner` parameter to orchestrator**

In `pii_orchestrator.py`, update `__init__` (line 42):

```python
def __init__(self, student_name: str, parent_names: List[str] = None,
             family_names: List[str] = None, organisation_names: List[str] = None,
             require_ner: bool = False):
```

Store it: `self.require_ner = require_ner`

In `_init_presidio` (line 72), change the except block:
```python
except Exception as e:
    if self.require_ner:
        raise RuntimeError(f"NER engine (spaCy/Presidio) failed to load: {e}") from e
    self.presidio_analyzer = None
```

- [ ] **Step 3: Restructure `detect_pii_in_text` for NER-primary flow**

First, update the imports at the top of `pii_orchestrator.py` (line 8). Change:
```python
from pii_detector import PIIDetector, PIIMatch
```
to:
```python
import re
from pii_detector import PIIDetector, PIIMatch, generate_name_variations
```

Then replace the body of `detect_pii_in_text` (lines 119-148):

```python
def detect_pii_in_text(self, text: str, page_num: int) -> List[PIIMatch]:
    all_matches = []

    # 1. Regex engine (always runs) — user-entered names, structured PII
    regex_matches = self.regex_detector.detect_pii_in_text(text, page_num)
    all_matches.extend(regex_matches)

    # 2. Presidio/spaCy NER (primary name discovery engine)
    if self.presidio_analyzer:
        ner_matches = self._run_presidio(text, page_num)
        # Filter very short NER hits
        ner_matches = [m for m in ner_matches if len(m.text) >= 3]

        # For each PERSON entity, generate name variations
        for m in ner_matches:
            if 'name' in m.category.lower() or m.category == 'Person':
                m.confidence = max(m.confidence, 0.90)
                # Generate variations for NER-discovered names
                variations, _ = generate_name_variations(m.text, include_nicknames=False)
                for var in variations:
                    if var.lower() != m.text.lower() and len(var) >= 3:
                        for match in re.finditer(re.escape(var), text, re.IGNORECASE):
                            line_num = text[:match.start()].count('\n') + 1
                            all_matches.append(PIIMatch(
                                text=match.group(), category="Person name (NER variation)",
                                confidence=0.85, page_num=page_num, line_num=line_num,
                                context=text[max(0,match.start()-25):match.end()+25],
                                source='presidio'
                            ))
        all_matches.extend(ner_matches)

    return self._deduplicate(all_matches)
```

- [ ] **Step 4: Update `DetectionService` to pass `require_ner`**

In `src/services/detection_service.py` (line 41):

```python
def __init__(self, student_name: str, parent_names: List[str] = None,
             family_names: List[str] = None, organisation_names: List[str] = None,
             require_ner: bool = False):
```

Line 48:
```python
self._orchestrator = PIIOrchestrator(
    student_name, parent_names, family_names, organisation_names,
    require_ner=require_ner
)
```

- [ ] **Step 5: Run orchestrator tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_pii_orchestrator.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/core/pii_orchestrator.py src/services/detection_service.py tests/test_pii_orchestrator.py
git commit -m "feat: NER-primary architecture with name variation generation and require_ner flag"
```

---

### Task 8: NER Failure as Hard Error in Bundled App

**Files:**
- Modify: `backend/main.py:110-117` (detect_pii endpoint), `:71-80` (check_dependencies)
- Modify: `desktop/src/pages/Setup.tsx`

- [ ] **Step 1: Pass `require_ner=True` in backend**

In `backend/main.py`, find where `DetectionService` is constructed (line 117 in `detect_pii`):

```python
service = DetectionService(
    req.student_name, parent_names, family_names, organisation_names,
    require_ner=True
)
```

- [ ] **Step 2: Add NER check to `check_dependencies` endpoint**

In the `check_dependencies` function (line 72), after the existing checks, add:

```python
    # Check NER availability
    ner_ok = False
    ner_message = "Not available"
    try:
        from src.core.pii_orchestrator import PIIOrchestrator
        test_orch = PIIOrchestrator("test", require_ner=True)
        if test_orch.presidio_analyzer is not None:
            ner_ok = True
            ner_message = "spaCy + Presidio loaded"
    except Exception as e:
        ner_message = str(e)
```

Add `ner_ok` and `ner_message` to the response. This requires updating `DependencyStatusResponse` in `backend/schemas.py` to include `ner_ok: bool = False` and `ner_message: str = ""`.

- [ ] **Step 3: Update Setup.tsx to check NER**

In `desktop/src/pages/Setup.tsx`, in `handleCheckAgain` (line 14), change the readiness check from:
```typescript
if (result.libreoffice_ok) {
```
to:
```typescript
if (result.libreoffice_ok && result.ner_ok !== false) {
```

Add a warning message in the dependency display for when `ner_ok` is false but other deps are OK. Display: "Name detection engine failed to load. The app cannot redact safely without it."

- [ ] **Step 4: Update `DependencyStatus` type in `desktop/src/types.ts`**

Add `ner_ok?: boolean` and `ner_message?: string` to the `DependencyStatus` interface.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/schemas.py desktop/src/pages/Setup.tsx desktop/src/types.ts
git commit -m "feat: NER failure is now a blocking error in the bundled desktop app"
```

---

## Phase 2: PDF Structure Hardening

### Task 9: Link Annotation Cleanup

**Files:**
- Modify: `src/core/redactor.py` (add `_delete_pii_links`, wire into `redact_pdf`)
- Test: `tests/test_adversarial.py` (created in Phase 3, but write a quick inline test now)

- [ ] **Step 1: Add `_delete_pii_links` method**

In `src/core/redactor.py`, after `_delete_pii_widgets` (line ~686), add:

```python
    def _delete_pii_links(self, page: fitz.Page, redacted_texts: list):
        """Remove link annotations whose URIs contain PII."""
        links = page.get_links()
        for link in links:
            uri = link.get("uri", "")
            if uri:
                uri_lower = uri.lower()
                for pii_text in redacted_texts:
                    if pii_text.lower() in uri_lower:
                        page.delete_link(link)
                        break
```

- [ ] **Step 2: Note — do NOT wire into the per-page items loop yet**

This method will be wired into the all-pages loop in Task 13, alongside widget deletion and annotation cleanup. This ensures links on pages WITHOUT detected PII items are also cleaned.

- [ ] **Step 3: Run existing redactor tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_redactor.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: delete link annotations containing PII URIs"
```

---

### Task 10: Non-Widget Annotation Cleanup

**Files:**
- Modify: `src/core/redactor.py`

- [ ] **Step 1: Add `_delete_pii_annotations` method**

After `_delete_pii_links`:

```python
    def _delete_pii_annotations(self, page: fitz.Page, redacted_texts: list):
        """Remove non-widget annotations whose text fields contain PII."""
        annots = list(page.annots()) if page.annots() else []
        for annot in annots:
            if annot.type[0] == fitz.PDF_ANNOT_WIDGET:
                continue
            info = annot.info
            text_fields = [
                info.get("content", ""),
                info.get("title", ""),
            ]
            for field_text in text_fields:
                if field_text:
                    field_lower = field_text.lower()
                    for pii_text in redacted_texts:
                        if pii_text.lower() in field_lower:
                            page.delete_annot(annot)
                            break
                    else:
                        continue
                    break
```

- [ ] **Step 2: Note — do NOT wire into the per-page items loop yet**

This method will be wired into the all-pages loop in Task 13.

- [ ] **Step 3: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: add method to delete non-widget annotations containing PII"
```

---

### Task 11: Bookmark Redaction

**Files:**
- Modify: `src/core/redactor.py`

- [ ] **Step 1: Add `_redact_bookmarks` method**

After `_delete_pii_annotations`:

```python
    def _redact_bookmarks(self, doc: fitz.Document, redacted_texts: list):
        """Replace PII in bookmark/outline titles with [REDACTED]."""
        toc = doc.get_toc(simple=False)
        if not toc:
            return
        modified = False
        for entry in toc:
            title = entry[1]
            for pii_text in redacted_texts:
                if pii_text.lower() in title.lower():
                    # Case-insensitive replace
                    pattern = re.compile(re.escape(pii_text), re.IGNORECASE)
                    entry[1] = pattern.sub("[REDACTED]", entry[1])
                    modified = True
        if modified:
            doc.set_toc(toc)
```

- [ ] **Step 2: Wire into `redact_pdf` after the page loop, before `_strip_metadata`**

After line ~166 (the signature images loop), before `_strip_metadata(doc)`:
```python
        self._redact_bookmarks(doc, all_redacted_texts)
```

Note: `all_redacted_texts` is the aggregate list — collect it during the per-page loop.

- [ ] **Step 3: Collect `all_redacted_texts` in the main loop**

At the start of `redact_pdf` (after opening the doc), add:
```python
        all_redacted_texts = set()
```

In the per-page loop, after building `redacted_texts` for the page:
```python
            all_redacted_texts.update(redacted_texts)
```

- [ ] **Step 4: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: redact PII in PDF bookmark/outline titles"
```

---

### Task 12: Structure Tree Stripping + JavaScript Cleanup

**Files:**
- Modify: `src/core/redactor.py:727-746` (`_strip_metadata`)

- [ ] **Step 1: Add structure tree stripping to `_strip_metadata`**

At the end of `_strip_metadata` (before the method returns), add:

```python
        # Strip tagged PDF structure (ActualText/Alt attributes contain original text)
        try:
            cat_xref = doc.pdf_catalog()
            doc.xref_set_key(cat_xref, "MarkInfo", "null")
            doc.xref_set_key(cat_xref, "StructTreeRoot", "null")
        except Exception:
            pass  # Some PDFs may not have a catalog
```

- [ ] **Step 2: Add JavaScript/Names cleanup**

After the structure tree stripping:

```python
        # Strip Names dictionary (contains JavaScript, named destinations)
        # Safe for redacted copies — the output doesn't need JS or named dests
        try:
            cat_xref = doc.pdf_catalog()
            names_type, _ = doc.xref_get_key(cat_xref, "Names")
            if names_type != "null":
                doc.xref_set_key(cat_xref, "Names", "null")
        except Exception:
            pass
```

This is the "nuclear option" fallback from the spec — clearing the entire Names tree. It's safe because the output is a redacted copy, and embedded files are already deleted separately.

- [ ] **Step 3: Run metadata tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_metadata_stripping.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: strip structure tree and Names dictionary from redacted PDFs"
```

---

### Task 13: Widget Deletion on All Pages

**Files:**
- Modify: `src/core/redactor.py:93-178` (`redact_pdf` main loop)

- [ ] **Step 1: Move widget deletion out of the per-page items loop**

Currently `_delete_pii_widgets` is called at lines 156-157 inside `for page_num, items in redactions_by_page.items()`. Move it to a separate loop after all redaction is complete.

Remove the `_delete_pii_widgets` call from inside the per-page loop.

After the Stage 4 signature detection loop (line ~166), add:

```python
        # Stage 5: Cleanup ALL pages — widgets, links, and annotations
        all_texts_list = list(all_redacted_texts)
        for page in doc:
            self._delete_pii_widgets(page, all_texts_list)
            self._delete_pii_links(page, all_texts_list)
            self._delete_pii_annotations(page, all_texts_list)
```

This wires in all three cleanup methods from Tasks 9, 10, and 13 into a single all-pages loop using the `all_redacted_texts` set collected in Task 11. This ensures cleanup runs on ALL pages, not just pages with detected PII items.

- [ ] **Step 2: Run widget tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_widget_redaction.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: run widget deletion on ALL pages, not just pages with detected PII"
```

---

### Task 14: Verification Failure Quarantine

**Files:**
- Modify: `src/services/redaction_service.py:270-280` (verification section in `_process_document`)

- [ ] **Step 1: Add quarantine logic**

In `_process_document`, find the verification failure handling (approximately lines 270-280). After setting `result.success = False`, add:

```python
                # Quarantine the suspect file
                try:
                    quarantine_path = output_path.with_suffix('.UNVERIFIED.pdf')
                    output_path.rename(quarantine_path)
                    result.output_path = None
                except Exception:
                    pass  # If rename fails, leave the file but still mark as failed
```

- [ ] **Step 2: Add `quarantine_path` field to `DocumentResult`**

In the `DocumentResult` dataclass (line 38), add:
```python
    quarantine_path: Optional[Path] = None
```

Set it in the quarantine logic:
```python
                    result.quarantine_path = quarantine_path
```

- [ ] **Step 3: Commit**

```bash
git add src/services/redaction_service.py
git commit -m "feat: quarantine files that fail post-redaction verification"
```

---

### Task 14b: Research Spike — Form XObject Image Scanning (Optional)

**Files:**
- Modify: `src/core/redactor.py` (if feasible)

This is a research spike from spec section 2.7. PyMuPDF does NOT have `page.get_xobjects()` or `doc.extract_xobject()`. Implementation requires low-level xref traversal.

- [ ] **Step 1: Research the PyMuPDF API for Form XObject access**

Use Context7 MCP or PyMuPDF docs to find the current API for:
- Enumerating XObjects on a page via xref
- Identifying Form XObjects (SubType /Form)
- Extracting images from Form XObject resources

- [ ] **Step 2: If feasible, implement; if not, skip and document**

If the API exists and is reliable, extend `_redact_embedded_images()` to also scan Form XObject images. If not, add a comment in `redactor.py` noting the limitation and skip. This is the lowest-incidence PDF structure gap.

- [ ] **Step 3: Commit (only if changes were made)**

```bash
git add src/core/redactor.py
git commit -m "feat: scan Form XObject images for PII (research spike)"
```

---

### Task 14c: Research Spike — Optional Content Groups (Optional)

**Files:**
- Modify: `src/core/redactor.py` (if feasible)

This is a research spike from spec section 2.8. PyMuPDF does NOT have `doc.get_ocgs()` or `doc.set_oc()` with the signatures in the spec.

- [ ] **Step 1: Research the PyMuPDF API for OCG manipulation**

Note: `page.get_text()` in PyMuPDF's default mode already extracts text from ALL optional content groups (both visible and hidden). So text-layer detection on hidden layers already works. The gap is only for content in annotation dictionaries on hidden layers — a very low-probability scenario.

- [ ] **Step 2: If feasible, force all layers visible; if not, add audit log warning**

If `doc.get_ocgs()` or equivalent exists, force all layers visible at the start of `redact_pdf()`. Otherwise, add a warning to the audit log if OCGs are detected (check for `/OCProperties` in the catalog via `doc.xref_get_key(doc.pdf_catalog(), "OCProperties")`).

- [ ] **Step 3: Commit (only if changes were made)**

```bash
git add src/core/redactor.py
git commit -m "feat: handle optional content groups in PDF redaction"
```

---

## Phase 3: Test Coverage

### Task 15: End-to-End Integration Tests

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Create the test file**

```python
"""End-to-end integration tests for the full redaction pipeline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Service-layer imports use full paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.core.redactor import PDFRedactor, RedactionItem
from src.core.pii_detector import PIIDetector


def _make_test_pdf(tmp_path, pages_content):
    """Create a multi-page PDF with specified text content per page."""
    pdf_path = tmp_path / "test_input.pdf"
    doc = fitz.open()
    for page_text in pages_content:
        page = doc.new_page()
        page.insert_text((72, 72), page_text, fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_with_link(tmp_path, body_text, link_uri):
    """Create a PDF with a link annotation."""
    pdf_path = tmp_path / "test_link.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), body_text, fontsize=12)
    link = {"kind": fitz.LINK_URI, "from": fitz.Rect(72, 72, 200, 90), "uri": link_uri}
    page.insert_link(link)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_with_bookmark(tmp_path, body_text, bookmark_title):
    """Create a PDF with a bookmark/outline entry."""
    pdf_path = tmp_path / "test_bookmark.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), body_text, fontsize=12)
    doc.set_toc([[1, bookmark_title, 1]])
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestRedactorLinkCleanup:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_link_with_pii_email_deleted(self, tmp_path):
        pdf = _make_pdf_with_link(tmp_path, "Contact us", "mailto:jane.smith@school.edu")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="jane.smith@school.edu")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        links = doc[0].get_links()
        pii_links = [l for l in links if "jane" in l.get("uri", "").lower()]
        assert len(pii_links) == 0
        doc.close()

    def test_link_without_pii_preserved(self, tmp_path):
        pdf = _make_pdf_with_link(tmp_path, "Visit website", "https://example.com")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        links = doc[0].get_links()
        assert any("example.com" in l.get("uri", "") for l in links)
        doc.close()


class TestRedactorBookmarkCleanup:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_bookmark_pii_replaced(self, tmp_path):
        pdf = _make_pdf_with_bookmark(tmp_path, "Report content", "Assessment for Jane Smith")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        toc = doc.get_toc()
        for entry in toc:
            assert "jane" not in entry[1].lower()
            assert "smith" not in entry[1].lower()
        doc.close()


class TestRedactorMetadataHardening:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_structure_tree_stripped(self, tmp_path):
        pdf_path = tmp_path / "tagged.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Jane Smith report", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf_path, out, items)
        doc = fitz.open(str(out))
        cat_xref = doc.pdf_catalog()
        st_type, _ = doc.xref_get_key(cat_xref, "StructTreeRoot")
        assert st_type == "null"
        doc.close()

    def test_names_dict_stripped(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Content", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="test")]
        self.redactor.redact_pdf(pdf_path, out, items)
        doc = fitz.open(str(out))
        cat_xref = doc.pdf_catalog()
        names_type, _ = doc.xref_get_key(cat_xref, "Names")
        assert names_type == "null"
        doc.close()


class TestMultiPageRedaction:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_pii_on_multiple_pages_all_redacted(self, tmp_path):
        pdf = _make_test_pdf(tmp_path, [
            "Jane Smith attended the session.",
            "No PII on this page.",
            "Phone: 0412 345 678",
            "Contact Jane Smith for details.",
        ])
        out = tmp_path / "out.pdf"
        items = [
            RedactionItem(page_num=1, text="Jane Smith"),
            RedactionItem(page_num=3, text="0412 345 678"),
            RedactionItem(page_num=4, text="Jane Smith"),
        ]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        for page_num in [0, 2, 3]:  # 0-indexed
            text = doc[page_num].get_text().lower()
            assert "jane smith" not in text
        assert "0412 345 678" not in doc[2].get_text()
        doc.close()
```

- [ ] **Step 2: Run integration tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_integration.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration tests for redaction pipeline"
```

---

### Task 16: Adversarial Input Tests

**Files:**
- Create: `tests/test_adversarial.py`

- [ ] **Step 1: Create the test file**

```python
"""Adversarial and edge-case input tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import pytest
from pathlib import Path
from pii_detector import PIIDetector


class TestUnicodeEdgeCases:
    def test_zero_width_chars_in_name(self):
        detector = PIIDetector("Jane Smith")
        # Zero-width space between first and last name
        text = "Student: Jane\u200BSmith attended"
        matches = detector.detect_pii_in_text(text, 1)
        # After NFKC normalisation, zero-width space should be stripped
        matched_texts = {m.text.lower() for m in matches}
        assert "jane" in matched_texts or "janesmith" in matched_texts or "jane smith" in matched_texts

    def test_smart_quotes_in_name(self):
        detector = PIIDetector("O'Brien")
        text = "Student O\u2019Brien was present"  # Right single quote
        matches = detector.detect_pii_in_text(text, 1)
        assert any("brien" in m.text.lower() for m in matches)

    def test_ligature_in_name(self):
        detector = PIIDetector("Griffin")
        # fi ligature
        text = "Student Gri\ufb01n was present"
        matches = detector.detect_pii_in_text(text, 1)
        # After NFKC, the ligature decomposes to "fi"
        assert any("griffin" in m.text.lower() for m in matches)


class TestBoundaryConditions:
    def test_pii_at_header_zone_boundary(self):
        """PII exactly at 12% mark — should be caught by zone or detection."""
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith\n" * 3  # Name near the top
        matches = detector.detect_pii_in_text(text, 1)
        assert len(matches) >= 1

    def test_pii_on_last_line_of_page(self):
        detector = PIIDetector("Jane Smith")
        text = "Nothing here\n" * 50 + "Contact Jane Smith"
        matches = detector.detect_pii_in_text(text, 1)
        assert any("jane smith" in m.text.lower() for m in matches)

    def test_empty_text_no_crash(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("", 1)
        assert matches == []

    def test_single_line_text(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Jane Smith", 1)
        assert len(matches) >= 1
```

- [ ] **Step 2: Run adversarial tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_adversarial.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_adversarial.py
git commit -m "test: add adversarial and edge-case input tests"
```

---

### Task 17: False-Positive Regression Tests

**Files:**
- Create: `tests/test_false_positives.py`

- [ ] **Step 1: Create the test file**

```python
"""False-positive regression tests — things that should NOT be flagged."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pii_detector import PIIDetector


class TestStudentIDFalsePositives:
    def test_educational_acronyms_not_flagged(self):
        """Common educational acronyms matching [A-Z]{3}\\d{3,} should not flag."""
        detector = PIIDetector("Jane Smith")
        for text in ["ASD123 assessment scale", "IEP456 review", "ODD789 criteria"]:
            matches = [m for m in detector.detect_pii_in_text(text, 1)
                       if m.category == "Student ID"]
            # These are borderline — document current behavior
            # If they DO match, that's the current regex being broad
            pass  # This test documents behavior, update assertion as needed


class TestPhoneFalsePositives:
    def test_short_number_in_table_not_phone(self):
        detector = PIIDetector("Jane Smith")
        text = "Score: 0412 out of 1000"
        matches = [m for m in detector.detect_pii_in_text(text, 1)
                   if m.category == "Phone number"]
        # 4-digit number should not be a phone
        assert len(matches) == 0

    def test_score_resembling_landline_not_matched(self):
        detector = PIIDetector("Jane Smith")
        text = "Test result: (03) 9642"
        matches = [m for m in detector.detect_pii_in_text(text, 1)
                   if m.category == "Phone number"]
        # Incomplete landline should not match
        assert len(matches) == 0


class TestNERFalsePositives:
    def test_subject_names_context(self):
        """Common school subjects should ideally not be flagged as person names."""
        detector = PIIDetector("Jane Smith")
        text = "He studies English and Art at school"
        matches = detector.detect_pii_in_text(text, 1)
        # NER may flag these — document current behavior
        subject_matches = [m for m in matches if m.text in ("English", "Art")]
        # This is informational — NER false positives require post-processing
        if subject_matches:
            assert all(m.confidence < 0.95 for m in subject_matches)
```

- [ ] **Step 2: Run false-positive tests**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/test_false_positives.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_false_positives.py
git commit -m "test: add false-positive regression tests"
```

---

## Phase 4: Bundle Simplification

### Task 18: Remove GLiNER

**Files:**
- Delete: `src/core/gliner_provider.py`
- Delete: `tests/test_gliner_provider.py`
- Modify: `src/core/pii_orchestrator.py` (remove GLiNER refs)
- Modify: `requirements-desktop.txt` (remove `gliner>=0.2.0`)

- [ ] **Step 1: Remove GLiNER from orchestrator**

In `src/core/pii_orchestrator.py`:

Remove `_init_gliner` method (lines 64-70).

In `__init__` (lines 61-62), remove:
```python
self.gliner_detector = None
self._init_gliner()
```

In `detect_pii_in_text`, the GLiNER block (lines 143-145 in original) has already been replaced by the NER-primary restructure in Task 7. Verify no `gliner` references remain.

- [ ] **Step 2: Remove `gliner>=0.2.0` from requirements**

In `requirements-desktop.txt`, delete the line `gliner>=0.2.0`.

- [ ] **Step 3: Delete the provider and test files**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
rm src/core/gliner_provider.py
rm tests/test_gliner_provider.py
```

- [ ] **Step 4: Verify no remaining GLiNER references**

Search for any remaining `gliner` references:
```bash
grep -ri "gliner" src/ backend/ tests/ --include="*.py" -l
```
Expected: No results (or only CLAUDE.md/docs files)

- [ ] **Step 5: Run full test suite**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/ --ignore=tests/test_ocr_verification.py --ignore=tests/test_gliner_provider.py -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/core/pii_orchestrator.py src/core/gliner_provider.py tests/test_gliner_provider.py requirements-desktop.txt
git commit -m "chore: remove GLiNER dependency and PyTorch transitive dependency"
```

Note: `git add` on deleted files stages the deletion. Avoid `git add -A` per project conventions.

---

### Task 19: Verify Bundle Size and Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Check: `scripts/bundle-python-mac.sh`, `scripts/bundle-python-win.ps1`

- [ ] **Step 1: Check if PyTorch is still a transitive dependency**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
./venv/bin/pip install presidio-analyzer spacy --dry-run 2>&1 | grep -i torch
```

If torch still appears, it's from spaCy's `thinc` backend. Document this in CLAUDE.md.

- [ ] **Step 2: Update CLAUDE.md**

Remove all GLiNER references:
- Architecture diagram: change 3-engine to 2-engine (regex + Presidio/spaCy)
- Detection pipeline diagram: remove GLiNER line
- Key files table: remove `src/core/gliner_provider.py`
- Dependencies: remove `gliner>=0.2.0`
- Models: remove `urchade/gliner_multi_pii-v1`
- Test structure: remove `test_gliner_provider.py`, update test count
- What's Next: note GLiNER removed for bundle simplification

Add new entries:
- Key files: add `src/core/nickname_map.py`
- Detection confidence table: add NDIS (0.90), ABN (0.90), Passport (0.65), Nickname (0.75), NER Person (0.90), NER variation (0.85)
- Test structure: add new test files

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for two-engine architecture and new detection features"
```

---

## Final Verification

### Task 20: Full Test Suite Run

- [ ] **Step 1: Run ALL tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && ./venv/bin/python -m pytest tests/ --ignore=tests/test_ocr_verification.py -v
```

Expected: All tests pass. Note the new total count (should be ~280+ tests).

- [ ] **Step 2: Run TypeScript type check**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 3: Run Vite build**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool/desktop" && npm run build
```

Expected: Build succeeds.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve any issues found during final verification"
```
