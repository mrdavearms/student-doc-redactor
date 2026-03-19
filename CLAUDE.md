# CLAUDE.md — Bulk Redaction Tool

> Project-level context for Claude Code. Supplements the global `~/.claude/CLAUDE.md`.

## Project Overview

A local Mac and Windows app that redacts PII from student assessment PDFs and Word documents. Built for Australian teachers and school psychologists. All processing is local — no internet, no cloud services at runtime.

Two frontends exist:
- **Desktop app** (primary): Electron + React + Vite + Tailwind v4, communicating with a FastAPI backend via HTTP. This is the user-facing product.
- **Streamlit app** (legacy): The original prototype in `app.py`. Still functional but no longer the focus.

- **Repo**: https://github.com/mrdavearms/student-doc-redactor (primary) · https://gitlab.com/davearmswork/bulk-redaction-tool (mirror)
- **Branches**: `test` (development) → `main` (stable). Always push to `test` first, then to `main`.
- **Run (desktop)**: `cd desktop && npm run dev:electron` (starts Vite + Electron + auto-spawns backend)
- **Run (backend only)**: `./venv/bin/python3.13 -m uvicorn backend.main:app --port 8765`
- **Run (Streamlit)**: `source venv/bin/activate && streamlit run app.py`
- **Test**: `source venv/bin/activate && pytest tests/ -v` (257 tests, ~4m30s)
- **Build DMG**: `cd desktop && npm run dist:mac`
- **Python**: 3.13+ (required for spaCy compatibility)

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
├── Stage 4: _redact_signature_images(page)          # Heuristic sig detection (ALL pages)
├── _strip_metadata(doc)                             # Author, XMP, embedded files
└── doc.save(output_pdf)
```

The service layer (`src/services/redaction_service.py`) orchestrates this and handles filename redaction, OCR warnings, custom output paths, and audit log entries.

### Desktop App Architecture (Two-Process Model)

Electron spawns FastAPI as a child process. React communicates with the backend via HTTP on `127.0.0.1:8765`.

```
Electron main.cjs
├── Spawns: python3.13 -m uvicorn backend.main:app --port 8765
├── Waits for /api/health → 200 OK
└── Creates BrowserWindow → loads Vite dev server or built files

React (Vite)
├── App.tsx           → screen router (switch on currentScreen)
├── Layout.tsx        → sidebar + animated page transitions (AnimatePresence)
├── store.ts          → Zustand single store (mirrors Streamlit session_state)
├── api.ts            → fetch wrapper for all backend endpoints
├── pages/            → 6 wizard pages (setup + 5 workflow steps)
└── components/       → reusable UI components

