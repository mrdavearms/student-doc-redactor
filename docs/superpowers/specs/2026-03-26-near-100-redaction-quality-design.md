# Near-100% Redaction Quality — Design Spec

> Date: 2026-03-26
> Status: Approved
> Goal: Every person name in every document gets detected and redacted, plus all PII survives no hiding place in the PDF structure.

---

## Problem Statement

The current redaction pipeline has three categories of gap:

1. **Detection gaps** — PII that exists in the document but is never identified. The biggest: the tool only reliably finds names the user explicitly enters. Any other person name (psychologist, teacher, specialist, other students) is only caught if spaCy/Presidio NER happens to pick it up — and NER results are treated as low-priority supplements rather than primary detections.

2. **PDF structure gaps** — PII that IS detected but survives redaction because it hides in PDF structures the redactor doesn't touch: link annotation URIs, sticky notes, bookmarks, the tagged PDF structure tree, JavaScript actions.

3. **Test coverage gaps** — No end-to-end integration test of the production pipeline. The bbox redaction path is untested. OCR tests are 100% mocked. Three service files have zero execution tests.

## Success Criteria

- Every PERSON entity detected by spaCy NER is treated as a high-confidence match with full name-variation generation
- Cross-line PII (label on one line, value on next) is detected for: DOB, Medicare, CRN, addresses, family keywords
- PII in link URIs, annotations, bookmarks, structure trees, and JavaScript is removed
- Widget deletion runs on ALL pages, not just pages with detected PII
- Form XObject images are OCR-scanned for PII
- Hidden PDF layers (OCG) are forced visible before detection/redaction
- Failed verification quarantines the output file
- GLiNER + PyTorch removed; installer size reduced (verify actual reduction — see Phase 4 note on PyTorch)
- End-to-end integration tests cover the full RedactionService.execute() pipeline
- Adversarial and false-positive regression tests exist

---

## Design

### Phase 1: Detection Architecture — NER-Primary Restructure

#### 1.1 Text Extraction Normalisation

**File: `src/core/text_extractor.py`**

- Apply `unicodedata.normalize('NFKC', text)` to all extracted text before returning it. This decomposes ligatures (fi → fi, fl → fl) so names like "Griffin" match even when stored as "Griﬃn".
- Normalise smart quotes: replace `\u2019` (right single quote), `\u2018` (left single quote), `\u201C`, `\u201D` (double quotes) with their ASCII equivalents.
- **Fix OCR text line preservation**: Change line 180 from joining OCR words with spaces to preserving line structure. Use Tesseract's `block_num` and `line_num` fields from `image_to_data` output to reconstruct line breaks. This fixes the bug where all OCR text collapses to `line_num=1`, causing dedup to drop duplicate name occurrences on the same page.

**Important for redaction**: NFKC normalisation fixes detection, but `page.search_for()` in `redactor.py` searches the raw PDF text layer (not the normalised version). PyMuPDF's `search_for()` does handle many ligature decompositions internally. However, if a normalised PII text fails to match via `search_for()`, the redaction code should fall back to bbox-based redaction when bboxes are available from the detection phase. Add a log warning when `search_for()` returns no results for a known PII item so the audit trail captures it.

#### 1.2 NER-Primary Orchestration

**File: `src/core/pii_orchestrator.py`**

Current flow: regex first, NER supplements, dedup keeps highest confidence.

New flow:
1. spaCy/Presidio `analyze()` runs on the full page text
2. Every PERSON entity gets confidence 0.90
3. **For each NER-discovered person name**: call a new standalone function `generate_name_variations(name: str) -> list[str]` (extracted from the instance method `PIIDetector._generate_name_variations()`). The existing method relies on `self.student_name` — the new function takes just a name string and returns variations (possessives, initials like `"S. Jones"`, first-only, last-only). These variations are added as additional matches at confidence 0.85.
4. Regex engine runs for structured PII (phone, email, address, DOB, Medicare, CRN, Student ID, NDIS, ABN) and user-entered names (student, parents, family, orgs at 0.95)
5. Cross-line lookahead pass runs (see 1.4)
6. Dedup merges all results

