# CLAUDE.md — Bulk Redaction Tool

> Project-level context for Claude Code. Supplements the global `~/.claude/CLAUDE.md`.

## Project Overview

A local Mac Streamlit app that redacts PII from student assessment PDFs and Word documents. Built for Australian teachers and school psychologists. All processing is local — no internet, no cloud services at runtime.

- **Repo**: https://github.com/mrdavearms/student-doc-redactor (primary) · https://gitlab.com/davearmswork/bulk-redaction-tool (mirror)
- **Branches**: `test` (development) → `main` (stable). Always push to `test` first, then to `main`.
- **Run**: `source venv/bin/activate && streamlit run app.py`
- **Test**: `source venv/bin/activate && pytest tests/ -v` (239 tests, ~4m30s)
- **Python**: 3.13+ (required for spaCy compatibility — the `venv/` dir uses 3.13, `venv_old/` is a legacy 3.14 venv that can be ignored)

---

## Architecture

### Detection Pipeline

The entry point for all PII detection is `PIIOrchestrator`, not `PIIDetector` directly. Screens always use the orchestrator.

```
PIIOrchestrator
├── PIIDetector          (regex — always runs)
├── Presidio + spaCy     (NER — runs if installed, graceful degradation if not)
└── GLiNERDetector       (zero-shot NER — runs if installed, graceful degradation if not)
      ↓
  _deduplicate()         (same text + page + line → keep highest confidence)
      ↓
  List[PIIMatch]         (sorted by confidence desc)
```

All three engines produce `PIIMatch` objects. The orchestrator merges and deduplicates by `(text.lower(), page_num, line_num)`.

### Redaction Pipeline

`redactor.py` handles the actual redaction. It uses **dual paths** based on page type:

```
redact_pdf(input_pdf, output_pdf, redaction_items)
│
├── For each page:
│   ├── _is_image_only_page(page)?
│   │   ├── YES → _redact_ocr_page(page, items)    # PIL ImageDraw path
│   │   └── NO  → _redact_text_search(page, text)  # PyMuPDF annotation path
│   │             + page.apply_redactions(images=PDF_REDACT_IMAGE_NONE)
│   │
│   └── _delete_pii_widgets(page, redacted_texts)   # AcroForm cleanup (always)
│
├── _strip_metadata(doc)                             # Author, XMP, embedded files
└── doc.save(output_pdf)
```

The service layer (`src/services/redaction_service.py`) orchestrates this and handles filename redaction, OCR warnings, and audit log entries.

### Screen Flow

`app.py` routes based on `st.session_state.current_screen`:

```
folder_selection → conversion_status → document_review → final_confirmation → completion
```

Navigation is handled by `session_state.navigate_to(screen_name)`, which sets the screen key and calls `st.rerun()`.

### Key Files

| File | Purpose |
|------|---------|
| `app.py` | Entry point, CSS, screen router |
| `src/core/pii_orchestrator.py` | **Main detection entry point** — merges all engines |
| `src/core/pii_detector.py` | Regex engine + `PIIMatch` dataclass definition |
| `src/core/presidio_recognizers.py` | 6 custom Australian Presidio recognizers |
| `src/core/gliner_provider.py` | GLiNER zero-shot NER wrapper |
| `src/core/redactor.py` | **Dual-path redaction** (text-layer + OCR image), widget deletion, metadata stripping |
| `src/core/text_extractor.py` | Text + OCR extraction from PDFs |
| `src/core/document_converter.py` | LibreOffice Word → PDF conversion |
| `src/core/binary_resolver.py` | Cross-platform Tesseract/LibreOffice path resolution |
| `src/core/logger.py` | Audit log generation and save |
| `src/core/session_state.py` | All `st.session_state` keys and `navigate_to()` |
| `src/ui/screens.py` | All 5 Streamlit screens (largest file) |
| `src/services/conversion_service.py` | Framework-agnostic conversion business logic |
| `src/services/detection_service.py` | Framework-agnostic PII detection business logic |
| `src/services/redaction_service.py` | Framework-agnostic redaction orchestration |
| `backend/main.py` | FastAPI API layer for desktop app (Phase 2) |
| `desktop/` | Electron + React + Vite frontend (Phase 2) |

---

## Critical Non-Obvious Rules

### 1. `navigate_to()` must NEVER be inside a `with st.spinner():` block

`navigate_to()` calls `st.rerun()`, which raises `RerunException`. If called inside a `with st.spinner()` context manager, the `__exit__` never runs cleanly. Always structure like this:

```python
# CORRECT
if st.button("Continue"):
    with st.spinner("Processing..."):
        do_the_work()
    session_state.navigate_to('next_screen')  # OUTSIDE the spinner

# WRONG — will cause issues
if st.button("Continue"):
    with st.spinner("Processing..."):
        do_the_work()
        session_state.navigate_to('next_screen')  # inside spinner = bad
```

