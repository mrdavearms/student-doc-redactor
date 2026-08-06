# Plan A: Detection & Verification Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close five empirically-confirmed PII detection gaps (real-format Centrelink CRNs, +61 mobiles, common DOB formats, prose addresses, unit prefixes), fix the false-quarantine verification bug, scan embedded images on every page without wrecking runtime, and remove two review-list noise generators.

**Architecture:** All changes are in the Python engine layer (`src/core/`). Detection pattern changes are mirrored in both engines — the regex detector (`pii_detector.py`) and the Presidio recognizers (`presidio_recognizers.py`) — because both run and dedup merges them. Verification changes live in `redactor.py`. No API, service-layer, or frontend changes.

**Tech Stack:** Python 3.13, pytest, PyMuPDF (`fitz`), Presidio/spaCy, PIL, pytesseract (mocked in tests where possible).

> **Revision note (post senior review):** This plan was reviewed against the real codebase by applying all changes to a scratch copy and running the full suite. Eight findings changed the design and are marked **[REV]** inline with the evidence. One was a **privacy blocker** (REV-6). Do not "simplify" any `[REV]` decision back to the obvious-looking version — each was measured against real documents.

## Global Constraints

- **Start with `git checkout test`** — repo policy is `test` → verify → merge to `main`, and HEAD is currently `main`. Do NOT push or merge without the user's explicit go-ahead.
- Run tests with `venv/bin/python3.13 -m pytest` — NEVER `venv/bin/pytest` (broken shebang).
- Baseline is **316 tests passing** in ~40s. All must stay green after every task.
- **Test-file conventions:** `tests/test_pii_detector.py` classes use `setup_method` plus a private helper (e.g. `self._crn_matches(line)` calling the specific `_detect_*` method). The snippets below construct `PIIDetector(...)` inline and call the public `detect_pii_in_text` — both styles run green, but before writing each test, read the target class and match its local style. This applies to Tasks 1, 2, 3 and 4.
- Conventional-commit subjects (`fix(scope): subject`) — release notes are generated from them.
- `PIIMatch.confidence` is a float 0.0–1.0. New medium-confidence matches use `0.65`.
- Do not add new pip dependencies.
- Working directory: the repo root `/Users/davidarmstrong/Antigravity/redaction tool` (quote the path — it contains a space).

---

### Task 1: Real-format Centrelink CRN detection

Real Centrelink CRNs are **9 digits followed by a letter** (e.g. `123 456 789A` or `123456789A`). The current pattern `\b[A-Z0-9]{9}\b` only matches exactly-9-character tokens, so it misses both real formats. Keep the old alternative for older documents that print the CRN without its check letter.

**Verified:** alternation order is correct (the longest real-format branch wins), `\b` behaves around the trailing letter, legacy `ABC123456` still matches, and no new false positives appear against Medicare/phone/date formats on a CRN line.

**Files:**
- Modify: `src/core/pii_detector.py:140` (CRN_PATTERN)
- Modify: `src/core/presidio_recognizers.py:116` (CentrelinkCRNRecognizer pattern)
- Test: `tests/test_pii_detector.py` (CRN test class)
- Test: `tests/test_presidio_recognizers.py` (CRN recognizer tests)

**Interfaces:**
- Consumes: nothing.
- Produces: `PIIDetector.CRN_PATTERN` (class attribute, regex string). Category stays `'Centrelink CRN'`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pii_detector.py`, find the CRN test class (search for `Centrelink`) and add, matching that class's local construction style:

```python
    def test_crn_real_format_spaced(self):
        """Real CRNs are 9 digits + a letter: '123 456 789A'."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("CRN: 123 456 789A", page_num=1)
        crn = [m for m in matches if m.category == "Centrelink CRN"]
        assert any(m.text == "123 456 789A" for m in crn)

    def test_crn_real_format_compact(self):
        """Compact real CRN: '123456789A' (10 chars, digit run + letter)."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("CRN: 123456789A", page_num=1)
        crn = [m for m in matches if m.category == "Centrelink CRN"]
        assert any(m.text == "123456789A" for m in crn)

    def test_crn_letter_format_requires_keyword(self):
        """Without a CRN keyword on the line, the number is not flagged."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Reference 123 456 789A", page_num=1)
        crn = [m for m in matches if m.category == "Centrelink CRN"]
        assert len(crn) == 0
```

In `tests/test_presidio_recognizers.py`, add to the CRN recognizer class (these recognizers are called directly via `.analyze(text, entities)`):

```python
    def test_detects_real_format_crn_with_letter(self):
        recognizer = CentrelinkCRNRecognizer()
        results = recognizer.analyze("CRN: 123 456 789A", entities=["AU_CRN"])
        assert len(results) >= 1

    def test_detects_compact_real_format_crn(self):
        recognizer = CentrelinkCRNRecognizer()
        results = recognizer.analyze("CRN: 123456789A", entities=["AU_CRN"])
        assert len(results) >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py -k crn_real -v && venv/bin/python3.13 -m pytest tests/test_presidio_recognizers.py -k real_format -v
```

Expected: the new tests FAIL (no matches found).

- [ ] **Step 3: Update both patterns**

In `src/core/pii_detector.py`, replace:

```python
    # Centrelink CRN pattern
    CRN_PATTERN = r'\b[A-Z0-9]{9}\b'
```

with:

```python
    # Centrelink CRN pattern.
    # Real CRNs are 9 digits + a letter ("123 456 789A" / "123456789A").
    # The 9-char alphanumeric alternative is kept for older docs that print
    # the CRN without its check letter.
    CRN_PATTERN = r'\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}[A-Za-z]\b|\b[A-Z0-9]{9}\b'
```

In `src/core/presidio_recognizers.py`, inside `CentrelinkCRNRecognizer.analyze`, replace:

```python
        pattern = re.compile(r"\b[A-Z0-9]{9}\b")
```

with:

```python
        pattern = re.compile(r"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}[A-Za-z]\b|\b[A-Z0-9]{9}\b")
```

- [ ] **Step 4: Run both touched files' full suites**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py tests/test_presidio_recognizers.py -v
```

Expected: ALL PASS (including all pre-existing CRN tests and all 18 Presidio tests).

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_detector.py src/core/presidio_recognizers.py tests/test_pii_detector.py tests/test_presidio_recognizers.py
git commit -m "fix(detector): detect real-format Centrelink CRNs (9 digits + letter)"
```

---

### Task 2: Phone formats — +61 mobiles and dotted separators

`+61 412 345 678` (the standard international mobile format, spaced) is completely missed because the only `+61` pattern uses landline 4-4 digit grouping. Dotted separators (`02.6056.1234`) are also missed.

> **[REV-1] The compact form already works — don't write a dead TDD test.** Verified: `'+61412345678'` already matches the existing `\+61[\s\-]*[2-478][\s\-]*\d{4}[\s\-]*\d{4}` pattern, while `'+61 412 345 678'` genuinely returns `[]`. A test asserting the compact form fails-first would pass before the change and prove nothing. Only the spaced form is a real gap.

> **[REV-2] Guard the dotted patterns against digit runs.** Adding `\.` as a separator creates a small new false-positive class (verified: `'Version 2.04.1234.5678 build'` → matches `04.1234.5678`). Zero hits on the real sample corpus, but a `(?<!\d)` / `(?!\d)` guard costs nothing. The existing phone patterns have no boundary anchors at all — this adds them only to the new dotted variants rather than re-architecting pre-existing behaviour.

**Files:**
- Modify: `src/core/pii_detector.py:122-128` (PHONE_PATTERNS)
- Modify: `src/core/presidio_recognizers.py:14-20` (AustralianPhoneRecognizer.PATTERNS)
- Test: `tests/test_pii_detector.py` (phone test class)
- Test: `tests/test_presidio_recognizers.py` (phone recognizer tests)

**Interfaces:**
- Consumes: nothing.
- Produces: `PIIDetector.PHONE_PATTERNS` (list of regex strings). Category stays `'Phone number'`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pii_detector.py` phone test class:

```python
    def test_mobile_international_format_spaced(self):
        """'+61 412 345 678' — the standard intl mobile format."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Contact: +61 412 345 678", page_num=1)
        phones = [m for m in matches if m.category == "Phone number"]
        assert any("412 345 678" in m.text for m in phones)

    def test_landline_dotted_separators(self):
        """'02.6056.1234' — dot-separated landline."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Ph: 02.6056.1234", page_num=1)
        phones = [m for m in matches if m.category == "Phone number"]
        assert any("6056" in m.text for m in phones)

    def test_mobile_dotted_separators(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Mob: 0412.345.678", page_num=1)
        phones = [m for m in matches if m.category == "Phone number"]
        assert len(phones) >= 1

    def test_dotted_pattern_does_not_match_inside_a_longer_digit_run(self):
        """Version/score strings must not become phone numbers."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Version 2.04.1234.5678 build", page_num=1)
        phones = [m for m in matches if m.category == "Phone number"]
        assert len(phones) == 0