**Extracting `generate_name_variations()` as a standalone function**: The existing `PIIDetector._generate_name_variations()` (line 141 of `pii_detector.py`) uses `self.student_name` for the short-name guard (`or v == self.student_name`). Extract the core logic into a module-level function that accepts `name: str` and `preserve_short_name: str | None = None`. The instance method becomes a thin wrapper: `return generate_name_variations(name, preserve_short_name=self.student_name)`. The orchestrator calls the standalone version for NER-discovered names with `preserve_short_name=None`.

The key architectural change: NER-discovered names are no longer "bonus finds" — they are primary detections with variation generation, just like user-entered names. The user-entered student name still gets 0.95 (slightly higher than NER's 0.90) so the review screen can distinguish "names you told us about" from "names we found."

#### 1.3 New Regex Patterns

**File: `src/core/pii_detector.py`**

New patterns to add:

```python
# NDIS participant number (9 digits with contextual keyword)
NDIS_PATTERN = r'(?i)(?:ndis|participant)\s*(?:number|no\.?|#)?\s*:?\s*(\d{9})\b'

# Australian Business Number (11 digits, keyword required)
ABN_PATTERN = r'(?i)abn\s*:?\s*(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})\b'

# Australian passport (low priority — add pattern but don't prioritise edge cases)
PASSPORT_PATTERN = r'(?i)passport\s*(?:number|no\.?|#)?\s*:?\s*([A-Z]\d{7})\b'
```

Extend `ADDRESS_PATTERN` street types:
- Add: `Close|Cl`, `Grove|Gr`, `Highway|Hwy`, `Parade|Pde`, `Circuit|Cct`, `Loop`, `Rise`, `Vale`, `Mews`, `Esplanade|Esp`
- Mirror in `presidio_recognizers.py`

Extend `FAMILY_KEYWORDS`:
- Add: `Stepmother`, `Stepfather`, `Foster parent`, `Foster carer`, `Legal guardian`, `Primary carer`, `Kinship carer`, `Aunt`, `Uncle`, `Grandparent`

Extend phone patterns:
- Change `\s*` to `[\s\-]*` in the mobile pattern to catch dash-separated numbers like `0412-345-678`

Fix ALL-CAPS contextual name capture:
- Change `_name_pat` from `r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'` to also match `([A-Z]{2,}(?:\s+[A-Z]{2,})?)` as an alternative branch

Fix smart quote matching in name variations:
- In `_detect_names()`, before building regex patterns from user-entered names, normalise all apostrophe variants to straight apostrophes in both the variation string and the search text

#### 1.4 Cross-Line Lookahead

**File: `src/core/pii_detector.py`**

**Signature change required**: The main detection loop in `detect_pii_in_text()` (line 181) currently passes a single `line` string to each detection method. To support cross-line lookahead, the following methods need their signatures extended to also receive `lines: list[str]` and `line_idx: int`:

- `_detect_dob(line, line_num)` → `_detect_dob(line, line_num, lines, line_idx)`
- `_detect_medicare(line, line_num)` → `_detect_medicare(line, line_num, lines, line_idx)`
- `_detect_crn(line, line_num)` → `_detect_crn(line, line_num, lines, line_idx)`
- `_detect_addresses(line, line_num)` → `_detect_addresses(line, line_num, lines, line_idx)`
- `_detect_contextual_names(line, line_num)` → `_detect_contextual_names(line, line_num, lines, line_idx)`

The calling loop changes from:
```python
for line_num, line in enumerate(lines, 1):
    matches.extend(self._detect_dob(line, line_num))
```
to:
```python
for line_idx, line in enumerate(lines):
    line_num = line_idx + 1
    matches.extend(self._detect_dob(line, line_num, lines, line_idx))
```

**This is a significant refactor** — all existing tests calling these methods directly will need updating. The test files affected are `test_pii_detector.py` (39 tests) and `test_pii_detector_names.py` (61 tests). Most can be updated mechanically by passing `lines=[line]` and `line_idx=0` to preserve existing single-line behavior.

New helper method: `_peek_next_line(lines, line_idx) -> str | None` — returns `lines[line_idx + 1]` if it exists, else `None`.

Apply lookahead in each method:
- `_detect_dob()`: if DOB label found but no date on same line, check next line
- `_detect_medicare()`: if "medicare" keyword found but no 10-digit number, check next line
- `_detect_crn()`: if CRN keyword found but no 9-digit number, check next line
- `_detect_addresses()`: if street address found but no state/postcode, check next line (and combine)
- Family keyword contextual detection: if keyword found but `_name_pat` doesn't match on same line, capture name from next line

#### 1.5 Nickname/Fuzzy Matching

**File: `src/core/nickname_map.py` (new file)**

A curated dictionary of ~100 common Australian English formal→informal name mappings:

```python
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
    # ... expand to ~100 entries
}

# Also build the reverse map for lookup efficiency
REVERSE_NICKNAME_MAP = {}
for formal, nicks in NICKNAME_MAP.items():
    for nick in nicks:
        REVERSE_NICKNAME_MAP.setdefault(nick, []).append(formal)
```

**False-positive mitigation for short nicknames**: Short nicknames like "Pat", "Sue", "Art", "Bill", "Rob", "Dan" are common English words. To prevent excessive false positives:
- Nickname matching only activates for **user-entered names** (student, parent, family names), NOT for NER-discovered names. Rationale: if the user typed "Patricia", they know "Pat" is relevant. But if NER finds "Patricia" in a document, auto-expanding to "Pat" would flag every occurrence of the word "pat" (as in "pat on the back").
- Nickname variations get confidence 0.75 (below the 0.85 of NER variations), clearly marking them as lower-certainty matches on the review screen.
- The existing `_CONTEXTUAL_NAME_EXCLUDE` list should be checked against all nickname variations — exclude any nickname that appears in the exclusion list.

Usage: When a user-entered name is found, look up its lowercase form in `NICKNAME_MAP`. If found, add each nickname as a variation at confidence 0.75 (subject to the guards above). Also check `REVERSE_NICKNAME_MAP` — if a nickname is entered as the student name, add the formal name(s) as variations. This is bidirectional: if the student is "Christopher" and the document says "Chris", it's caught. If the student is entered as "Chris" and the document says "Christopher", it's also caught.

#### 1.6 NER Failure as Hard Error in Bundled App

**File: `src/core/pii_orchestrator.py`**

Add a parameter: `require_ner: bool = False`. When `True`, if `_init_presidio()` fails, raise an exception instead of setting `self.presidio_analyzer = None`.

**File: `src/services/detection_service.py`** (NOT `backend/main.py` directly — the orchestrator is constructed inside `DetectionService.__init__()`)

Modify `DetectionService.__init__()` to accept and pass through `require_ner=True` to the `PIIOrchestrator` constructor.

**File: `backend/main.py`**

When constructing `DetectionService`, pass `require_ner=True`. The FastAPI startup will fail loudly if spaCy isn't available.

**File: `desktop/src/pages/Setup.tsx`** (note: the actual filename is `Setup.tsx`, not `SetupScreen.tsx`)

The setup screen already checks dependencies. Add a check that the `/api/dependencies/check` endpoint confirms NER is loaded. If not, show a blocking error: "Name detection engine failed to load. The app cannot redact safely without it."

---

### Phase 2: PDF Structure Hardening

#### 2.1 Link Annotation Cleanup

**File: `src/core/redactor.py`**

New method: `_delete_pii_links(page, redacted_texts)`

After `apply_redactions()` on each page, iterate `page.get_links()`. For each link with a `uri` field, check if any redacted PII text appears in the URI (case-insensitive substring). If so, `page.delete_link(link)`.

#### 2.2 Non-Widget Annotation Cleanup

**File: `src/core/redactor.py`**

New method: `_delete_pii_annotations(page, redacted_texts)`

Iterate `page.annots()`. For each annotation that is NOT a widget (skip `/Subtype /Widget`), check:
- `annot.info.get("content", "")` — the `/Contents` field
- `annot.info.get("title", "")` — the `/T` author field
- For FreeText annotations: the annotation's text content

If any field contains PII, call `page.delete_annot(annot)`.

#### 2.3 Bookmark/Outline Redaction

**File: `src/core/redactor.py`**

New method: `_redact_bookmarks(doc, redacted_texts)`

```python
toc = doc.get_toc(simple=False)
modified = False
for entry in toc:
    title = entry[1]
    for pii_text in redacted_texts:
        if pii_text.lower() in title.lower():
            entry[1] = title.replace(pii_text, "[REDACTED]")  # case-insensitive replace
            modified = True
if modified:
    doc.set_toc(toc)
```

#### 2.4 Structure Tree Stripping

**File: `src/core/redactor.py`** — add to `_strip_metadata()`

```python
# Strip tagged PDF structure (contains ActualText/Alt with original text)
xref = doc.pdf_catalog()
doc.xref_set_key(xref, "MarkInfo", "null")
doc.xref_set_key(xref, "StructTreeRoot", "null")
```

#### 2.5 JavaScript Cleanup

**File: `src/core/redactor.py`** — add to `_strip_metadata()`

**Research spike required**: The JavaScript name tree in PDF is accessed via the `/Names` dictionary in the document catalog. `doc.xref_get_key()` returns `(type_string, value_string)` tuples, and parsing indirect references from raw PDF strings requires multiple xref lookups. The implementation needs to:

1. Get the catalog xref: `cat_xref = doc.pdf_catalog()`
2. Get the Names dictionary reference: `names_type, names_val = doc.xref_get_key(cat_xref, "Names")`
3. If `names_type` is an indirect reference, resolve it to get the Names dict xref
4. Set the JavaScript key to null on that resolved xref: `doc.xref_set_key(names_xref, "JavaScript", "null")`

**Fallback plan**: If xref traversal proves too complex or fragile, an alternative is to clear the entire `/Names` entry from the catalog. This also removes named destinations and embedded file references (embedded files are already deleted separately). Since the output is a redacted copy (not the original), losing named destinations is acceptable. In that case:
```python
doc.xref_set_key(cat_xref, "Names", "null")
```

The implementing agent should try the targeted approach first, fall back to the nuclear option if needed, and document which approach was used.

#### 2.6 Widget Deletion on All Pages

**File: `src/core/redactor.py`**

Move `_delete_pii_widgets(page, redacted_texts)` out of the `for page_num, items in redactions_by_page.items()` loop. After the main redaction loop completes, run a separate loop:

```python
# Collect ALL redacted texts across all pages
all_redacted_texts = set()
for items in redactions_by_page.values():
    for item in items:
        all_redacted_texts.add(item.text.lower())

for page in doc:
    self._delete_pii_widgets(page, all_redacted_texts)
```

**Note**: This changes `redacted_texts` from a per-page list to a global set. For short/ambiguous PII strings (e.g., a 3-letter name like "Amy"), this could match unrelated widget values on other pages. This is acceptable — a false-positive widget deletion on a redacted copy is preferable to a missed PII widget. The user reviews the original, not the redacted copy.

#### 2.7 Form XObject Image Scanning

**File: `src/core/redactor.py`**

**Research spike required**: PyMuPDF does NOT have `page.get_xobjects()` or `doc.extract_xobject()` methods. To scan images inside Form XObjects, the implementation must walk the page's resource dictionary via low-level xref manipulation:

1. Get the page's xref: `page_xref = page.xref`
2. Read the XObject dictionary: `doc.xref_get_key(page_xref, "Resources/XObject")`
3. For each XObject entry, check if its `/Subtype` is `/Form`
4. If so, read the Form XObject's own `/Resources/XObject` dictionary for image references
5. Extract each image via its xref and `doc.extract_image(img_xref)`
6. Run the existing OCR + redact pipeline from `_match_and_redact_ocr_words()`

This is non-trivial and may require a research spike during implementation to confirm the exact PyMuPDF xref traversal API. The implementing agent should:
- First verify the API approach works with a test PDF containing a Form XObject with an embedded image
- If xref traversal proves unreliable, document the limitation and skip this item (it's the lowest-incidence item in Phase 2)

#### 2.8 Optional Content Groups — Force Visible

**File: `src/core/redactor.py`**

**Research spike required**: PyMuPDF does NOT have `doc.get_ocgs()` or `doc.set_oc(xref, on=True)` with those signatures. The actual API for OCG manipulation involves:

- `doc.get_layer()` — returns layer configuration
- `doc.set_layer_ui_config()` — modifies layer visibility
- Direct xref manipulation of the `/OCProperties` dictionary in the catalog

The implementing agent should:
1. Check the PyMuPDF docs (use context7 MCP) for the current OCG API
2. Test with a PDF that has hidden layers
3. If the API is too complex or unreliable, an alternative approach is: after detection, check if `doc.get_ocgs()` (or equivalent) returns any OCGs, and if so, log a warning in the audit log noting that the document contains hidden layers that may not have been fully scanned

At minimum, `page.get_text()` in PyMuPDF's default mode extracts text from ALL optional content groups (both visible and hidden), so detection of text-layer content on hidden layers already works. The gap is only for content in annotation dictionaries on hidden layers, which is a very low-probability scenario.

#### 2.9 Verification Failure Quarantine

**File: `src/services/redaction_service.py`**

When `verify_redaction_ocr()` returns failures:

```python
if not all_clean:
    result.verification_failures = ocr_failures
    result.success = False
    # Quarantine the suspect file
    quarantine_path = output_path.with_suffix('.UNVERIFIED.pdf')
    output_path.rename(quarantine_path)
    result.output_path = None  # Clear path — don't show to user
    result.quarantine_path = str(quarantine_path)
```

**Frontend handling**: The React completion screen (`desktop/src/pages/`) needs to handle `output_path: null` with `quarantine_path` present. Display a warning: "This document could not be fully verified. An unverified copy was saved as [quarantine filename]. Please review it manually before sharing." This is a minor frontend change — the completion screen already handles `success: false` cases.

---

### Phase 3: Test Coverage

#### 3.1 End-to-End Integration Tests

**New file: `tests/test_integration.py`**

Test the full `RedactionService.execute()` pipeline:

- Create a multi-page PDF programmatically with known PII:
  - Page 1: Student name in body text, email in a link annotation, phone number
  - Page 2: DOB with label on separate line, parent name after "Mother:" keyword on next line
  - Page 3: Address split across two lines, Medicare number after keyword on next line
  - Page 4: Name in a sticky note annotation, name in a bookmark title
  - Page 5: Image-only page with OCR text containing a name
- Run `RedactionService.execute()` with known inputs
- Open output PDF and verify:
  - `page.get_text()` contains no PII strings on any page
  - `page.get_links()` contains no PII URIs
  - `page.annots()` contains no PII in Contents/Title
  - `doc.get_toc()` contains no PII in bookmark titles
  - `doc.metadata` is clean
  - No StructTreeRoot exists
  - Widget values on all pages are clean
  - OCR re-scan of each page finds no PII

#### 3.2 Bbox Redaction Path Tests

**New file: `tests/test_bbox_redaction.py`**

- Create PDF with known text at known coordinates
- Create `RedactionItem` objects with explicit bboxes
- Run `_redact_bbox()`
- Verify black rectangle placed at correct coordinates
- Verify text no longer appears in `page.get_text()`

#### 3.3 Real-Tesseract OCR Integration Tests

**File: `tests/test_ocr_redaction.py`**

Activate the existing `_make_image_pdf_with_text()` helper (line 67 — currently unused). Add tests marked with `@pytest.mark.skipif(not shutil.which('tesseract'))`:

- Create image-only PDF with drawn text "John Smith 0412 345 678"
- Run full OCR detection + redaction
- OCR the output and verify PII strings absent

#### 3.4 Adversarial Input Tests

**New file: `tests/test_adversarial.py`**

- Unicode lookalike: PDF containing "Jаne" (Cyrillic а) — NFKC does NOT normalise Cyrillic to Latin. This is a known limitation. Test documents it.
- Zero-width characters: "Jane\u200BSmith" — NFKC strips some zero-width chars. Test that.
- PII in bookmark titles — verify `_redact_bookmarks()` catches it
- PII in sticky note — verify `_delete_pii_annotations()` catches it
- PII in link URI — verify `_delete_pii_links()` catches it
- PII at exact header zone boundary (12.0% mark, constant is `HEADER_ZONE_FRACTION` in code)
- Multi-page document with PII on pages 1, 5, and 10

#### 3.5 False-Positive Regression Tests

**New file: `tests/test_false_positives.py`**

- "ASD123 assessment scale" — should NOT flag as Student ID. Add common educational acronyms to an exclude list: ASD, IEP, ODD, ADD, PDF, NSW, VIC, QLD
- "He studies English and Art" — NER PERSON entities for subject names should be filtered via a subject-name exclusion list
- "Score: 0412" in a table — should NOT flag as phone (phone patterns should require 10 digits total for mobile numbers starting with 04)
- Organisation words: "The Active program" when org name is "Active Learning Centre" — "Active" alone should not be flagged in generic context

#### 3.6 Cross-Engine Dedup Tests

**File: `tests/test_pii_orchestrator.py`**

- NER finds "Jane Smith", regex finds "Jane" and "Smith" separately — all three survive dedup (different texts)
- NER-discovered name gets variations generated — verify "J. Smith", "Smith's", etc. appear in results
- Confidence tie-breaking is deterministic (add test for equal-confidence matches)

---

### Phase 4: Bundle Simplification

#### 4.1 Remove GLiNER

- Remove `gliner>=0.2.0` from `requirements-desktop.txt`
- Remove `src/core/gliner_provider.py`
- Remove `tests/test_gliner_provider.py`
- Remove GLiNER initialisation and references from `src/core/pii_orchestrator.py`
- Remove GLiNER labels and category mapping

#### 4.2 Update Bundle Scripts and Verify Size

- `scripts/bundle-python-mac.sh`: PyTorch may or may not be removed by dropping GLiNER. **spaCy's `thinc` backend can optionally use torch**, so torch might still be pulled as a transitive dependency of spaCy. The implementing agent must:
  1. Run `pip install presidio-analyzer spacy` (without GLiNER) in an isolated venv
  2. Check if `torch` appears in the installed packages: `pip list | grep torch`
  3. If torch is still present, investigate whether it can be excluded (e.g., `pip install spacy --no-deps` + manual dependency install, or checking if `thinc` works without torch)
  4. Document the actual bundle size reduction achieved
- `scripts/bundle-python-win.ps1`: Same verification.

If torch cannot be removed without breaking spaCy, the installer size reduction will be smaller than the ~350-400MB target. This is acceptable — the primary goal of Phase 4 is removing a redundant NER engine and its runtime model download dependency, not hitting a specific size target.

#### 4.3 Update Documentation

- Update CLAUDE.md: remove GLiNER references, update architecture diagram to show two-engine pipeline, update confidence table, update dependency list
- Update README.md if it references GLiNER

---

## File Change Summary

| File | Change Type | Phase |
|------|------------|-------|
| `src/core/text_extractor.py` | Modify — NFKC normalisation, smart quotes, OCR line preservation | 1 |
| `src/core/pii_orchestrator.py` | Modify — NER-primary architecture, remove GLiNER, require_ner flag | 1, 4 |
| `src/core/pii_detector.py` | Modify — new patterns, cross-line lookahead (signature changes to 5 methods), ALL-CAPS, smart quotes, nickname lookup, Student ID exclude list | 1 |
| `src/core/nickname_map.py` | **New** — curated nickname dictionary with false-positive guards | 1 |
| `src/core/presidio_recognizers.py` | Modify — add missing street types to address recognizer | 1 |
| `src/services/detection_service.py` | Modify — accept and pass `require_ner` parameter | 1 |
| `src/core/gliner_provider.py` | **Delete** | 4 |
| `src/core/redactor.py` | Modify — link/annotation/bookmark cleanup, structure tree stripping, JS cleanup, widget on all pages, Form XObject scanning (research spike), OCG handling (research spike) | 2 |
| `src/services/redaction_service.py` | Modify — verification quarantine | 2 |
| `backend/main.py` | Modify — pass require_ner=True to DetectionService | 1 |
| `desktop/src/pages/Setup.tsx` | Modify — NER failure blocking error | 1 |
| `desktop/src/pages/` (completion screen) | Modify — handle quarantine_path in UI | 2 |
| `requirements-desktop.txt` | Modify — remove gliner | 4 |
| `scripts/bundle-python-mac.sh` | Modify — verify size reduction, check torch dependency | 4 |
| `scripts/bundle-python-win.ps1` | Modify — verify size reduction, check torch dependency | 4 |
| `tests/test_integration.py` | **New** — E2E pipeline tests | 3 |
| `tests/test_bbox_redaction.py` | **New** — bbox path tests | 3 |
| `tests/test_adversarial.py` | **New** — adversarial input tests | 3 |
| `tests/test_false_positives.py` | **New** — false-positive regression tests | 3 |
| `tests/test_ocr_redaction.py` | Modify — activate real-Tesseract tests | 3 |
| `tests/test_pii_orchestrator.py` | Modify — cross-engine dedup + NER variation tests | 3 |
| `tests/test_pii_detector.py` | Modify — update method signatures for cross-line lookahead | 3 |
| `tests/test_pii_detector_names.py` | Modify — update method signatures for cross-line lookahead | 3 |
| `tests/test_gliner_provider.py` | **Delete** | 4 |
| `CLAUDE.md` | Modify — update architecture, dependencies, confidence table | 4 |

---

## Execution Notes for Implementation Session

This spec is designed to be executed in a new Claude Code session using parallel sub-agents for maximum efficiency. The four phases have these dependencies:

```
Phase 1 (Detection) ──┐
                       ├──→ Phase 3 (Tests) — tests need the new detection + hardening code
Phase 2 (PDF Hardening)┘
Phase 4 (Bundle) — independent, can run in parallel with Phase 1+2
```

**Important coordination note**: Phase 1 and Phase 2 modify mostly different files, but they share an integration point: Phase 1 changes what gets detected (more matches), and Phase 2 changes how those matches are redacted (more PDF structures cleaned). They can be coded in parallel but must be tested together before Phase 3. The `redactor.py` file is modified by Phase 2 only — Phase 1 does not touch it.

Recommended execution strategy:
- **Wave 1**: Launch Phase 1 and Phase 2 as parallel sub-agents (they modify different files — Phase 1 touches detection code, Phase 2 touches redaction code). Launch Phase 4 as a third parallel agent (fully independent — only touches GLiNER removal and bundle scripts).
- **Wave 2**: After Wave 1 completes, run existing tests to verify no regressions. Then launch Phase 3 (new tests need the new code to exist).
- **Wave 3**: Run the full test suite (`pytest tests/ -v`). Fix any failures.

**Skills and tools to use during implementation**:
- `superpowers:dispatching-parallel-agents` — for Wave 1 parallelisation
- `feature-dev:code-architect` agents — for planning each phase's detailed file edits before coding
- `feature-dev:code-explorer` agents — to verify file dependencies and current API signatures before editing
- `superpowers:test-driven-development` — for Phase 3 test writing
- `superpowers:verification-before-completion` — run tests before claiming any phase is done
- `coderabbit:code-review` or `superpowers:requesting-code-review` — after each wave completes
- `mcp__Context7__resolve-library-id` + `mcp__Context7__get-library-docs` — for PyMuPDF API verification during research spikes (Phase 2.5, 2.7, 2.8)

**Research spikes in Phase 2**: Items 2.5 (JavaScript cleanup), 2.7 (Form XObject images), and 2.8 (OCG handling) require PyMuPDF API research before implementation. The implementing agent should use Context7 MCP to look up current PyMuPDF documentation for these APIs. Each has a fallback plan documented above if the primary approach proves infeasible.