FastAPI (backend/main.py)
├── /api/health, /api/dependencies/check
├── /api/folder/process, /api/folder/validate, /api/folder/open
├── /api/pii/detect   → returns matches, caches PIIMatch objects server-side
├── /api/redact       → uses cached detection data + user selections
└── /api/preview      → renders PDF page at 150 DPI, returns base64 PNG
```

### Screen Flow

The desktop app has a 6-screen wizard flow (setup screen + 5 workflow steps):

```
setup → folder_selection → conversion_status → document_review → final_confirmation → completion
```

The `setup` screen checks for LibreOffice and Tesseract on first launch, with install guidance and a "Check Again" button. It is skipped on subsequent launches when dependencies are present.

In the desktop app, `App.tsx` switches on `currentScreen` from the Zustand store. Layout wraps children in `<AnimatePresence mode="wait">` with `key={currentScreen}` for animated transitions.

Streamlit shares the same 5 workflow steps (no setup screen). `app.py` routes based on `st.session_state.current_screen`.

### Key Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit entry point, CSS, screen router |
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
| `src/ui/screens.py` | All Streamlit screens (largest file) |
| `src/services/conversion_service.py` | Framework-agnostic conversion business logic |
| `src/services/detection_service.py` | Framework-agnostic PII detection business logic |
| `src/services/redaction_service.py` | Framework-agnostic redaction orchestration + custom output path |
| `backend/main.py` | FastAPI API layer + server-side detection cache |
| `backend/schemas.py` | Pydantic request/response models |
| `desktop/electron/main.cjs` | Electron main process — spawns backend, creates window |
| `desktop/electron/preload.cjs` | Electron preload — exposes `selectFolder`, `openExternal` to renderer |
| `desktop/src/App.tsx` | React entry point, screen router |
| `desktop/src/store.ts` | Zustand store — single source of truth for UI state |
| `desktop/src/api.ts` | HTTP client for all backend endpoints |
| `desktop/src/components/Layout.tsx` | Main layout with sidebar + animated page transitions |
| `desktop/src/components/Sidebar.tsx` | Step indicator, logo, walkthrough trigger, About modal |
| `desktop/src/components/Walkthrough.tsx` | 4-step first-run onboarding modal |
| `desktop/src/components/HelpTip.tsx` | Reusable `?` icon popover for contextual help |
| `desktop/src/components/AboutModal.tsx` | 3-tab About dialog (About, How to Use, Features) |
| `desktop/src/components/PreviewSection.tsx` | Before/after PDF preview (split view, on-demand fetch) |
| `desktop/src/components/DocumentCard.tsx` | Expandable per-document summary card for completion screen |
| `desktop/src/components/RedactionProgress.tsx` | Animated progress bar + rotating witty teacher comments |
| `desktop/src/components/UpdateBanner.tsx` | Auto-update notification banner |
| `desktop/src/hooks/useUpdater.ts` | Custom hook for electron-updater integration |
| `desktop/src/types.ts` | `Screen` type, `SCREENS` array, API response interfaces |

---

## Critical Non-Obvious Rules

### 1. `navigate_to()` must NEVER be inside a `with st.spinner():` block (Streamlit only)

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

### 21. Signature detection ("Stage 4") runs on ALL pages after PII redaction

`_redact_signature_images(page)` iterates every embedded image on every page and applies a four-gate heuristic via `_is_likely_signature()`:

1. **Aspect ratio** > 2.0 (signatures are wide and thin)
2. **Page width** < 250pt (rejects banners/letterheads)
3. **Pixel dimensions**: width > 50px AND height < 200px (rejects icons and full-page scans)
4. **Ink ratio** < 30% (signatures are mostly white space; photos have high ink)

Ink ratio is computed by converting to grayscale and counting pixels below a darkness threshold (< 128). Matching images are replaced with solid black PNGs via `page.replace_image(xref, stream=...)`.

Stage 4 runs on ALL pages, not just pages with detected PII — signatures often appear on pages with no other flagged content. The class-level threshold constants (`SIGNATURE_MIN_ASPECT`, `SIGNATURE_MAX_RECT_WIDTH`, etc.) can be tuned without changing the method logic.

### 22. `_is_whole_word_match()` handles possessive+punctuation combinations

The short-word guard (for texts ≤6 chars) uses a regex to validate the suffix after a needle match:

```python
remainder = word_clean[len(needle):]
if re.fullmatch(r"(?:['\u2019]s)?[^a-zA-Z0-9]*", remainder):
```

This single regex handles: exact matches (empty remainder), possessives (`'s`), trailing punctuation (`,` `.` `)`), and combined forms like `'s,` or `'s.`. Previously, three separate conditions missed the combined possessive+punctuation case (e.g. "Joe's," was not redacted).

### 23. Desktop: `<Walkthrough />` must NOT be inside Layout's animated children

Layout wraps children in `<motion.div key={currentScreen}>` inside `<AnimatePresence mode="wait">`. When the screen changes, React unmounts/remounts the entire children block. Any component rendered inside this area will remount on every screen change. The Walkthrough component (first-run onboarding) must live in Sidebar (which is outside the animated area and never remounts) — NOT in App.tsx children. The first-run check uses `localStorage` with key `walkthrough_dismissed`.

### 24. Desktop: Preview images must NEVER be stored in the Zustand store

The before/after PDF preview (`PreviewSection.tsx`) fetches page images as base64 PNGs via `/api/preview`. These images contain actual document content (potentially including PII). They must be kept in **React component state only** (`useState`) — never in the Zustand store, which would persist them across screen transitions. When the component unmounts, the images are garbage collected.

### 25. Desktop: Server-side detection cache bridges detect → redact

`_detection_cache` in `backend/main.py` keeps full `PIIMatch` objects (with bboxes) between the detect and redact API calls. The frontend only sends back selection keys (`"docPath_idx"`) — not the full match data. The cache is cleared on each new detection run. If the cache is missing when redact is called, the backend returns HTTP 400.

### 26. Desktop: `custom_output_path` overrides default subfolder

`RedactionRequest.custom_output_path` (added March 2026) allows users to save redacted files to any location. When set, `_prepare_output_folder()` uses it directly with `mkdir(parents=True, exist_ok=True)`, bypassing the normal `redacted/` subfolder logic and the `folder_action` parameter entirely.

### 27. Desktop: Tailwind v4 uses `@theme` block, not `tailwind.config.js`

The desktop app uses `@tailwindcss/vite` plugin with `@import "tailwindcss"` and a `@theme` block in `index.css`. There is no `tailwind.config.js` file. Custom colours (e.g. `--color-primary-*`) are defined in the `@theme` block. The `.btn-press` utility class (active scale effect) is defined in `index.css`.

---

## Session State Keys (Streamlit)

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

## Zustand Store Keys (Desktop)

Single store in `desktop/src/store.ts`. `setDetectionResults` auto-initialises all selections to `true`.