### 2. `PIIMatch.confidence` is a float (0.0–1.0), not a string

Changed in commit `a699268`. It was previously `'high'`/`'medium'`/`'low'`. There is a `confidence_label` property on `PIIMatch` that maps to those strings for display. Tests were updated to reflect this. Don't revert to string confidence values.

```python
match.confidence        # float: 0.95, 0.65, etc.
match.confidence_label  # property: 'high' | 'medium' | 'low'
```

### 3. `PIIMatch` has a `source` field

Added in `a699268`. Values: `'regex'`, `'presidio'`, `'gliner'`. Used by the orchestrator for deduplication logic. Don't remove it.

### 4. Medicare detection requires 'medicare' in the same line

`_detect_medicare()` returns early if `'medicare' not in line.lower()`. This is intentional — prevents false positives from any 10-digit number sequence. Don't remove this guard.

### 5. DOB detection requires a label on the same line

`_detect_dob()` only fires if a DOB label (DOB, Date of Birth, Born, etc.) appears on the same line as the date. Standalone dates are not flagged. Intentional.

### 6. Student ID requires 3+ digits (not 1+)

`STUDENT_ID_PATTERN = r'\b[A-Z]{3}\d{3,}\b'` — the `{3,}` is deliberate. `FEN12` should NOT match. `FEN123` should. Don't change to `\d+`.

### 7. Name variations filter: min 3 chars, but always preserve `self.student_name`

```python
variations = [v for v in variations if len(v) >= 3 or v == self.student_name]
```

The `or v == self.student_name` guard is important for students with short names (e.g. "Jo"). Don't remove it.

### 8. Presidio and GLiNER are optional dependencies

Both `_init_presidio()` and `_init_gliner()` catch all exceptions and set the detector to `None`. The app degrades gracefully to regex-only detection. This is by design — don't add hard failures.

### 9. There are two redaction verification methods

- `verify_redaction(pdf_path, text)` — fast, text-layer only. Used in the main redaction flow for spot-checking.
- `verify_redaction_ocr(pdf_path, texts)` — slow, renders at 300 DPI and OCRs. More thorough. Used for comprehensive post-redaction checks.

### 10. Metadata stripping happens inside `redact_pdf()`

`_strip_metadata()` is called inside `redact_pdf()` before `doc.save()`. It strips author, title, subject, creator, producer, keywords, creation date, modification date, XMP metadata, and embedded files. It always runs — not optional.

### 11. OCR pages ARE automatically redacted via `_redact_ocr_page()`

**This rule was rewritten in March 2026. The previous version said OCR pages "cannot be automatically redacted" — that is no longer true.**

Image-only pages (detected by `_is_image_only_page()`: no text words, but images present) are redacted using a completely different code path from text-layer pages:

```python
# Text-layer pages:
page.add_redact_annot(rect)
page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

# Image-only pages:
_redact_ocr_page(page, items)  # renders → OCR → PIL ImageDraw → replace page
```

The OCR redaction pipeline:
1. `page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))` — render at 300 DPI
2. `pytesseract.image_to_data()` — OCR with bounding boxes
3. Compare each OCR word against PII using cleaned matching
4. `ImageDraw.rectangle()` — draw filled black rectangles on PIL image
5. Replace page content: `page.clean_contents()` → clear content streams → `page.insert_image()`

OCR warnings are now **informational** (not error/skip signals). The audit log notes which pages used OCR redaction.

### 12. Every embedded image is OCR-scanned for PII (Stage 2)

After text-layer redaction, `_redact_embedded_images()` runs on every page. It extracts each embedded image via `doc.extract_image(xref)`, OCRs it with pytesseract, blacks out PII matches in the image pixels using PIL, and replaces the original via `page.replace_image(xref, stream=png_bytes)`. This catches PII in email screenshots, scanned documents, and even small logos. No image is too small to scan — there is no size threshold.

### 13. OCR word-matching logic is shared via `_match_and_redact_ocr_words()`

Both `_redact_ocr_page()` (full-page image-only OCR) and `_redact_embedded_images()` (per-image OCR) use the same matching helper. Any change to matching rules (possessives, punctuation, email substring, etc.) must be made in `_match_and_redact_ocr_words()` to affect both paths.

### 14. NEVER use `fitz.PDF_REDACT_IMAGE_REMOVE` on scanned PDFs

`page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)` will **delete the entire full-page scan image**, leaving a blank white page. This is catastrophic for scanned documents where each page IS a single image.

Always use `images=fitz.PDF_REDACT_IMAGE_NONE` for text-layer redactions, and use the `_redact_ocr_page()` PIL ImageDraw path for image-only pages.

### 15. OCR word matching has two modes — cleaned and exact