```

In `tests/test_presidio_recognizers.py` phone recognizer class:

```python
    def test_detects_intl_mobile_format(self):
        recognizer = AustralianPhoneRecognizer()
        results = recognizer.analyze("+61 412 345 678", entities=["AU_PHONE"])
        assert len(results) >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py -k "international or dotted" -v && venv/bin/python3.13 -m pytest tests/test_presidio_recognizers.py -k intl_mobile -v
```

Expected: the three format tests FAIL; `test_dotted_pattern_does_not_match_inside_a_longer_digit_run` passes today (regression guard for the new code).

- [ ] **Step 3: Update both pattern lists**

In `src/core/pii_detector.py`, replace the whole `PHONE_PATTERNS` list with:

```python
    # Australian phone number patterns.
    # The dotted variants carry (?<!\d) / (?!\d) guards so they cannot match
    # inside a longer digit run (e.g. a version string "2.04.1234.5678").
    PHONE_PATTERNS = [
        r'\+61[\s\-]*4\d{2}[\s\-]*\d{3}[\s\-]*\d{3}',   # +61 412 345 678 (intl mobile)
        r'\+61[\s\-]*[2-478][\s\-]*\d{4}[\s\-]*\d{4}',  # +61 2 1234 5678
        r'0[2-478][\s\-]*\d{4}[\s\-]*\d{4}',            # 02 1234 5678
        r'(?<!\d)0[2-478]\.\d{4}\.\d{4}(?!\d)',         # 02.1234.5678
        r'\(0[2-478]\)[\s\-]*\d{4}[\s\-]*\d{4}',        # (02) 1234 5678
        r'04\d{2}[\s\-]*\d{3}[\s\-]*\d{3}',             # 0412 345 678
        r'(?<!\d)04\d{2}\.\d{3}\.\d{3}(?!\d)',          # 0412.345.678
        r'04\d{8}',                                      # 0412345678
    ]