| Key | Type | Purpose |
|-----|------|---------|
| `currentScreen` | Screen | Active wizard step |
| `folderPath` | string | Selected input folder |
| `studentName` | string | Student full name |
| `parentNames` | string | Comma-separated parent names |
| `familyNames` | string | Comma-separated family names |
| `organisationNames` | string | Comma-separated organisation names |
| `redactHeaderFooter` | boolean | Blank header/footer zones |
| `folderValid` | boolean | Whether folder path is valid |
| `conversionResults` | ConversionResults \| null | Word → PDF conversion outcomes |
| `detectionResults` | DetectionResults \| null | PII detection results (all documents) |
| `currentDocIndex` | number | Which document is being reviewed |
| `userSelections` | Record<string, boolean> | `"docPath_matchIdx"` → selected |
| `redactionResults` | RedactionResults \| null | Final redaction outcomes |
| `loading` | boolean | Generic loading overlay active |
| `loadingMessage` | string | Loading overlay text |
| `error` | string \| null | Global error toast message |

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
| Organisation name | 0.95 | High — user-provided, word-level matching with generic word filter |

---

## Test Structure

```
tests/                                # 257 tests total
├── test_pii_detector.py              # 39 tests: phone, email, address, Medicare, CRN, Student ID, DOB
├── test_pii_detector_names.py        # 61 tests: name variations, contextual detection, possessives, family
├── test_pii_orchestrator.py          # 25 tests: orchestrator merge, dedup, multi-engine coordination
├── test_presidio_recognizers.py      # 18 tests: 6 custom AU Presidio recognizer unit tests
├── test_gliner_provider.py           # 12 tests: GLiNER zero-shot NER wrapper
├── test_redactor.py                  # 11 tests: text-layer redaction routing, possessive+punctuation, core redact_pdf
├── test_signature_detection.py       # 16 tests: heuristic signature detection (unit + integration)
├── test_ocr_redaction.py             # 28 tests: image-only page detection, OCR redaction, word matching
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

### Python (two requirements files)

**`requirements.txt`** (Streamlit app):
- `streamlit>=1.31.0` — UI framework
- `pymupdf>=1.23.0` — PDF redaction (`import fitz`)
- `pytesseract>=0.3.10` — OCR
- `Pillow>=10.2.0` — Image handling for OCR verification
- `python-docx>=1.1.0` — Word file handling
- `presidio-analyzer>=2.2.0` — Microsoft NER framework
- `spacy>=3.7.0` — NLP backend for Presidio
- `gliner>=0.2.0` — Zero-shot NER

**`requirements-desktop.txt`** (Desktop app — no Streamlit, adds FastAPI):
- All of the above minus Streamlit, plus:
- `fastapi>=0.110.0` + `uvicorn[standard]>=0.27.0` — API layer

### Desktop (package.json)
- `react` + `react-dom` — UI framework
- `zustand` — State management
- `framer-motion` — Animations (page transitions, micro-interactions)
- `lucide-react` — Icons
- `electron` — Desktop shell
- `electron-updater` — In-app auto-update system
- `vite` + `@tailwindcss/vite` — Build tooling + Tailwind v4

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

## CI/CD — GitHub Actions

`.github/workflows/release.yml` — triggered by pushing a `v*` tag:

1. **build-mac** (macos-latest): Bundles Python + Tesseract, builds `.dmg` via electron-builder
2. **build-windows** (windows-latest): Bundles Python + Tesseract, builds `.exe` via electron-builder
3. **release-notes** (runs after both builds): Auto-generates teacher-friendly release notes with download links, setup guidance, categorised changelog, and collapsed auto-updater files

electron-builder uses `--publish always` to create a draft GitHub Release and upload assets. The release-notes job stamps the body. You still need to manually publish the draft.

### Auto-Update

The app uses `electron-updater` to check for updates on launch. `useUpdater.ts` hook + `UpdateBanner.tsx` component handle the UX. Update metadata (`.yml` and `.blockmap` files) are published alongside installers.

---

## What's Next / Known Gaps

- **Code signing**: Mac DMG uses ad-hoc signing (not notarised). Windows `.exe` is unsigned. Both work but show OS warnings on first launch.
- **Desktop UX polish**: COMPLETED (March 2026). Walkthrough, tooltips, before/after preview, witty progress comments, custom output path, typographic logo.
- **Windows support**: COMPLETED (v1.1.0). Installer, bundled Tesseract, platform-aware paths.
- **Linux**: Not supported. No current plans.
- **Fuzzy name matching**: Comment in `pii_detector.py` notes this as a future feature.
- **Batch processing** (multiple students at once): Not implemented.
- **OCR redaction quality**: Depends entirely on scan quality. Low-DPI or blurry scans may cause missed words. There is no fuzzy OCR matching yet.
- **`docs/legacy/`**: Contains 6 legacy markdown files moved from root during cleanup. Outdated — README.md is the authoritative user documentation.
- **`docs/plans/`**: Contains implementation plans from each development phase. Reference only.

---

## Sample Data

`sample/` contains real documents. This repo is public. Ensure real student documents are never committed — keep sample data synthetic or anonymised. The `sample/redacted_2/` and `sample/redaction_log.txt` files are in `.gitignore` (output files — never commit these).
