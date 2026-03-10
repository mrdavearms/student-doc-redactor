# CLAUDE.md — Bulk Redaction Tool

> Project-level context for Claude Code. Supplements the global `~/.claude/CLAUDE.md`.

## Project Overview

A local Mac Streamlit app that redacts PII from student assessment PDFs and Word documents. Built for Australian teachers and school psychologists. All processing is local — no internet, no cloud services at runtime.

- **Repo**: https://github.com/mrdavearms/student-doc-redactor (primary) · https://gitlab.com/davearmswork/bulk-redaction-tool (mirror)
- **Branches**: `test` (development) → `main` (stable). Always push to `test` first, then to `main`.
- **Run**: `source venv/bin/activate && streamlit run app.py`
- **Test**: `source venv/bin/activate && pytest tests/ -v` (142 tests, ~30s)
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
| `src/core/redactor.py` | PyMuPDF redaction, metadata stripping, OCR verification |
| `src/core/text_extractor.py` | Text + OCR extraction from PDFs |
| `src/core/document_converter.py` | LibreOffice Word → PDF conversion |
| `src/core/logger.py` | Audit log generation and save |
| `src/core/session_state.py` | All `st.session_state` keys and `navigate_to()` |
| `src/ui/screens.py` | All 5 Streamlit screens (largest file) |

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

### 11. OCR pages cannot be automatically redacted

`page.search_for()` returns nothing on image-only pages. When OCR pages are detected, a warning is added to `st.session_state.ocr_warnings` and the user is shown a banner. These pages require manual redaction.

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

---

## Test Structure

```
tests/
├── test_pii_detector.py         # 39 tests: phone, email, address, Medicare, CRN, Student ID, DOB, integration
├── test_pii_detector_names.py   # 44 tests: name variations, name detection, contextual detection
├── test_pii_orchestrator.py     # Orchestrator merge and dedup logic
├── test_presidio_recognizers.py # 6 AU recognizers unit tests
├── test_gliner_provider.py      # GLiNER wrapper tests
├── test_metadata_stripping.py   # PDF metadata removal tests
└── test_ocr_verification.py     # OCR post-redaction verification tests
```

Tests use `sys.path.insert` to locate `src/core/` modules — this is required because the test runner runs from the repo root, not from within `src/`.

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
- **Windows/Linux**: Not supported. macOS only.
- **Fuzzy name matching**: Comment in `pii_detector.py` notes this as a future feature.
- **Signature detection**: Listed in roadmap, not implemented.
- **Batch processing** (multiple students at once): Not implemented.
- **`venv_old/`**: Legacy venv from Python 3.14 era. Not used. Can be deleted once confirmed stable on 3.13 venv.
- **`GITHUB_SETUP.md`, `GIT_WORKFLOW.md`, `FINAL_SUMMARY.md`**: Legacy docs from early development. Outdated — may reference implementation details that have changed. README.md is now the authoritative user documentation.

---

## Sample Data

`sample/` contains real documents. This repo is private. Do not make it public until sample documents are removed or replaced with synthetic data. The `sample/redacted_2/` and `sample/redaction_log.txt` files are in `.gitignore` (output files — never commit these).