In `_redact_ocr_page()`, OCR words are matched against PII using:

```python
# Cleaned match (for names — strips punctuation, handles possessives):
ocr_clean = re.sub(r"[^\w'\u2019]", '', ocr_lower)
if ocr_clean == pii_lower or ocr_clean == pii_lower + "'s" or ocr_clean == pii_lower + "\u2019s":

# Exact substring match (for emails/URLs — preserves special chars):
if not pii_lower.isalpha() and pii_lower in ocr_lower:
```

The `not pii_lower.isalpha()` guard prevents the substring match from firing for plain-name PII like "Joe" — otherwise "Joe" would match inside "joe@email.com" as a separate hit, causing double-counting.

### 16. Page content replacement in PyMuPDF requires clearing content streams

When replacing a page's visual content (for OCR redaction), you can't just insert an image — the old content streams must be cleared first:

```python
page.clean_contents()  # Consolidates content streams
doc = page.parent
for xref in page.get_contents():
    doc.update_stream(xref, b"")  # Clear each content stream
page.insert_image(page.rect, stream=img_bytes, overlay=True)
```

**Do NOT use `page._cleanContents()`** — this private API does not exist in current PyMuPDF versions. The public `page.clean_contents()` plus content stream clearing handles the same job.

### 17. Form widget (AcroForm) deletion runs after text/OCR redaction

`_delete_pii_widgets()` iterates over `page.widgets()` and deletes any widget whose field value matches redacted PII text. This runs AFTER text-layer or OCR redaction, as a separate pass. It catches PII stored in interactive form fields that are invisible to `page.search_for()`.

### 18. Filename PII redaction is handled by the service layer

`redaction_service.py` checks if the student name appears in document filenames. If found, the output filename has PII replaced with `[REDACTED]`. This logic is in the service layer, not in `redactor.py`.

### 19. Organisation names generate word-level variations

`PIIDetector._detect_organisation_names()` splits each org name into words and flags matches ≥3 chars. Common English words (`the`, `school`, `centre`, `clinic`, etc.) are excluded via `GENERIC_ORG_WORDS`. The full org name is matched first (longest match first, like student names). Category: `"Organisation name"`, confidence: `0.90`.

### 20. Header/footer zone redaction ("Stage 0") blanks regions before PII redaction

When `redact_header_footer=True`, `_redact_zones()` runs before any PII redaction. It blanks the top 12% (`HEADER_ZONE_RATIO = 0.12`) and bottom 8% (`FOOTER_ZONE_RATIO = 0.08`) of every page. Text-layer pages use `add_redact_annot()` + `apply_redactions()`; image-only pages use PIL `ImageDraw.rectangle()`. This removes school letterheads, addresses, and logos without needing to detect them as named PII.

---

## Session State Keys

All keys initialised in `session_state.init_session_state()`:

| Key | Type | Purpose |
|-----|------|---------|
| `current_screen` | str | Screen router key |
| `folder_path` | Path | Selected folder |
| `student_name` | str | Student's full name |
| `parent_names` | str | Comma-separated parent names |
| `family_names` | str | Comma-separated family names |
| `documents` | list | Found PDF paths |
| `conversion_results` | dict | Word → PDF conversion outcomes |
| `flagged_files` | list | Files flagged for manual review |
| `detected_pii` | dict | PII matches keyed by document |
| `current_doc_index` | int | Which document is being reviewed |
| `user_selections` | dict | Per-document user approval choices |
| `global_decisions` | dict | Bulk approve/reject decisions |
| `redacted_folder` | Path | Output folder path |
| `log_content` | str | Audit log string |
| `organisation_names` | str | Comma-separated organisation names |
| `redact_header_footer` | bool | Whether to blank header/footer zones |
| `processing_complete` | bool | Completion flag |
| `verification_failures` | list | (filename, text) tuples where verification failed |
| `ocr_warnings` | list | (filename, count) tuples for OCR page warnings |

---

## Detection Confidence Values (Regex Engine)

| Category | Confidence | Rationale |
|----------|-----------|-----------|
| Student name | 0.95 | High — word-boundary matched against known name |
| Phone number | 0.95 | High — structured Australian pattern |
| Email address | 0.95 | High — standard pattern |
| Address | 0.95 | High — requires state + postcode |
| Medicare number | 0.95 | High — contextual guard required |
| Date of birth | 0.95 | High — label required |
| Student ID (surname match) | 0.95 | High — prefix matches student surname |
| Student ID (no surname match) | 0.65 | Medium — pattern only, prefix mismatch |
| Centrelink CRN | 0.65 | Medium — contextual guard, pattern is broad |
| Family/parent (contextual) | 0.65 | Medium — inferred from keyword proximity |
| Parent/family (user-provided) | 0.95 | High — user explicitly named them |
| Organisation name | 0.90 | High — user-provided, word-level matching with generic word filter |