```

In `src/core/presidio_recognizers.py`, replace `AustralianPhoneRecognizer.PATTERNS` with:

```python
    PATTERNS = [
        Pattern("AU_PHONE_INTL_MOBILE", r"\+61\s*4\d{2}\s*\d{3}\s*\d{3}", 0.85),
        Pattern("AU_PHONE_INTL", r"\+61\s*[2-478]\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_LANDLINE", r"0[2-478]\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_LANDLINE_DOTTED", r"(?<!\d)0[2-478]\.\d{4}\.\d{4}(?!\d)", 0.85),
        Pattern("AU_PHONE_PARENS", r"\(0[2-478]\)\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_MOBILE_SPACED", r"04\d{2}\s*\d{3}\s*\d{3}", 0.85),
        Pattern("AU_PHONE_MOBILE_DOTTED", r"(?<!\d)04\d{2}\.\d{3}\.\d{3}(?!\d)", 0.85),
        Pattern("AU_PHONE_MOBILE_NOSPACE", r"04\d{8}", 0.80),
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py tests/test_presidio_recognizers.py tests/test_false_positives.py -v
```

Expected: ALL PASS. If a false-positive test fails, the new separator classes are over-matching — tighten them rather than weakening the test.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_detector.py src/core/presidio_recognizers.py tests/test_pii_detector.py tests/test_presidio_recognizers.py
git commit -m "fix(detector): detect +61 mobile and dot-separated phone formats"
```

---

### Task 3: DOB date formats — dots, 2-digit years, ordinals, month-first

`DOB: 12.03.2015`, `DOB: 12/3/15`, `Date of Birth: 12th March 2015`, and `Born: March 12, 2015` are all missed. These only fire when a DOB label is on the line (or the line above), so false-positive risk from the broader patterns is minimal.

**Verified:** all five plan examples match; `_MONTHS` composes correctly as a class-body attribute in both files (it is a non-capturing group, so there is no alternation-precedence bug); every existing DOB test that asserts `len(matches) == 1` still passes; the label guard still blocks `"Review meeting held 12.03.2025"`. This task also finds a genuinely missed DOB (`20/07/13`) in the real sample corpus.

**Files:**
- Modify: `src/core/pii_detector.py:164-169` (DATE_PATTERNS + new `_MONTHS` class attr)
- Modify: `src/core/presidio_recognizers.py:139-143` (DateOfBirthRecognizer.DATE_PATTERNS)
- Test: `tests/test_pii_detector.py` (DOB test class)
- Test: `tests/test_presidio_recognizers.py` (DOB recognizer tests)

**Interfaces:**
- Consumes: nothing.
- Produces: `PIIDetector._MONTHS` (regex fragment string), expanded `PIIDetector.DATE_PATTERNS`. Category stays `'Date of birth'`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pii_detector.py` DOB test class:

```python
    def test_dob_dotted_separators(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("DOB: 12.03.2015", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert any(m.text == "12.03.2015" for m in dob)

    def test_dob_two_digit_year(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("DOB: 12/3/15", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert any(m.text == "12/3/15" for m in dob)

    def test_dob_ordinal_day(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Date of Birth: 12th March 2015", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert any("March 2015" in m.text for m in dob)

    def test_dob_ordinal_with_of(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Born: 3rd of June 2014", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert any("June 2014" in m.text for m in dob)

    def test_dob_month_first_us_style(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Born: March 12, 2015", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert any("March 12" in m.text for m in dob)

    def test_standalone_dotted_date_without_label_not_flagged(self):
        """Dotted dates still require a DOB label — review dates stay unflagged."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Review meeting held 12.03.2025", page_num=1)
        dob = [m for m in matches if m.category == "Date of birth"]
        assert len(dob) == 0
```

In `tests/test_presidio_recognizers.py` DOB recognizer class:

```python
    def test_detects_dotted_dob(self):
        recognizer = DateOfBirthRecognizer()
        results = recognizer.analyze("DOB: 12.03.2015", entities=["AU_DOB"])
        assert len(results) >= 1

    def test_detects_ordinal_dob(self):
        recognizer = DateOfBirthRecognizer()
        results = recognizer.analyze("Date of Birth: 12th March 2015", entities=["AU_DOB"])
        assert len(results) >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py -k "dob_dotted or two_digit_year or ordinal or month_first or standalone_dotted" -v && venv/bin/python3.13 -m pytest tests/test_presidio_recognizers.py -k "dotted_dob or ordinal_dob" -v
```

Expected: all new tests FAIL except `test_standalone_dotted_date_without_label_not_flagged` (regression guard).

- [ ] **Step 3: Update both pattern lists**

In `src/core/pii_detector.py`, replace the `DATE_PATTERNS` list with:

```python
    # Month-name fragment shared by the date patterns below
    _MONTHS = (
        r'(?:January|February|March|April|May|June|July|August|September|'
        r'October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    )

    # Date patterns (various formats). Only flagged as DOB when a DOB label
    # is present on the same line (or the line above) — see _detect_dob().
    DATE_PATTERNS = [
        r'\d{1,2}/\d{1,2}/\d{2,4}',   # DD/MM/YYYY and DD/M/YY
        r'\d{1,2}-\d{1,2}-\d{2,4}',   # DD-MM-YYYY
        r'\d{1,2}\.\d{1,2}\.\d{2,4}', # DD.MM.YYYY
        r'\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?' + _MONTHS + r'\s+\d{2,4}',  # 12th (of) March 2015
        _MONTHS + r'\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}',  # March 12, 2015
    ]
```

In `src/core/presidio_recognizers.py`, replace `DateOfBirthRecognizer.DATE_PATTERNS` with (repeated in full — the two engines' lists must stay in sync):

```python
    _MONTHS = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )
    DATE_PATTERNS = [
        r"\d{1,2}/\d{1,2}/\d{2,4}",
        r"\d{1,2}-\d{1,2}-\d{2,4}",
        r"\d{1,2}\.\d{1,2}\.\d{2,4}",
        r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTHS + r"\s+\d{2,4}",
        _MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}",
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py tests/test_presidio_recognizers.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_detector.py src/core/presidio_recognizers.py tests/test_pii_detector.py tests/test_presidio_recognizers.py
git commit -m "fix(detector): detect dotted, 2-digit-year, ordinal and month-first DOB formats"
```

---

### Task 4: Prose addresses and unit prefixes

Two gaps: (a) "Sarah lives at 12 Bakers Lane with her mother." — no state+postcode, so nothing matches; (b) "Unit 3/45 High Street, Wodonga VIC 3690" — matches from "45", leaving "Unit 3/" visible after redaction. Fix: an optional unit prefix on the full pattern, plus a new **medium-confidence street-only pattern**.

> **[REV-3] The naive street-only pattern has a real false-positive surface — use the tightened three-class version below.** A simple "number + Title-Case words + street type" pattern fires on ordinary report language, because `STREET_TYPES` contains ambiguous tokens (`Dr, St, Place, Court, Close, Way, Rise, Grove`). Measured false positives: `'Seen by 2 Specialists Dr Jones'` → `2 Specialists Dr`; `'Sarah made 12 Point Rise in reading fluency'` → `12 Point Rise`; `'Working at 2 Year Level Place Value'` → `2 Year Level Place`; `'He completed 3 Tasks St Andrews campus'` → `3 Tasks St`. This matters more than usual because the store auto-selects every match `true` and there is an "Accept All & Continue" fast path — a false positive here gets **redacted without the teacher noticing**, destroying report content.
>
> The verified fix splits street types into two classes: unambiguous nouns (`Street`, `Road`, `Lane`, …) match freely; abbreviations and ambiguous common nouns (`St`, `Dr`, `Court`, `Place`, `Rise`, …) must be followed by a comma, full stop, or end-of-line. Leading words are capped at two, and the second may not be a stop-word. Measured on this exact pattern: **9/9 genuine addresses matched** (including `12 The Esplanade` and `45 Old Sydney Road`), **11/11 false positives rejected**, and zero street-only hits across every page of the real `sample/` corpus.

> **[REV-4] This task fixes an existing test that the naive pattern breaks.** `tests/test_pii_detector.py::TestAddressDetection::test_text_without_state_not_matched` asserts that `"123 Some Place without any proper suburb here"` yields zero matches. `Place` is capitalised and in `STREET_TYPES`, so the naive pattern breaks it. The tightened pattern requires `Place` to be followed by `,`/`.`/end-of-line, so the existing test **passes unchanged** — as it should, since "Some Place" is not an address.

> **[REV-5] Street-only matches stay selected-by-default.** The alternative (defaulting 0.65 Address matches to unselected) was considered and rejected: it is inconsistent with the tool's fail-safe posture ("when in doubt, redact"), and with the tightened pattern there are no demonstrated false positives to protect against. The user can always deselect.

**Files:**
- Modify: `src/core/pii_detector.py:133-134` (ADDRESS_PATTERN → four class attrs) and `:349-363` (`_detect_addresses`)
- Modify: `src/core/presidio_recognizers.py:34-40` (AustralianAddressRecognizer pattern — unit prefix only)
- Test: `tests/test_pii_detector.py` (address test class)
- Test: `tests/test_false_positives.py` (permanent home for the FP cases)

**Interfaces:**
- Consumes: nothing.
- Produces: `PIIDetector.STREET_TYPES`, `PIIDetector.UNIT_PREFIX`, `PIIDetector.ADDRESS_PATTERN`, `PIIDetector.STREET_ONLY_PATTERN` (all regex-string class attrs). Street-only matches use category `'Address'` at confidence `0.65`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pii_detector.py` address test class:

```python
    def test_address_with_unit_prefix(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Address: Unit 3/45 High Street, Wodonga VIC 3690", page_num=1)
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text.startswith("Unit 3/45") for m in addr)

    def test_address_with_bare_unit_slash_prefix(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Lives at 3/45 High Street, Wodonga VIC 3690", page_num=1)
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text.startswith("3/45") for m in addr)

    def test_street_only_address_in_prose(self):
        """Addresses without state+postcode get a medium-confidence match."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Sarah lives at 12 Bakers Lane with her mother.", page_num=1)
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text == "12 Bakers Lane" for m in addr)
        assert all(m.confidence == 0.65 for m in addr)

    def test_street_only_ambiguous_type_requires_terminator(self):
        """'5 Rosewood Court,' is an address; '2 Year Level Place Value' is not."""
        detector = PIIDetector("Joe Bloggs")
        hit = detector.detect_pii_in_text(
            "The family moved to 5 Rosewood Court, Wodonga", page_num=1)
        assert any(m.category == "Address" and m.text == "5 Rosewood Court" for m in hit)

        miss = detector.detect_pii_in_text(
            "Working at 2 Year Level Place Value", page_num=1)
        assert not [m for m in miss if m.category == "Address"]

    def test_street_only_keeps_the_esplanade_style_names(self):
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Lives at 12 The Esplanade, Torquay", page_num=1)
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text == "12 The Esplanade" for m in addr)

    def test_full_address_not_double_reported(self):
        """A full-format address must yield ONE match, not full + street-only."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Address: 12 Bakers Lane, Wodonga VIC 3690", page_num=1)
        addr = [m for m in matches if m.category == "Address"]
        assert len(addr) == 1
        assert addr[0].confidence == 0.95
```

In `tests/test_false_positives.py`, add a permanent regression class (this file is the right home and the plan would otherwise never add to it):

```python
class TestStreetOnlyAddressFalsePositives:
    """Report language that must never be flagged as an address."""

    NON_ADDRESSES = [
        "Seen by 2 Specialists Dr Jones on Tuesday",
        "Assessment completed over 3 Sessions Dr Patel today",
        "Sarah made 12 Point Rise in reading fluency",
        "Attends 2 Days Way Out program",
        "He completed 3 Tasks St Andrews campus",
        "Referred to 1 Session Close observation",
        "Working at 2 Year Level Place Value",
        "Scored 8 On The Rise",
        "She scored 12 goals in the season.",
        "Completed 3 Sessions Term 2.",
        "Achieved 4 Levels Above Expected.",
        "123 Some Place without any proper suburb here",
    ]

    def test_report_language_not_flagged_as_address(self):
        detector = PIIDetector("Joe Bloggs")
        for line in self.NON_ADDRESSES:
            matches = detector.detect_pii_in_text(line, page_num=1)
            addr = [m for m in matches if m.category == "Address"]
            assert not addr, f"False positive on {line!r}: {[m.text for m in addr]}"
```

(Check the imports at the top of `test_false_positives.py` and add `PIIDetector` if it is not already imported.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py -k "unit_prefix or unit_slash or street_only or esplanade or double_reported" tests/test_false_positives.py -v
```

Expected: the unit-prefix and street-only tests FAIL; `test_full_address_not_double_reported` and the false-positive class pass today (regression guards).

- [ ] **Step 3: Implement the patterns and detection method**

In `src/core/pii_detector.py`, replace the single `ADDRESS_PATTERN` line with:

```python
    # Street-type suffixes for the FULL address pattern (anchored by state+postcode,
    # so ambiguity is not a risk there).
    STREET_TYPES = (
        r'Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|'
        r'Crescent|Cres|Boulevard|Blvd|Terrace|Tce|Close|Cl|Grove|Gr|Highway|Hwy|'
        r'Parade|Pde|Circuit|Cct|Loop|Rise|Vale|Mews|Esplanade|Esp'
    )

    # Optional unit/flat prefix: "Unit 3/", "Flat 2 ", "3/"
    UNIT_PREFIX = r'(?:(?:Unit|Flat|Apt|Apartment)\s+)?(?:\d+[A-Za-z]?\s*/\s*)?'

    # Full Australian address: needs street type + suburb + state + postcode
    ADDRESS_PATTERN = (
        UNIT_PREFIX
        + r'\d+\s+[A-Za-z\s]+(?:' + STREET_TYPES + r'),?\s+[A-Za-z\s]+,?\s+'
        + r'(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT|Victoria|New South Wales|Queensland|'
        + r'South Australia|Western Australia|Tasmania|Northern Territory|'
        + r'Australian Capital Territory)\s+\d{4}'
    )

    # ── Street-only address (no state/postcode) — medium confidence ──
    # Deliberately case-SENSITIVE, and split into two street-type classes:
    #   _STREET_FREE     unambiguous nouns — may be followed by anything
    #   _STREET_ANCHORED abbreviations + words that are common English nouns
    #                    ("Court", "Place", "Rise", "Dr") — must be followed by
    #                    a comma, full stop, or end of line.
    # Without that split, report language like "2 Specialists Dr Jones" and
    # "12 Point Rise in reading fluency" is flagged as an address and silently
    # redacted via the Accept-All path.
    _STREET_FREE = (
        r'Street|Road|Avenue|Drive|Lane|Crescent|Boulevard|Terrace|Highway|'
        r'Parade|Circuit|Esplanade|Mews'
    )
    _STREET_ANCHORED = (
        r'St|Rd|Ave|Dr|Ln|Cres|Blvd|Tce|Hwy|Pde|Cct|'
        r'Court|Place|Close|Grove|Way|Rise|Vale|Loop|Ct|Pl|Cl|Gr'
    )
    # At most two leading capitalised words. The FIRST may be a stop-word so
    # genuine names like "12 The Esplanade" work; the SECOND may not, which is
    # what rejects "8 On The Rise".
    _STREET_LEAD = (
        r'\d+\s+[A-Z][A-Za-z]*'
        r'(?:\s+(?!(?:The|On|In|At|Of|And|To|For|A|An)\b)[A-Z][A-Za-z]*){0,1}\s+'
    )
    STREET_ONLY_PATTERN = (
        r'\b' + UNIT_PREFIX + _STREET_LEAD + r'(?:' + _STREET_FREE + r')\b'
        + r'|\b' + UNIT_PREFIX + _STREET_LEAD + r'(?:' + _STREET_ANCHORED + r')(?=[,.]|\s*$)'
    )
```

Replace the whole `_detect_addresses` method with:

```python
    def _detect_addresses(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
        """Detect Australian addresses — full (state+postcode) and street-only."""
        matches = []
        full_spans = []
        pattern = re.compile(self.ADDRESS_PATTERN, re.IGNORECASE)
        for match in pattern.finditer(line):
            full_spans.append((match.start(), match.end()))
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Address',
                confidence=0.95,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))

        # Street-only fallback (no state/postcode) — medium confidence.
        # NOT case-insensitive: street names must be capitalised.
        street_pattern = re.compile(self.STREET_ONLY_PATTERN)
        for match in street_pattern.finditer(line):
            if any(match.start() >= s and match.end() <= e for s, e in full_spans):
                continue  # Already covered by a full address match
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Address',
                confidence=0.65,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches
```

In `src/core/presidio_recognizers.py`, replace the `AustralianAddressRecognizer` pattern with (unit prefix added, structure otherwise identical):

```python
    PATTERNS = [
        Pattern(
            "AU_ADDRESS",
            r"(?:(?:Unit|Flat|Apt|Apartment)\s+)?(?:\d+[A-Za-z]?\s*/\s*)?\d+\s+[A-Za-z\s]+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|Crescent|Cres|Boulevard|Blvd|Terrace|Tce|Close|Cl|Grove|Gr|Highway|Hwy|Parade|Pde|Circuit|Cct|Loop|Rise|Vale|Mews|Esplanade|Esp),?\s+[A-Za-z\s]+,?\s+(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT)\s+\d{4}",
            0.85,
        ),
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector.py tests/test_presidio_recognizers.py tests/test_false_positives.py tests/test_adversarial.py -v
```

Expected: ALL PASS — including the pre-existing `test_text_without_state_not_matched` (see [REV-4]). If that test fails, the street-type split was not applied correctly.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_detector.py src/core/presidio_recognizers.py tests/test_pii_detector.py tests/test_false_positives.py
git commit -m "feat(detector): detect prose addresses and unit-number prefixes"
```

---

### Task 5: Whole-word verification (false-quarantine fix)

**Confirmed bug** (reproduced end to end): redacting "Ann" from a document that also contains "Annual Review" succeeds — the text layer correctly keeps "Annual Review" and loses "Ann" — but `verify_redaction` / `verify_redaction_ocr` do substring checks (`"ann" in "annual"`), report the redaction as failed, and the service quarantines a correctly-redacted file as `.UNVERIFIED.pdf`.

> **[REV-7] Tokenize on hyphens, not just whitespace.** A naive `\s+` join leaves two verification **false negatives** — cases where PII really is still visible but verification passes: `_pii_visible_in_text("Sarah Williams", "sarah-williams")` → `False`, and `("Smith-Jones", "smith - jones")` → `False`. Since this task deliberately loosens a safety net, it must not open new holes in it. Splitting the PII on whitespace *and* hyphens, then joining with `[\s\-…]*`, closes both. Verified 19/19 cases including `O'Brien`, `Smith-Jones`, emails, newline-wrapped multi-word names, and the negative cases `"sarah williamson"`, `"brann"`, `"obrien"`.

**Files:**
- Modify: `src/core/redactor.py:838-841` (`verify_redaction`), `:923-927` (`verify_redaction_ocr`), plus a new module-level helper after `_levenshtein`
- Test: `tests/test_redactor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_pii_visible_in_text(pii_text: str, haystack_lower: str) -> bool` — module-level function in `redactor.py`. `haystack_lower` must already be lowercased by the caller.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_redactor.py`:

```python
class TestWholeWordVerification:
    """Verification must not flag PII 'visible' inside longer ordinary words."""

    def test_helper_no_match_inside_longer_word(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "annual review scheduled") is False

    def test_helper_no_match_with_leading_letters(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "the banner was red") is False

    def test_helper_matches_whole_word(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "ann was here") is True

    def test_helper_matches_possessive(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "ann's workbook") is True

    def test_helper_multiword_across_whitespace(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "report for sarah\nwilliams today") is True

    def test_helper_multiword_joined_by_hyphen(self):
        """OCR may join or hyphenate a name — that is still visible PII."""
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "sarah-williams") is True

    def test_helper_hyphenated_name_split_by_spaces(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Smith-Jones", "smith - jones") is True

    def test_helper_does_not_overmatch_longer_surname(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "sarah williamson") is False

    def test_helper_email_exact(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("nick.williams@gmail.com",
                                    "contact nick.williams@gmail.com now") is True

    def test_helper_apostrophe_name(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("O'Brien", "kate o'brien attended") is True

    def test_verify_redaction_passes_when_name_only_inside_longer_word(self, tmp_path):
        """A correctly-redacted doc containing 'Annual' must verify clean for 'Ann'."""
        import fitz
        from redactor import PDFRedactor, RedactionItem

        src = tmp_path / "ann.pdf"
        out = tmp_path / "ann_redacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Student: Ann Chen", fontsize=12)
        page.insert_text((72, 130), "Annual Review scheduled for Term 3.", fontsize=12)
        doc.save(str(src))
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(page_num=1, text="Ann"),
                                        RedactionItem(page_num=1, text="Chen")])
        assert ok

        is_clean, msg = r.verify_redaction(out, "Ann")
        assert is_clean, f"False positive: {msg}"

    def test_verify_redaction_still_fails_when_name_remains(self, tmp_path):
        import fitz
        from redactor import PDFRedactor

        pdf = tmp_path / "unredacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Student: Ann Chen", fontsize=12)
        doc.save(str(pdf))
        doc.close()

        r = PDFRedactor()
        is_clean, _ = r.verify_redaction(pdf, "Ann")
        assert not is_clean
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_redactor.py::TestWholeWordVerification -v
```

Expected: `ImportError: cannot import name '_pii_visible_in_text'` for the helper tests, and `test_verify_redaction_passes_when_name_only_inside_longer_word` fails with "False positive: Text still found in document: Ann".

- [ ] **Step 3: Implement the helper and rewire both verifiers**

In `src/core/redactor.py`, add after the `_levenshtein` function:

```python
# Whitespace or any hyphen/dash variant — used to split PII into tokens and to
# join them when searching, so a name that OCR renders as "Smith - Jones" or
# "sarah-williams" is still recognised as visible.
_PII_SEP = r"[\s\-‐-―]"


def _pii_visible_in_text(pii_text: str, haystack_lower: str) -> bool:
    """
    Whole-word visibility check used by both verification paths.

    Substring checks caused false quarantines: after correctly redacting
    "Ann", the word "Annual" elsewhere made verification report the PII as
    still visible. This helper requires the PII to appear as (a) whole
    word(s) — not embedded inside a longer alphanumeric run — while still
    catching possessives ("Ann's") and multi-word PII that OCR wrapped,
    hyphenated, or ran together.

    Args:
        pii_text: The redacted PII string (any case).
        haystack_lower: The text to search, ALREADY lowercased by the caller.
    """
    tokens = [re.escape(t) for t in re.split(_PII_SEP + r"+", pii_text.lower()) if t]
    if not tokens:
        return False
    pattern = (
        r"(?<![A-Za-z0-9])"
        + (_PII_SEP + r"*").join(tokens)
        + r"(?:['’]s)?(?![A-Za-z0-9])"
    )
    return re.search(pattern, haystack_lower) is not None
```

In `verify_redaction`, replace:

```python
            # Check if the text still appears
            if original_text.lower() in all_text.lower():
                return False, f"Text still found in document: {original_text}"
```

with:

```python
            # Check if the text still appears (whole-word — substring checks
            # false-flagged short names inside longer words, e.g. Ann/Annual)
            if _pii_visible_in_text(original_text, all_text.lower()):
                return False, f"Text still found in document: {original_text}"
```

In `verify_redaction_ocr`, replace:

```python
                # Check each redacted string
                for text in redacted_texts:
                    if len(text) >= 3 and text.lower() in ocr_text:
```

with:

```python
                # Check each redacted string (whole-word — see _pii_visible_in_text)
                for text in redacted_texts:
                    if len(text) >= 3 and _pii_visible_in_text(text, ocr_text):
```

(`ocr_text` is already lowercased at its assignment — do not lowercase twice.)

- [ ] **Step 4: Run the redactor and verification suites**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_redactor.py tests/test_ocr_verification.py tests/test_backend_redact.py -v
```

Expected: ALL PASS. (`test_ocr_verification.py` was confirmed to pass unchanged with this helper.) If a test there fails asserting the OLD substring semantics, update it to whole-word expectations and note it in the commit message; any other failure means stop and debug.

- [ ] **Step 5: Commit**

```bash
git add src/core/redactor.py tests/test_redactor.py
git commit -m "fix(redactor): whole-word verification stops false quarantines (Ann vs Annual)"
```

---

### Task 6: Embedded-image OCR scan on every page (with runtime mitigations)

**Coverage hole:** Stage 2 (`_redact_embedded_images`) currently runs inside the `redactions_by_page` loop, so it only scans pages that already had a detected item — and only against that page's items. An embedded screenshot containing the student's name on an otherwise-clean page is never scanned. (This also makes CLAUDE.md rule #12, which already claims "every page", true.)

> **[REV-8] The naive move is a serious performance regression — the mitigations below are mandatory, not optional.** Measured on the real corpus: `_check_tesseract()` costs **57 ms per call** (it shells out to `pytesseract.get_tesseract_version()`), and it is invoked once per page — 43 pages is 2.5 s of pure subprocess overhead before any OCR runs. Full-page scans cost **~1.3 s/page** to OCR, so a 50-page scanned report with detections on three pages goes from a few seconds to **~65 s per document**, inside a folder batch. Three mitigations, all verified safe:
> 1. **Memoise the Tesseract check** on the instance (57 ms → one call per run).
> 2. **Cache OCR results per image xref** for the duration of one `redact_pdf` call — a repeated letterhead logo is then OCR'd once (measured: one sample document has 9 image placements across just 2 unique xrefs).
> 3. **Skip pages already handled by `_redact_ocr_page`** — that path already rendered and OCR'd the whole page at 300 DPI, so re-extracting and re-OCR'ing its single image is pure duplicate work.

**Files:**
- Modify: `src/core/redactor.py` — `__init__`, `_check_tesseract`, `_redact_embedded_images`, `redact_pdf`
- Test: `tests/test_ocr_redaction.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_redact_embedded_images(page, items, ocr_cache: dict = None)` — new optional third parameter. `PDFRedactor._tesseract_ok` instance attribute (memoised `None` → `bool`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ocr_redaction.py`:

```python
class TestEmbeddedImageScanCoverage:
    def test_embedded_image_scan_runs_on_all_pages_with_full_item_list(self, tmp_path):
        """Stage 2 must scan EVERY page against the whole document's items,
        not just pages that had their own detections."""
        import fitz
        from unittest.mock import patch
        from redactor import PDFRedactor, RedactionItem

        pdf = tmp_path / "two_page.pdf"
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((72, 100), "Report for Sarah Williams", fontsize=12)
        p2 = doc.new_page()
        p2.insert_text((72, 100), "General notes with nothing detected", fontsize=12)
        doc.save(str(pdf))
        doc.close()

        items = [RedactionItem(page_num=1, text="Sarah Williams")]
        calls = []

        def record(self, page, its, ocr_cache=None):
            calls.append((page.number, [i.text for i in its]))
            return 0

        r = PDFRedactor()
        with patch.object(PDFRedactor, "_redact_embedded_images", autospec=True,
                          side_effect=record):
            ok, _ = r.redact_pdf(pdf, tmp_path / "out.pdf", items)

        assert ok
        pages_scanned = {c[0] for c in calls}
        assert pages_scanned == {0, 1}, f"Expected both pages scanned, got {pages_scanned}"
        for _, texts in calls:
            assert texts == ["Sarah Williams"]

    def test_tesseract_check_is_memoised(self):
        """The availability check must not shell out once per page."""
        from unittest.mock import patch
        from redactor import PDFRedactor

        r = PDFRedactor()
        with patch("redactor.pytesseract.get_tesseract_version", return_value="5.0") as m:
            assert r._check_tesseract() is True
            assert r._check_tesseract() is True
            assert r._check_tesseract() is True
        assert m.call_count == 1
```

(The `autospec=True` + `side_effect` mechanics were verified: `record` receives `self` as its first argument exactly as written.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py::TestEmbeddedImageScanCoverage -v
```

Expected: the coverage test FAILS (`pages_scanned` is `{0}`); the memoisation test FAILS (`call_count == 3`).

- [ ] **Step 3: Memoise the Tesseract check**

In `src/core/redactor.py`, replace the `PDFRedactor.__init__` body:

```python
    def __init__(self):
        pass
```

with:

```python
    def __init__(self):
        # Memoised Tesseract availability — the check shells out to
        # `tesseract --version` (~57ms), and Stage 2 asks once per page.
        self._tesseract_ok = None
```

and replace `_check_tesseract`:

```python
    def _check_tesseract(self) -> bool:
        """Check if Tesseract is installed and accessible."""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
```

with:

```python
    def _check_tesseract(self) -> bool:
        """Whether Tesseract is installed and accessible (memoised per instance)."""
        if self._tesseract_ok is None:
            try:
                pytesseract.get_tesseract_version()
                self._tesseract_ok = True
            except Exception:
                self._tesseract_ok = False
        return self._tesseract_ok
```

- [ ] **Step 4: Add the per-xref OCR cache**

In `_redact_embedded_images`, change the signature:

```python
    def _redact_embedded_images(self, page: fitz.Page, items: list) -> int:
```

to:

```python
    def _redact_embedded_images(self, page: fitz.Page, items: list, ocr_cache: dict = None) -> int:
```

Then, inside the per-image loop, replace this block:

```python
            ocr_data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
            ocr_words = []
            for i in range(len(ocr_data['text'])):
                word = ocr_data['text'][i].strip()
                if not word:
                    continue
                x = ocr_data['left'][i]
                y = ocr_data['top'][i]
                w = ocr_data['width'][i]
                h = ocr_data['height'][i]
                ocr_words.append((word, (x, y, x + w, y + h)))
```

with:

```python
            # The same logo/letterhead xref often repeats on every page — OCR
            # it once per document rather than once per placement.
            if ocr_cache is not None and xref in ocr_cache:
                ocr_words = ocr_cache[xref]
            else:
                ocr_data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
                ocr_words = []
                for i in range(len(ocr_data['text'])):
                    word = ocr_data['text'][i].strip()
                    if not word:
                        continue
                    x = ocr_data['left'][i]
                    y = ocr_data['top'][i]
                    w = ocr_data['width'][i]
                    h = ocr_data['height'][i]
                    ocr_words.append((word, (x, y, x + w, y + h)))
                if ocr_cache is not None:
                    ocr_cache[xref] = ocr_words
```

- [ ] **Step 5: Move Stage 2 out of the per-page loop**

In `redact_pdf`, DELETE these three lines from inside the `for page_num, items in redactions_by_page.items():` loop:

```python
                # Stage 2: Scan every embedded image on this page for PII.
                # Runs on ALL pages — text-layer, image-only, and hybrid.
                image_redacted_count += self._redact_embedded_images(page, items)
```

In that same loop, record which pages took the full-page OCR path. Change:

```python
                if self._is_image_only_page(page):
                    # Image-only page: render → OCR → draw black rects on image → replace page
                    ocr_hits = self._redact_ocr_page(page, items)
                    ocr_redacted_count += ocr_hits
```

to:

```python
                if self._is_image_only_page(page):
                    # Image-only page: render → OCR → draw black rects on image → replace page
                    ocr_hits = self._redact_ocr_page(page, items)
                    ocr_redacted_count += ocr_hits
                    # This page's whole content was just rendered and OCR'd at
                    # 300 DPI — Stage 2 would only re-OCR the same pixels.
                    ocr_handled_pages.add(page.number)
```

and initialise that set next to `all_redacted_texts = set()`:

```python
            ocr_handled_pages = set()
```

Then, immediately AFTER the per-page loop closes (before the `# ── Stage 4: Signature image detection ──` block), ADD:

```python
            # ── Stage 2: Embedded-image OCR scan ──
            # Runs on EVERY page with the full document-level item list, so an
            # image containing PII on a page with no text-layer detections is
            # still scanned. Pages already handled by _redact_ocr_page are
            # skipped, and OCR results are cached per image xref, so repeated
            # letterheads are read once per document rather than once per page.
            if redaction_items:
                ocr_cache: dict = {}
                for page in doc:
                    if page.number in ocr_handled_pages:
                        continue
                    image_redacted_count += self._redact_embedded_images(
                        page, redaction_items, ocr_cache=ocr_cache
                    )
```

- [ ] **Step 6: Run the OCR redaction and integration suites**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_ocr_redaction.py tests/test_integration.py tests/test_signature_detection.py tests/test_widget_redaction.py tests/test_metadata_stripping.py tests/test_zone_redaction.py -v
```

Expected: ALL PASS (98 tests across these files were confirmed green with this change).

- [ ] **Step 7: Commit**

```bash
git add src/core/redactor.py tests/test_ocr_redaction.py
git commit -m "fix(redactor): scan embedded images on every page, with OCR caching and memoised tesseract check"
```

---

### Task 7: Contextual-name capture must require capitalisation

**Confirmed noise bug:** the family-keyword patterns compile with `re.IGNORECASE`, which silently defeats the `[A-Z][a-z]+` "capitalised name" requirement. Verified current behaviour:

```
'Parent email: nick...'  -> [('email', 'Parent/Guardian')]
'Mother reports that...' -> [('reports that', 'Parent/Guardian')]
```

Fix: scope case-insensitivity to the keyword only, using Python's scoped inline flag `(?i:...)`. Verified after the fix: both return `[]`, and `'MOTHER: JANE attended'` still returns `['JANE']` (the ALL-CAPS branch is intact). On the real corpus this removes 6 of 12 spurious Parent/Guardian items (`'and peer'`, `'reading'`, `'rereads the'`).

> **[REV-9] Accepted tradeoff, to be recorded in the release note.** A teacher who types "mother: jane smith" in all-lowercase now gets nothing from the regex engine, and spaCy is weak on lowercase person names. This is a 0.65-confidence category and the noise reduction is large, so the trade is worth taking — but state it explicitly in the release notes rather than leaving it implicit.

**Files:**
- Modify: `src/core/pii_detector.py:525-529` (the three patterns in `_detect_contextual_names`)
- Test: `tests/test_pii_detector_names.py` (contextual test class)

**Interfaces:**
- Consumes: nothing.
- Produces: no signature changes. Behaviour change: fully-lowercase words after a family keyword are no longer captured.

- [ ] **Step 1: Write the failing tests**

Add to the contextual-detection test class in `tests/test_pii_detector_names.py`:

```python
    def test_lowercase_word_after_keyword_not_captured(self):
        """'Parent email:' must not flag the word 'email' as a name."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Parent email: nick.williams@gmail.com", page_num=1)
        contextual = [m for m in matches
                      if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text == "email" for m in contextual)

    def test_lowercase_phrase_after_keyword_not_captured(self):
        """Today this captures 'reports that'; after the fix, nothing."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Mother reports that homework is difficult", page_num=1)
        contextual = [m for m in matches
                      if m.category in ("Parent/Guardian", "Family member")]
        assert not contextual, f"Unexpected contextual matches: {[m.text for m in contextual]}"

    def test_allcaps_name_after_keyword_still_captured(self):
        """ALL-CAPS names (form headers) must still be captured."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("MOTHER: JANE attended", page_num=1)
        contextual = [m for m in matches if m.category == "Parent/Guardian"]
        assert any("JANE" in m.text for m in contextual)
```

(Note: `test_lowercase_phrase_after_keyword_not_captured` asserts `not contextual` rather than checking for a specific string — the currently-captured text is `"reports that"`, not `"reports"`, so a `m.text != "reports"` assertion would pass before and after and guard nothing.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector_names.py -k "lowercase_word or lowercase_phrase or allcaps_name" -v
```

Expected: both lowercase tests FAIL; `test_allcaps_name_after_keyword_still_captured` passes (regression guard).

- [ ] **Step 3: Scope IGNORECASE to the keyword only**

In `src/core/pii_detector.py` `_detect_contextual_names`, replace:

```python
            patterns = [
                re.compile(r'\b' + keyword + r'[:\s]+' + _name_pat, re.IGNORECASE),
                re.compile(r'\b' + keyword + r'\s*\(\s*' + _name_pat + r'\s*\)', re.IGNORECASE),
                re.compile(r'\b' + keyword + r',\s+' + _name_pat, re.IGNORECASE),
            ]
```

with:

```python
            # Keyword matching is case-insensitive via a scoped inline flag,
            # but the name capture stays case-SENSITIVE — a global IGNORECASE
            # silently defeated the [A-Z][a-z]+ capitalisation requirement and
            # flagged words like "email" in "Parent email:" as names.
            patterns = [
                re.compile(r'\b(?i:' + keyword + r')[:\s]+' + _name_pat),
                re.compile(r'\b(?i:' + keyword + r')\s*\(\s*' + _name_pat + r'\s*\)'),
                re.compile(r'\b(?i:' + keyword + r'),\s+' + _name_pat),
            ]
```

(Verified: `(?i:...)` works in Python 3.13 and composes correctly with keyword strings that contain regex, such as `Foster\s+parent` and `Step-mother`. The cross-line block below keeps its own `re.IGNORECASE` on `keyword_pat` — that pattern matches the keyword only, and its `name_only` pattern is already case-sensitive.)

- [ ] **Step 4: Run the full names suite**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_detector_names.py tests/test_pii_detector.py tests/test_false_positives.py -v
```

Expected: ALL PASS. Existing tests use lowercase keywords with capitalised names ("his father (Nick)") and are unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_detector.py tests/test_pii_detector_names.py
git commit -m "fix(detector): contextual name capture requires capitalisation, keyword stays case-insensitive"
```

---

### Task 8: NER variation matching — word boundaries and title filtering

**Confirmed noise bug:** the orchestrator searches NER name variations with `re.finditer(re.escape(var), text, re.IGNORECASE)` — no word boundary — so the variation "Ann" (from "Ann Chen") also matches inside "Annual", creating phantom review items. Separately, "Mrs Thompson" generates "Mrs" as a first-name variation.

> **[REV-6] BLOCKER AVOIDED — do NOT reuse `_CONTEXTUAL_NAME_EXCLUDE` to filter variations.** That set is not a title list. It contains ~25 **real given names**, because it was built for a different job (filtering keyword-adjacent noise and nicknames): `belle, bill, bob, cal, cam, con, dick, dom, don, gen, len, max, may, nan, nana, pat, penny, ray, reg, rich, rick, rob, ron, sue, ted`. Filtering variations through it would mean: NER finds "Bob Henderson" (a parent) on page 1; later pages say only "Bob"; the bare "Bob" is **no longer flagged and therefore not redacted** — a privacy breach, introduced by a change whose only goal was cosmetic. Verified drops: `Bob Henderson → ['Bob']`, `Sue Williams → ['Sue']`, `Max Fenn → ['Max']`, `Pat O'Brien → ['Pat']`, `Penny Clarke → ['Penny']`, `Ray Smith → ['Ray']`, `Ted Nguyen → ['Ted']`. **Use the dedicated `_NAME_TITLES` set below instead.**

**Files:**
- Modify: `src/core/pii_orchestrator.py` (new `_NAME_TITLES` constant + the variation loop at `:144-154`)
- Test: `tests/test_pii_orchestrator.py`

**Interfaces:**
- Consumes: nothing. (Explicitly does NOT import `_CONTEXTUAL_NAME_EXCLUDE`.)
- Produces: `_NAME_TITLES` module-level set in `pii_orchestrator.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pii_orchestrator.py`. `PIIMatch` and `PIIOrchestrator` are already imported at the top of that file — do not re-import them:

```python
def _stub_person(text_val):
    return PIIMatch(text=text_val, category="Person name (NER)", confidence=0.90,
                    page_num=1, line_num=1, context="", source="presidio")


class TestNerVariationBoundaries:
    def _orchestrator_with_stub(self, monkeypatch, person_text):
        # Skip the (slow) real Presidio init; stub the NER result directly.
        monkeypatch.setattr(PIIOrchestrator, "_init_presidio", lambda self: None)
        orch = PIIOrchestrator("Zara Quill")
        orch.presidio_analyzer = object()  # truthy — _run_presidio is stubbed
        monkeypatch.setattr(
            orch, "_run_presidio",
            lambda text, page_num: [_stub_person(person_text)]
        )
        return orch

    def test_variation_does_not_match_inside_longer_word(self, monkeypatch):
        orch = self._orchestrator_with_stub(monkeypatch, "Ann Chen")
        text = "Ann Chen attended.\nAnnual Review scheduled for Term 3."
        matches = orch.detect_pii_in_text(text, page_num=1)
        ann_hits = [m for m in matches if m.text.lower() == "ann"]
        assert all(m.line_num == 1 for m in ann_hits), \
            f"'Ann' matched inside 'Annual': {[(m.text, m.line_num) for m in ann_hits]}"

    def test_title_tokens_not_generated_as_variations(self, monkeypatch):
        orch = self._orchestrator_with_stub(monkeypatch, "Mrs Thompson")
        text = "Mrs Thompson is the classroom teacher."
        matches = orch.detect_pii_in_text(text, page_num=1)
        assert not any(m.text.lower() == "mrs" for m in matches), \
            "Bare title 'Mrs' must not be flagged as a name variation"

    def test_real_given_names_are_still_flagged_as_variations(self, monkeypatch):
        """Regression guard: common given names must NOT be filtered out.

        An earlier design filtered variations through _CONTEXTUAL_NAME_EXCLUDE,
        which contains real names (Bob, Sue, Max, Pat, Ray, Ted...). That would
        silently stop redacting a parent referred to by first name only.
        """
        for full, bare in [("Bob Henderson", "bob"), ("Sue Williams", "sue"),
                           ("Max Fenn", "max"), ("Ray Smith", "ray")]:
            orch = self._orchestrator_with_stub(monkeypatch, full)
            text = f"{full} attended the meeting.\nLater {bare.capitalize()} phoned the school."
            matches = orch.detect_pii_in_text(text, page_num=1)
            assert any(m.text.lower() == bare for m in matches), \
                f"Bare given name {bare!r} from {full!r} was not flagged — privacy risk"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py::TestNerVariationBoundaries -v
```

Expected: the first two FAIL ("Ann" matches on line 2 inside "Annual"; "Mrs" is flagged). `test_real_given_names_are_still_flagged_as_variations` passes today and must STILL pass after the change — it is the guard against [REV-6].

- [ ] **Step 3: Add the title set, boundaries, and filter**

In `src/core/pii_orchestrator.py`, add after the existing module-level constants (near `PRESIDIO_SKIP_TYPES`):

```python
# Honorifics that spaCy sometimes includes in a PERSON span ("Mrs Thompson"),
# which then generate a bare title as a "first name" variation.
#
# This is deliberately its own set and NOT _CONTEXTUAL_NAME_EXCLUDE from
# pii_detector: that set contains real given names (Bob, Sue, Max, Pat, Ray,
# Ted, Penny...) because it filters keyword-adjacent noise. Filtering name
# variations through it would stop redacting a parent referred to by first
# name only — a privacy breach.
_NAME_TITLES = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor",
    "sir", "madam", "rev", "master",
}
```

Then in `detect_pii_in_text`, replace the variation loop:

```python
                    variations, _ = generate_name_variations(m.text, include_nicknames=False)
                    for var in variations:
                        if var.lower() != m.text.lower() and len(var) >= 3:
                            for match in re.finditer(re.escape(var), text, re.IGNORECASE):
```

with:

```python
                    variations, _ = generate_name_variations(m.text, include_nicknames=False)
                    for var in variations:
                        if var.lower() != m.text.lower() and len(var) >= 3:
                            # A bare honorific is not a name (see _NAME_TITLES).
                            if var.lower() in _NAME_TITLES:
                                continue
                            # Lookaround boundaries: "Ann" must not match inside
                            # "Annual". (\b fails for variations that start or end
                            # with punctuation, like "J. Smith" or "S.W.")
                            var_pattern = (r'(?<![A-Za-z0-9])' + re.escape(var)
                                           + r'(?![A-Za-z0-9])')
                            for match in re.finditer(var_pattern, text, re.IGNORECASE):
```

(The body of the inner `for match ...:` loop is unchanged. Lookarounds were verified to handle `J. Smith`, `S.W.` and `M.T.` correctly where `\b` would not.)

- [ ] **Step 4: Run the orchestrator suite**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/test_pii_orchestrator.py -v
```

Expected: ALL PASS (27 existing + 3 new), **including** `test_real_given_names_are_still_flagged_as_variations`.

- [ ] **Step 5: Commit**

```bash
git add src/core/pii_orchestrator.py tests/test_pii_orchestrator.py
git commit -m "fix(orchestrator): word-boundary NER variation matching, skip bare honorifics"
```

---

### Task 9: Corpus regression check, full suite, CLAUDE.md sync

> **[REV-10] Measure the net effect on real documents.** Four detection patterns change across this plan with no measurement of their combined effect. A before/after category count over the real `sample/` corpus is cheap and is the only thing that catches a noise regression the unit tests cannot see.

**Files:**
- Create: `scripts/detection_delta.py` (a small, permanent developer tool)
- Modify: `CLAUDE.md` (project root)

**Interfaces:**
- Consumes: the completed Tasks 1–8.
- Produces: `scripts/detection_delta.py` (developer tool, not imported by the app).

- [ ] **Step 1: Write the corpus delta tool**

Create `scripts/detection_delta.py`:

```python
"""Developer tool: category counts for the current detector over sample/ PDFs.

Run before and after a detection-pattern change and diff the two outputs:

    git stash && venv/bin/python3.13 scripts/detection_delta.py > /tmp/before.txt
    git stash pop && venv/bin/python3.13 scripts/detection_delta.py > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt

Unit tests cannot see noise regressions across real documents; this can.
"""

import collections
import glob
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src" / "core"))

import fitz  # noqa: E402
from pii_detector import PIIDetector  # noqa: E402

# The sample corpus is one student; adjust these if the sample data changes.
STUDENT = "Jobe Fenn"
PARENTS = ["Louisa Fenn"]


def main():
    pdfs = sorted(glob.glob(str(_ROOT / "sample" / "**" / "*.pdf"), recursive=True))
    if not pdfs:
        print("No sample PDFs found — nothing to compare.")
        return

    detector = PIIDetector(STUDENT, parent_names=PARENTS)
    counts = collections.Counter()
    items = set()

    for path in pdfs:
        with fitz.open(path) as doc:
            for page in doc:
                for m in detector.detect_pii_in_text(page.get_text(), page_num=page.number + 1):
                    counts[m.category] += 1
                    items.add((Path(path).name, m.category, m.text))

    print(f"documents: {len(pdfs)}")
    print(f"{'category':36s} {'count':>6s}")
    for category in sorted(counts):
        print(f"{category:36s} {counts[category]:6d}")
    print("\nall distinct items (file | category | text):")
    for item in sorted(items):
        print("  " + " | ".join(item))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the before/after comparison**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 scripts/detection_delta.py > /tmp/after.txt && git stash && venv/bin/python3.13 scripts/detection_delta.py > /tmp/before.txt; git stash pop && diff /tmp/before.txt /tmp/after.txt; echo "--- exit $? (1 = differences, expected) ---"
```

Expected (based on the pre-implementation measurement): roughly `Date of birth 0 → 1` (Task 3 finds a genuinely missed `20/07/13`), `Parent/Guardian 12 → 6` (Task 7 removes `'and peer'`, `'reading'`, `'rereads the'`), `Student name` unchanged at 435, and **no new Address items** (Task 4's tightened pattern found zero street-only hits on this corpus).

**Review the diff before continuing.** Any *lost* Student name / Parent / Email / Phone item is a regression — stop and investigate rather than proceeding. Any *new* item should be a genuine piece of PII you can point at in the source document.

- [ ] **Step 3: Run the entire test suite**

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && venv/bin/python3.13 -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `N passed` with zero failures, where N ≥ 316 + the ~30 tests added by this plan. Note the exact number for the next step.

- [ ] **Step 4: Update CLAUDE.md**

Make exactly these edits:

1. **Reconcile the test count.** CLAUDE.md says **306** on the `**Test**:` line near the top and **316** in the Test Structure block. Set both to the actual number from Step 3.
2. **Detection Confidence Values table** — add one row after the "Address" row:
   `| Address (street-only, no state/postcode) | 0.65 | Medium — capitalised street name + street type, no state/postcode anchor |`
3. **Rule #9** (two verification methods) — append: "Both verifiers use the module-level `_pii_visible_in_text()` whole-word check — never revert to substring matching, which falsely quarantined correctly-redacted files when a short name ('Ann') appeared inside an ordinary word ('Annual'). The helper splits PII on whitespace *and* hyphens so OCR variants like 'smith - jones' are still caught."
4. **Rule #12** (embedded images) — replace its first sentence with: "After per-page redaction, `_redact_embedded_images()` runs on **every page of the document** with the full document-level redaction item list (not just pages that had detections). Pages already processed by `_redact_ocr_page()` are skipped (their pixels were just OCR'd at 300 DPI), OCR results are cached per image xref for the run, and `_check_tesseract()` is memoised on the instance — without those three mitigations a 50-page scanned report costs ~65s."
5. **Add a new numbered rule:** "**The street-only Address pattern uses two street-type classes.** Unambiguous nouns (`Street`, `Road`, `Lane`…) match freely; abbreviations and words that are also common English nouns (`St`, `Dr`, `Court`, `Place`, `Rise`, `Way`, `Close`, `Grove`) must be followed by a comma, full stop, or end-of-line. Merging them back into one list re-introduces false positives on report language such as '2 Specialists Dr Jones' and '12 Point Rise in reading fluency' — which the Accept-All path would redact without the teacher noticing."
6. **Add a new numbered rule:** "**Never filter NER name variations through `_CONTEXTUAL_NAME_EXCLUDE`.** That set contains real given names (Bob, Sue, Max, Pat, Ray, Ted, Penny…) because it filters keyword-adjacent noise in `_detect_contextual_names`. Using it on variations stops a parent referred to by first name only from being redacted. `pii_orchestrator._NAME_TITLES` exists for the honorific-filtering job; keep the two separate."
7. **Test Structure section** — update the per-file counts for `test_pii_detector.py`, `test_pii_detector_names.py`, `test_pii_orchestrator.py`, `test_presidio_recognizers.py`, `test_redactor.py`, `test_ocr_redaction.py` and `test_false_positives.py` (get each with `venv/bin/python3.13 -m pytest tests/<file> -q 2>&1 | tail -1`).
8. **Known Gaps** — under "OCR redaction quality", delete the stale sentence "There is no fuzzy OCR matching yet." if still present (fuzzy matching shipped in v1.4.0).

- [ ] **Step 5: Commit**

```bash
git add scripts/detection_delta.py CLAUDE.md
git commit -m "docs(claude): sync detection patterns, verification and stage-2 rules with code"
```

---

## Release-note items (for whoever writes the next release)

- Newly detected: real-format Centrelink CRNs, `+61` mobile numbers, dotted phone numbers, dotted/2-digit-year/ordinal/month-first dates of birth, addresses written in prose without a state and postcode, and unit numbers in addresses.
- Fixed: correctly-redacted documents were sometimes quarantined as `.UNVERIFIED.pdf` when a short name appeared inside an ordinary word (e.g. "Ann" inside "Annual").
- Improved: images are now scanned for PII on every page, not only pages that already had a detection.
- **Behaviour change to call out:** names written entirely in lowercase after a family keyword (e.g. "mother: jane smith") are no longer picked up by the pattern engine. This removed a large amount of review-list noise; type names with capitals, or add them via "Add a Missed Item".

## Self-Review Checklist (run after all tasks)

- [ ] Every gap has a task: CRN format (1), +61/dotted phones (2), DOB formats (3), prose/unit addresses (4), false quarantine (5), embedded-image coverage (6), "email"-as-name noise (7), Ann/Annual + "Mrs" variation noise (8).
- [ ] **[REV-3/4]** The street-only pattern uses the two-class split; `test_text_without_state_not_matched` passes unchanged; the false-positive class in `test_false_positives.py` passes.
- [ ] **[REV-6]** `pii_orchestrator.py` does NOT import `_CONTEXTUAL_NAME_EXCLUDE`, and `test_real_given_names_are_still_flagged_as_variations` passes.
- [ ] **[REV-7]** `_pii_visible_in_text` splits on hyphens as well as whitespace.
- [ ] **[REV-8]** All three Stage-2 mitigations are in place (memoised check, xref cache, skip OCR-handled pages).
- [ ] Regex + Presidio pattern pairs are in sync (Tasks 1–4 touch both files).
- [ ] The corpus delta was reviewed and every change in it is explainable.
- [ ] `venv/bin/python3.13 -m pytest tests/ -q` fully green.
- [ ] No new dependencies, no API/schema changes, no frontend changes.