---

## Test Structure

```
tests/                                # 239 tests total
├── test_pii_detector.py              # 39 tests: phone, email, address, Medicare, CRN, Student ID, DOB
├── test_pii_detector_names.py        # 54 tests: name variations, contextual detection, possessives, family
├── test_pii_orchestrator.py          # 22 tests: orchestrator merge, dedup, multi-engine coordination
├── test_presidio_recognizers.py      # 18 tests: 6 custom AU Presidio recognizer unit tests
├── test_gliner_provider.py           # 12 tests: GLiNER zero-shot NER wrapper
├── test_redactor.py                  # 9 tests: text-layer redaction routing, metadata, core redact_pdf
├── test_ocr_redaction.py             # 19 tests: image-only page detection, OCR redaction, word matching
├── test_ocr_verification.py          # 7 tests: post-redaction OCR verification (300 DPI re-scan)
├── test_metadata_stripping.py        # 8 tests: PDF metadata removal (author, XMP, embedded files)
├── test_widget_redaction.py          # 6 tests: AcroForm widget deletion
├── test_filename_redaction.py        # 13 tests: PII in filenames → [REDACTED] replacement
├── test_zone_redaction.py            # 5 tests: header/footer zone blanking (Stage 0)
├── test_session_state.py             # 2 tests: session state key initialisation
└── test_binary_resolver.py           # 6 tests: cross-platform Tesseract/LibreOffice path resolution
```

Tests use `sys.path.insert` to locate `src/core/` modules — this is required because the test runner runs from the repo root, not from within `src/`.

**OCR redaction tests** (`test_ocr_redaction.py`) mock `pytesseract.image_to_data` to return controlled word bounding boxes, avoiding a hard dependency on Tesseract being installed in the test environment. They test the matching logic (cleaned vs exact, possessives, email/URL handling) and the page-type routing (text-layer vs OCR path).

Run a single test file: `pytest tests/test_pii_detector.py -v`
Run with output: `pytest tests/ -v -s`

---

## Dependencies

### Python (requirements.txt)
- `streamlit>=1.31.0` — UI framework
- `pymupdf>=1.23.0` — PDF redaction (`import fitz`)
- `pytesseract>=0.3.10` — OCR
- `Pillow>=10.2.0` — Image handling for OCR verification
- `python-docx>=1.1.0` — Word file handling
- `presidio-analyzer>=2.2.0` — Microsoft NER framework
- `spacy>=3.7.0` — NLP backend for Presidio
- `gliner>=0.2.0` — Zero-shot NER

### External (installed via Homebrew)
- `LibreOffice` — Word → PDF conversion (`soffice` binary)
- `tesseract` — OCR engine

### Models (downloaded separately)
- `en_core_web_lg` — spaCy large English model (`python -m spacy download en_core_web_lg`)
- `urchade/gliner_multi_pii-v1` — GLiNER model (auto-downloaded on first run, ~10–20s)

---

## LibreOffice Path Discovery

`document_converter.py` checks paths in order:
1. `which soffice` (system PATH)
2. `/opt/homebrew/bin/soffice` (Apple Silicon Homebrew)
3. `/usr/local/bin/soffice` (Intel Mac Homebrew)
4. `/Applications/LibreOffice.app/Contents/MacOS/soffice` (app bundle)

---

## What's Next / Known Gaps

- **Mac `.app` bundle**: App is not yet packaged. Planned via PyInstaller or py2app. See `FINAL_SUMMARY.md`.
- **Windows/Linux (Phase 3)**: Not supported yet. Phase 3 roadmap includes Windows COM automation for Word conversion and bundled Tesseract.
- **Packaging (Phase 4)**: electron-builder for .dmg + .exe not started.
- **Fuzzy name matching**: Comment in `pii_detector.py` notes this as a future feature.
- **Signature detection**: Listed in roadmap, not implemented.
- **Batch processing** (multiple students at once): Not implemented.
- **OCR redaction quality**: Depends entirely on scan quality. Low-DPI or blurry scans may cause missed words. There is no fuzzy OCR matching yet.
- **`venv_old/`**: Legacy venv from Python 3.14 era. Not used. Can be deleted once confirmed stable on 3.13 venv.
- **`GITHUB_SETUP.md`, `GIT_WORKFLOW.md`, `FINAL_SUMMARY.md`**: Legacy docs from early development. Outdated — may reference implementation details that have changed. README.md is now the authoritative user documentation.

---

## Sample Data

`sample/` contains real documents. This repo is private. Do not make it public until sample documents are removed or replaced with synthetic data. The `sample/redacted_2/` and `sample/redaction_log.txt` files are in `.gitignore` (output files — never commit these).
