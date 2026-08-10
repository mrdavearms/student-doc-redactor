# CLAUDE.md — Bulk Redaction Tool

> Project-level context for Claude Code. Supplements the global `~/.claude/CLAUDE.md`.

## Project Overview

A local Mac and Windows app that redacts PII from student assessment PDFs and Word documents. Built for Australian teachers and school psychologists. All processing is local — no internet, no cloud services at runtime.

Two frontends exist:
- **Desktop app** (primary): Electron + React + Vite + Tailwind v4, communicating with a FastAPI backend via HTTP. This is the user-facing product.
- **Streamlit app** (legacy): The original prototype in `app.py`. Still functional but no longer the focus.

- **Repo**: https://github.com/mrdavearms/student-doc-redactor — the only maintained remote. A `gitlab` remote (`davearmswork/bulk-redaction-tool`) is still configured in git but is **abandoned and drifted**; do not push to it, and do not offer to re-sync it.
- **Branches**: `test` (development) → `main` (stable). Always push to `test` first, then to `main`.
- **Run (desktop)**: `cd desktop && npm run dev:electron` (starts Vite + Electron + auto-spawns backend)
- **Run (backend only)**: `./venv/bin/python3.13 -m uvicorn backend.main:app --port 8765`
- **Run (Streamlit)**: `source venv/bin/activate && streamlit run app.py`
- **Test**: `venv/bin/python3.13 -m pytest tests/ -v` (651 tests; runtime varies by machine/Tesseract availability)
  Note: `venv/bin/pytest` has a broken shebang pointing to a non-existent `venv_new/` path — always use `venv/bin/python3.13 -m pytest` directly.
- **Test (desktop)**: `cd desktop && npm test` (vitest, 166 tests across 11 files). Covers **pure modules only** — `api.ts`, `errorMessage.ts`, `store.ts`, `filename.ts`, `paths.ts`, `context.ts`, `faultReport.ts`, routing, `electron/navigation.cjs`, and `electron/macUpdate.cjs`. Note the macOS updater's **I/O half** (`macUpdateInstaller.cjs` — download, checksum, mount, staging) has no unit tests; it is covered by `cd desktop && npm run verify:mac-updater` (43 checks, macOS only, not part of `npm test` because it needs `hdiutil`/`ditto` and one network call — see `desktop/scripts/mac-updater-checks/README.md`). There is no **React-component** harness, so verify React changes via `npm run build` (tsc) + `npm run lint`. Electron **main-process** code is testable only where the logic has been extracted into a pure CJS module that `main.cjs` imports — `navigation.cjs` is the worked example, and `navigation.test.ts` imports it directly. Prefer that split over adding logic inline to `main.cjs`, which stays unit-testable only via `node --check electron/main.cjs`.
- **Stale desktop deps**: if `npm test`/`npm run build` errors with `vitest: command not found` or `Cannot find module 'vitest/config'`, run `cd desktop && npm install` first.
- **Build DMG (Mac)**: `cd desktop && npm run dist:mac`
- **Build installer (Windows)**: `cd desktop && npm run dist:win`
- **Build + publish to GitHub**: `cd desktop && npm run dist:publish` (CI only — requires `GH_TOKEN`)
- **Python**: 3.13+ (required for spaCy compatibility)

---

## Architecture

### Detection Pipeline

The entry point for all PII detection is `PIIOrchestrator`, not `PIIDetector` directly. Screens always use the orchestrator.

```
PIIOrchestrator
├── PIIDetector          (regex — always runs, user-entered names + structured PII)
├── Presidio + spaCy     (NER-primary — discovers names, generates variations)
│     ↓
│   For each PERSON entity → generate_name_variations() → search text
│     ↓
  _deduplicate()         (same text + page + line → keep highest confidence)
      ↓
  List[PIIMatch]         (sorted by confidence desc)
```

Both engines produce `PIIMatch` objects. The orchestrator merges and deduplicates by `(text.lower(), page_num, line_num)`. NER is the primary name discovery engine — when it finds a name like "Sarah Williams", it generates variations ("Sarah", "Williams", "S. Williams") and searches for those too.

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
├── pages/            → 8 wizard pages (setup + mode choice + 5 steps, 2 completion variants)
└── components/       → reusable UI components

FastAPI (backend/main.py)
├── /api/health, /api/dependencies/check
├── /api/folder/process, /api/folder/validate, /api/folder/open
├── /api/file/process, /api/file/validate   → single-document mode
├── /api/pii/detect   → returns matches, caches PIIMatch objects server-side
├── /api/redact       → uses cached detection data + user selections
├── /api/deidentify   → same cache/selections, writes labelled .txt instead
├── /api/deidentify/people → who was found, with a proposed role + its evidence
├── /api/deidentify/labels → labels for a proposed assignment (preview)
└── /api/preview      → renders PDF page at 150 DPI, returns base64 PNG
```

### Two Pathways

Step 0 asks which output the user wants (`workflowMode` in the store):

- **`redact`** — black out PII, producing redacted PDFs. The original pathway.
- **`deidentify`** — replace PII with non-identifying labels (`[Student]`, `[Parent 1]`), producing plain text safe to paste into an AI tool.

They are **not** separate pipelines. Conversion, detection, the review screen, manual PII additions and selections are byte-for-byte identical; only the final output step branches. `DeidentificationService` mirrors `RedactionService`'s shape (cooperative cancel, quarantine, filename PII stripping, single-document filename override).

De-identification reads the extracted text already in `_detection_cache` rather than re-extracting, so the text it replaces into is exactly the text detection ran against — and scanned pages work for free, since that cached text is already OCR'd.

### Screen Flow

The desktop app has a 9-screen flow (setup + mode choice + 5 or 6 workflow steps, plus a no-PII branch):

```
setup → mode_selection → folder_selection → conversion_status → document_review → [people_review] → final_confirmation → completion
```

`no_pii_found` is a branch off `document_review`, not a step in the ladder — it is shown when detection finds nothing to remove, so the user is never marched through a review screen with an empty list.

The `setup` screen checks for LibreOffice and Tesseract on first launch, with install guidance and a "Check Again" button. It is skipped on subsequent launches when dependencies are present.

`people_review` appears in **de-identify mode only** — hence `screensFor(mode)` rather than a fixed `SCREENS` array (6 steps de-identify, 5 redact). `mode_selection` is the app's landing screen (`initialState.currentScreen`). Like `setup` it is **not** in the step ladder — step numbering still runs 1–5, and the Sidebar shows the chosen pathway as a badge with a "change" link rather than as a step. `completion` renders `<DeidentifyCompletion />` or `<Completion />` depending on `workflowMode`, which keeps the redact completion screen untouched.

In the desktop app, `App.tsx` switches on `currentScreen` from the Zustand store. Layout wraps children in `<AnimatePresence mode="wait">` with `key={currentScreen}` for animated transitions.

Streamlit shares the same 5 workflow steps (no setup or mode screen — de-identify mode is desktop-only). `app.py` routes based on `st.session_state.current_screen`.

### Key Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit entry point, CSS, screen router |
| `src/core/pii_orchestrator.py` | **Main detection entry point** — merges all engines |
| `src/core/pii_detector.py` | Regex engine + `PIIMatch` dataclass definition |
| `src/core/presidio_recognizers.py` | 6 custom Australian Presidio recognizers |
| `src/core/nickname_map.py` | Curated ~100-entry Australian nickname dictionary with reverse lookup |
| `src/core/redactor.py` | **Dual-path redaction** (text-layer + OCR image), widget deletion, metadata stripping |
| `src/core/pseudonym_map.py` | De-identify mode: privacy-safe labels, roles, person-identity merge rules |
| `src/core/role_suggester.py` | Proposes a person's role from surrounding text, with quotable evidence |
| `src/core/text_deidentifier.py` | De-identify mode: single-pass label replacement + exact/fuzzy verification |
| `src/core/text_extractor.py` | Text + OCR extraction from PDFs |
| `src/core/document_converter.py` | LibreOffice Word → PDF conversion |
| `src/core/binary_resolver.py` | Cross-platform Tesseract/LibreOffice path resolution |
| `src/core/logger.py` | Audit log generation and save |
| `src/core/session_state.py` | All `st.session_state` keys and `navigate_to()` |
| `src/ui/screens.py` | All Streamlit screens (largest file) |
| `src/services/conversion_service.py` | Framework-agnostic conversion business logic |
| `src/services/detection_service.py` | Framework-agnostic PII detection business logic |
| `src/services/redaction_service.py` | Framework-agnostic redaction orchestration + custom output path |
| `src/services/deidentification_service.py` | De-identify orchestration, key file, label-only audit log |
| `backend/main.py` | FastAPI API layer + server-side detection cache |
| `backend/schemas.py` | Pydantic request/response models |
| `desktop/electron/main.cjs` | Electron main process — spawns backend, creates window |
| `desktop/electron/navigation.cjs` | Pure navigation allow-list used by `main.cjs` to deny `window.open` and off-app navigation — extracted so it is unit-testable |
| `desktop/electron/macUpdate.cjs` | Pure logic for the macOS self-updater — asset choice, download URL, "can we self-update?" checks, and the swap-script text. Unit-tested |
| `desktop/electron/macUpdateInstaller.cjs` | I/O half of the macOS self-updater — download + SHA-512 check, mount the dmg, stage the new `.app` beside the old one |
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
| `desktop/src/pages/ModeSelection.tsx` | Step 0 — choose redact or de-identify |
| `desktop/src/pages/PeopleReview.tsx` | "Who's who?" — confirm each person's role (de-identify only) |
| `desktop/src/pages/DeidentifyCompletion.tsx` | Completion screen for de-identify mode (leads with the key file) |
| `desktop/src/pages/NoPiiFound.tsx` | Shown when detection finds nothing — a branch off `document_review`, not a numbered step |
| `desktop/src/components/ErrorBoundary.tsx` | Top-level React error boundary, wrapped around `<App/>` in `main.tsx` |
| `desktop/src/components/ErrorFallback.tsx` | What the boundary renders after a render crash |
| `desktop/src/components/UpdateCard.tsx` | Prominent update panel on the landing screen (the banner is used on every other screen) |
| `desktop/src/lib/faultReport.ts` | "Report this problem" → `mailto:` only, no telemetry. **Strips every path-like token first** — file paths in this app contain student names |
| `desktop/src/lib/peopleRoles.ts` | `effectiveRoleMap` — the role map a run actually uses; see rule #54b |
| `desktop/src/types.ts` | `Screen` type, `WorkflowMode`, `SCREENS` array, API response interfaces |

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

Added in `a699268`. Values in practice: `'regex'`, `'presidio'`, and `'manual'` (user-added during document review — see rule #31). The docstring on the dataclass still lists `'gliner'` from before that engine was removed (see Known Gaps) — no code path emits it anymore. Used by the orchestrator for deduplication logic. Don't remove it.

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

### 8. Presidio is an optional dependency (but required in bundled app)

`_init_presidio()` catches all exceptions and sets the analyzer to `None` unless `require_ner=True`. The Streamlit app degrades gracefully to regex-only detection. The bundled desktop app passes `require_ner=True` — if Presidio/spaCy fails to load, it raises `RuntimeError` and the Setup screen shows a blocking error.

### 9. There are two redaction verification methods

- `verify_redaction(pdf_path, text)` — fast, text-layer only. Used in the main redaction flow for spot-checking.
- `verify_redaction_ocr(pdf_path, texts)` — slow, renders at 300 DPI and OCRs. More thorough. Used for comprehensive post-redaction checks.

Both verifiers use the module-level `_pii_visible_in_text()` whole-word check — never revert to substring matching, which falsely quarantined correctly-redacted files when a short name ('Ann') appeared inside an ordinary word ('Annual'). The helper splits PII on whitespace *and* hyphens so OCR variants like 'smith - jones' are still caught.

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

After per-page redaction, `_redact_embedded_images()` runs on **every page of the document** with the full document-level redaction item list (not just pages that had detections). Pages already processed by `_redact_ocr_page()` are skipped (their pixels were just OCR'd at 300 DPI), OCR results are cached per image xref for the run, and `_check_tesseract()` is memoised on the instance — without those three mitigations a 50-page scanned report costs ~65s. It extracts each embedded image via `doc.extract_image(xref)`, OCRs it with pytesseract, blacks out PII matches in the image pixels using PIL, and replaces the original via `page.replace_image(xref, stream=png_bytes)`. This catches PII in email screenshots, scanned documents, and even small logos. No image is too small to scan — there is no size threshold.

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

`PIIDetector._detect_organisation_names()` splits each org name into words and flags matches ≥3 chars. Common English words (`the`, `school`, `centre`, `clinic`, etc.) are excluded via `GENERIC_ORG_WORDS`. The code also runs a secondary filter against `_CONTEXTUAL_NAME_EXCLUDE` (the same list shared with name detection). Both lists must be checked if modifying exclusion logic. The full org name is matched first (longest match first, like student names). Category: `"Organisation name"`, confidence: `0.95`.

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

### 28. Backend-down detection lives in `api.ts` + `App.tsx`

`api.ts` distinguishes network errors from HTTP errors via `BackendUnreachableError`. The Zustand `backendReachable` flag drives a top-of-app banner in `App.tsx`; a 5-second polling effect on `/api/health` only runs while the flag is `false`. `FolderSelection.validateFolder` deliberately leaves `folderValid` untouched on `BackendUnreachableError` so the false-negative "Folder not found" message doesn't render.

### 29. Error message text comes from `lib/errorMessage.ts`, not raw backend strings

All `setError` call sites use `friendlyError(e)` from `desktop/src/lib/errorMessage.ts`. The mapper covers every `HTTPException(detail=...)` pattern in `backend/main.py` plus a fallback. Tests live at `desktop/tests/errorMessage.test.ts`. If you add a new backend error string, add a pattern to the mapper and a test case.

### 30. Cleanup endpoints are restricted to the user-selected output folder

`/api/cleanup` and `/api/cleanup/list` only operate on `*_redacted.pdf` and `*.UNVERIFIED.pdf` files inside the resolved `output_folder` (verified via `Path.is_relative_to`); the delete endpoint enforces the filename patterns itself, not just the list endpoint. Do not relax these checks — they prevent path-traversal deletion of files outside the output area.

### 31. Manually-added PII items live in the same detection cache as engine-found matches

`POST /api/pii/manual` (`backend/main.py`) appends a `PIIMatch(source="manual")` directly to `_detection_cache[doc_path]["matches"]` — the same list `/api/redact` reads from. This means a manual item is only ever *appended*, never inserted at an arbitrary position: its index in that list becomes its selection key (`f"{doc_path}_{index}"`), and `/api/redact` derives `user_selections` by iterating `range(len(matches))` from the cache. Inserting anywhere but the end would silently reassign an existing item's key to unrelated new content.

### 32. Fuzzy OCR matching only applies to alphabetic words of 5+ characters

`_fuzzy_word_match()` in `redactor.py` (used by the shared `_match_and_redact_ocr_words()`, so it covers both `_redact_ocr_page()` and `_redact_embedded_images()`) tolerates single-character OCR misreads via Levenshtein distance — but only for alphabetic PII of 5+ characters (`pii_lower.isalpha()` guard, same one used elsewhere to keep fuzzing away from emails/URLs). Distance tolerance is 1 for 5-7 letter words, 2 for 8+. Words under 5 letters, and any non-alphabetic PII, require an exact match — fuzzing short words risks blacking out unrelated text (e.g. "And" for "Ann").

### 33. The street-only Address pattern uses two street-type classes

Unambiguous nouns (`Street`, `Road`, `Lane`…) match freely; abbreviations and words that are also common English nouns (`St`, `Dr`, `Court`, `Place`, `Rise`, `Way`, `Close`, `Grove`) must be followed by a comma, full stop, or end-of-line. Merging them back into one list re-introduces false positives on report language such as '2 Specialists Dr Jones' and '12 Point Rise in reading fluency' — which the Accept-All path would redact without the teacher noticing.

### 34. Never filter NER name variations through `_CONTEXTUAL_NAME_EXCLUDE`

That set contains real given names (Bob, Sue, Max, Pat, Ray, Ted, Penny…) because it filters keyword-adjacent noise in `_detect_contextual_names`. Using it on variations stops a parent referred to by first name only from being redacted. `pii_orchestrator._NAME_TITLES` exists for the honorific-filtering job; keep the two separate.

### 35. API token auth, and middleware order

When `REDACTION_API_TOKEN` is set (Electron sets it at spawn), every endpoint except `/api/health` requires a matching `X-Api-Token` header. The token flows `main.cjs` → backend env + `ipcMain.handle('get-api-token')` → `preload.cjs` → `window.electronAPI.getApiToken()` → cached in `api.ts`. Unset (manual `uvicorn`, pytest) means auth is disabled. **The `@app.middleware("http")` token function must be defined BEFORE `app.add_middleware(CORSMiddleware, ...)`** — Starlette inserts at index 0, so the last registration is outermost, and only that ordering lets a 401 carry CORS headers the dev renderer can read. CORS is pinned to the two Vite dev origins; the packaged app sends no Origin at all and needs no entry, and `"null"` is deliberately excluded (it is the sandboxed-iframe origin).

### 36. Cooperative redaction cancel

`POST /api/redact/cancel` flips `_redaction_control['cancel_requested']`; `RedactionService.execute(should_cancel=...)` checks it between documents, sets `RedactionResults.cancelled`, and marks the audit log via `logger.set_cancelled()`. The frontend does NOT abort the redact request on cancel — it keeps it alive and reads accurate partial results from the response, including `quarantine_path` for `.UNVERIFIED.pdf` files (which have no `output_path`).

### 37. spaCy loads once per process

`_get_shared_nlp_engine()` in `pii_orchestrator.py` caches the NLP engine module-level (thread-locked). Never construct `NlpEngineProvider` per request — it costs ~0.6s each time. The `AnalyzerEngine` itself stays per-orchestrator (~0.01s) because `StudentNameRecognizer` is parameterised per run.

### 38. Single-document mode reuses the whole folder pipeline

Step 1 offers two equal choices: one document or a whole folder (`inputMode` in the store). Single-document mode is not a separate pipeline — `ConversionService.process_file()` returns the same `ConversionResults` shape as `process_folder()`, so detection, review and redaction are byte-for-byte the same code path afterwards.

Three things hold it together:
- **`setFilePath` also sets `folderPath`** to the file's parent folder. Redaction still works in folders (audit log location, default `redacted/` output), so nothing downstream needs to know which mode is active. It also clears `folderValid`, because `folderPath` has just moved to a folder the user never validated — without that, switching back to folder mode shows a green "Folder found" and Start Processing would redact every document in the chosen file's folder. `FolderSelection` re-validates when the user switches back.
- **`conversionFolderPath` stores the *file* path in file mode**, not the folder. Storing the folder would let a second file in the same folder reuse the first file's conversion results.
- **The conversion screen auto-advances in file mode** when exactly one file came through clean (`processable_count === 1 && flagged_count === 0`), guarded by `autoAdvancedKey`. Without that guard, any screen navigating back to `conversion_status` would be bounced straight forward again and the user could never reach step 1.

### 39. `custom_output_filename` is honoured for one document only

The Save As dialog (file mode) names a single file. `RedactionService.execute()` ignores `custom_output_filename` unless `len(request.documents) == 1` — several documents would all collide on the one name. `_sanitise_output_filename()` strips any directory component (so a crafted name can't write outside the chosen folder) and forces a `.pdf` suffix.

An explicit filename also **skips the collision counter** — the native Save dialog has already asked the user about replacing an existing file. Without an override, the existing PII-stripping (`strip_pii_from_filename`) and `_2`/`_3` collision suffixes apply exactly as before.

**The output must never be the source document.** The Save As dialog opens in the source document's own folder, so the original is one click away, and redacting in place cannot work: PyMuPDF raises `save to original must be incremental`, and `redact_pdf()`'s failure cleanup would then `unlink()` what is actually the user's only unredacted copy. `_process_document()` refuses via `is_same_file()` before any file operation; `redact_pdf()` additionally never unlinks a path equal to its input; and `FinalConfirmation.handleSaveAs` rejects the choice in the UI. Do not remove any of the three — `is_same_file()` uses `os.path.samefile` so it catches the case-insensitive-filesystem variants (`Report.pdf` vs `report.pdf`) that a string compare misses.

`desktop/src/lib/filename.ts` only *suggests* the name that pre-fills the dialog; the backend stays authoritative for the default name.

### 40. Response models carrying mixed-type rows need a typed model, not `Dict[str, X]`

`RedactionResultsResponse.ocr_warnings` was declared `List[Dict[str, int]]` while the endpoint built `{"filename": str, "count": int}` — so Pydantic rejected the filename and **every redaction of a scanned document returned a 500** instead of its results. It went unnoticed because the failure needs a selected PII item on an image-only page. It is now an `OcrWarning` model (`filename: str`, `count: int`).

`verification_failures` is genuinely `Dict[str, str]` and is fine as-is. Any future row with mixed value types must get its own model.

### 41. `detectionParamsKey` must be cleared on any backend-cache doubt

The frontend skips re-detection when the fingerprint matches, which is only safe while `_detection_cache` holds the same run. Every path that can observe a `no cached detection data` error — and `setBackendReachable(false)` — clears the key. Without that the wizard loops: skip detection → redact 400s → 'go back one step' → skip again.

`setWorkflowMode` deliberately does **not** clear it. Detection inputs are identical in both pathways, so a user who changes their mind after reviewing would otherwise lose all their review work for nothing.

### 42. De-identify labels must never contain any part of a real name

`Student(BB)` for "Billy Bob" is not a pseudonym — initials identify a child in a small school community as surely as the name does. Labels are role + sequence number only (`[Student]`, `[Parent 1]`, `[Person 2]`), assigned by entry/discovery order, which leaks nothing. `tests/test_pseudonym_map.py::TestNoIdentityLeaksIntoLabels` asserts this programmatically for every key entry — no word of 2+ characters and no initials pattern may appear in a label. Do not add a label scheme derived from the name "for readability".

The only re-identifying artifact is the key file, `DO-NOT-UPLOAD-name-key.txt`. The warning is in the **filename** because the likeliest accident is dragging a whole folder into an AI chat, not failing to read a header.

### 43. The de-identify key file goes with the ORIGINALS, never in the output folder

Everything in the output folder must be safe to upload — that is the entire point of the mode. The key file is written to `request.folder_path` (where the unredacted originals already live), so it adds no new exposure there. `tests/test_backend_deidentify.py::test_key_file_is_outside_the_output_folder` enforces it. `/api/cleanup` cannot delete it either: it matches none of the `_CLEANUP_SUFFIXES` patterns.

For the same reason the de-identify audit log records **labels, not values** — it sits alongside the documents and must not become a second copy of the key. `RedactionLogger` is constructed with `'[Student]'` in place of the real name so even its header is clean, plus `operation="DE-IDENTIFICATION", verb="de-identified"` so it does not call itself a redaction run. Those two parameters **default** to the redact wording precisely so `redaction_service`'s two-argument call keeps the redact log byte-for-byte as it was — don't make them required.

### 44. Two names are the same person only by full name, never by a shared token

Reports routinely name classmates and siblings. The naive merge rule ("this name shares a variation with someone known, so it's them") folds classmate "Billy Chen" into student "Billy Bob" because both yield the variation "Billy". That is not a privacy failure but a **meaning** failure: the AI reading the output would attribute one child's behaviour to another.

`PseudonymMap.register_person()` merges only when the full names match or one full name appears in the other's `generate_name_variations()` output (so "S. Williams" is "Sarah Williams"). Shared tokens then resolve separately: a surname claimed by every claimant → `[Family name]`; a given name → the highest-priority claimant (Student > Parent > Family member > Person). Both are recorded in the key file's ambiguity notes.

### 45. De-identify verification adds a fuzzy pass on OCR text

In redaction a garbled OCR word only means a black box lands slightly off. In de-identify mode the OCR text **is** the deliverable, so "Bi11y" would ship readable. `fuzzy_leftovers()` re-checks OCR-sourced pages using `redactor.fuzzy_word_match` — the same rule as rule #32, lifted to module level precisely so the thresholds are stated once.

Both verifiers strip the inserted labels first (`strip_labels`). Without that, a person genuinely named "Person" would see `[Person 1]` reported as their name still being visible and quarantine a correctly processed file.

`text_deidentifier._pattern_for` deliberately mirrors `redactor._pii_visible_in_text`'s token handling. If they drift apart, the verifier starts flagging text the replacer never had a chance to match.

### 46. In de-identify mode the SOURCE FILENAME is PII

Assessment documents are routinely named after the student ("Billy Bob Support Report.pdf"). Writing `doc.name` into the output file's header or into `LogEntry.document_name` printed the very name every other line had removed — caught only by an end-to-end run on a realistically-named file, because every unit test used `report.pdf`.

Everything written to disk uses `safe_name` / `output_filename` (already `strip_pii_from_filename`'d). `DeidentifyDocumentResult.document_name` deliberately keeps the real name — it is shown in the local UI so the user can recognise their file. The original→output mapping lives in the key file's "WHICH FILE CAME FROM WHICH" section, which is already private.

### 47. Not every NER "person" is a person

PDF extraction hands NER run-together spans (`"Billy Bob        Date of Birth"`) and form labels (`"Email"`). Registering those as people invented bogus `[Person N]` key entries and — worse — gave the student *two different labels in one document*, because the long span won longest-first replacement.

`clean_person_name()` rejects candidates with digits, >4 tokens, non-alphabetic tokens, or any token in `_NOT_A_PERSON_TOKEN` (a set chosen to avoid plausible Australian surnames), and strips leading honorifics so "Ms Williams" merges with "Sarah Williams" instead of becoming a second teacher. A rejected span still gets replaced — `label_for()` falls back to `_label_from_contained()`, resolving it to the longest real name inside it, so the student stays `[Student]` on that line.

### 48. A merge in `register_person` must write the new surface form back

Deciding two names are the same person is only half the job. The merge branch used to `return owner.label` without recording the candidate's variations, so the merge was forgotten immediately: registering "S. Williams" then "Sarah Williams" merged correctly, but "Sarah W." was then unrecognised and minted a **second** `[Person N]` for the same human — two labels in the output and two rows in the key file, which is precisely the meaning failure rule #44 exists to prevent.

The branch now claims any genuinely new form for the merged owner and rebuilds. It claims **only forms nobody else already owns**: re-claiming a shared token would flip `_rebuild`'s all-surnames test and silently turn `[Family name]` back into `[Student]`. It also upgrades the owner's display name to the fullest written form (`_name_fullness`), so the key file says "Sarah Williams" rather than whichever abbreviation happened to appear first.

### 49. Output formatting: substitute and verify BEFORE decorating

Native pages are rebuilt from line geometry (`_format_native_page`): wrapped prose reflows into paragraphs, lines sharing a row become table cells, header/footer lines are dropped by POSITION (never by string — string matching deleted body lines that merely repeated a letterhead line). Cells are assembled with `_CELL_SEP` (U+2028 — whitespace to the regex engine) and only decorated into `" | "` AFTER replacement and verification have run. Decorating first lets a multi-word PII value straddle a cell join where neither the replace pass nor the symmetric verify pass can bridge it — a silent false pass. AcroForm widget values are re-appended after the rebuild (they live outside the content stream); any formatting failure falls back to the cached raw text.

### 50. The output folder is only safe to share when it is a SEPARATE folder

The UI promises everything in the output folder is safe to upload. That holds for the default `deidentified/` subfolder, but not when the user points output at the folder holding the originals — where the unredacted source documents and the key file sit alongside the output. In single-document mode this is the **default** path, because the Save As dialog opens in the source document's own folder.

`DeidentifyResults.output_folder_holds_originals` (via `_same_folder`, which uses `os.path.samefile` for the case-insensitive-filesystem and symlink variants) flows to the completion screen and the key file, both of which then warn instead of reassuring. The run is deliberately **not** blocked — the user is entitled to that choice; they are just not told a falsehood about it.

### 51. Roles are PROPOSED, never assumed

The tool cannot know whether "Sarah Williams" is a classroom teacher or a speech pathologist, and getting it wrong is worse than leaving it vague: `[Teacher 1]` over a paediatrician's advice invites an AI to reason about it as classroom observation. `role_suggester.suggest_role()` therefore returns a role **and the phrase that suggested it**, and never emits `likely` without a quotable keyword. No evidence, or two roles tied, ⇒ `unknown` ⇒ `[Other person]` ⇒ the user is asked. `'guardian'` sits under both `parent` and `carer` deliberately so it ties. The bare word `'student'` is deliberately NOT a keyword — it is near-ubiquitous and almost always means the report's subject, who is excluded from the screen.

### 52. Custom role text is the one place rule #42 can be bypassed

A user-typed role goes straight into a label, so "Billy's mum" would smuggle a real name past the no-names invariant. `PseudonymMap.sanitise_custom_role()` rejects text containing ANY owner's variation — student, parents, family, other discovered people **and organisations** — using `redactor._pii_visible_in_text` so it inherits the whole-word semantics ("Ann" inside "Annual" is not a match) rather than re-deriving them. Rejected text falls back to `[Other person]`.

### 53. Role numbering is keyed on the rendered stem, across built-in AND custom roles

`_assign_role_labels()` buckets owners by their final bracket text, not by role key. Bucketing per key would let two people who both typed "Speech pathologist" — or one assigned `[Health professional]` while another typed that exact text — emit identical bare labels and become indistinguishable in the output: the rule #44 meaning failure, user-induced. Numbering appears only when 2+ owners share a stem, so one teacher is `[Teacher]` and three are `[Teacher 1..3]`. Reassigning one person can therefore renumber others — which is why `/api/deidentify/labels` returns the whole set and the UI re-renders every card.

`_rebuild()` runs `_assign_role_labels()` and `_resolve_shared_tokens()` as two separate passes on purpose: role numbering must not be able to corrupt the priority logic that rule #44's identity resolution depends on.

### 54. People-review answers die with any selection change

`personRoles` / `personCustomLabels` / `ignoredPeople` / `peopleReviewed` are only meaningful for the exact set of people the current selections produce. `document_review` sits BEFORE `people_review`, so the user can always go back and deselect the very person they just classified. Every selection mutation — `toggleSelection`, `selectAll`, `deselectAll`, `addManualMatch` — clears them, as do `setDetectionResults` and `setWorkflowMode`. Same class of staleness rule #41 guards for `detectionParamsKey`; they are deliberately NOT part of that fingerprint.

The people list itself is **response-only**: it carries real names by construction and must never be written to disk or into the audit log.

### 54a. Selection defaults are per-pathway, and mode-switch re-derives them

"Select everything" is right for redaction (over-removal = a black box) and wrong for de-identification (over-removal destroys the content the AI needs — spaCy tags "Working Memory" as ORGANIZATION). `lib/categories.ts`: a category is pre-unticked ONLY when a false positive is likelier than a true one AND removal costs meaning — `ORGANIZATION (NER)`, `NRP (NER)`, unknown `* (NER)` fallbacks, de-identify mode only. The builder writes an EXPLICIT false for every unticked key (DocumentReview renders `?? true`; an omitted key displays ticked while submitting unticked). `setWorkflowMode` re-derives selections for the new mode when detection results exist — in BOTH directions — because the sidebar's change link is reachable mid-flow and stale defaults reintroduce the bug sideways. `detectionParamsKey` stays untouched (rule 41).

### 54b. The Who's-who screen commits what it displays

The dropdown renders `explicit answer ?? suggestion`; Continue commits exactly that via `effectiveRoleMap`, and the label preview is requested with the same effective map — the screen must never show a role the run won't use. Its zero-people auto-skip uses `peopleAutoSkippedKey`, a SEPARATE field from `autoAdvancedKey`: sharing one field let PeopleReview's stamp erase ConversionStatus's and re-arm the forward-bounce trap rule 38 fixed.

### 54c. The NER sweep and the read endpoint

After a successful write, the output (labels stripped) is swept with the shared spaCy engine; surviving PERSON entities become `leftover_name_warnings` — warnings, not quarantine (NER false positives would block correct output), excluding strings the user deliberately deselected. The warnings carry REAL NAMES: UI response only, never the audit log, never disk. `/api/output/read` serves preview/copy and is deliberately narrower than cleanup: only `*_deidentified.txt` — never `.UNVERIFIED.txt` (may contain PII) and never the key file.

### 55. One copy of the app only — and a healthy port does NOT mean the backend is ours

`waitForBackend()` polling `/api/health` proves *something* is on 8765, not that it is the process we just spawned. Two everyday situations put a stranger there: double-clicking the app icon twice, and force-quitting the app (Task Manager / Force Quit) which orphans the Python child. Either way the second `uvicorn` exits 1 on `address already in use` — but only after the orphan has already answered health with 200, so the window opened, and its renderer holds an `API_TOKEN` the live backend rejects: every request 401s.

Four things hold this together, and removing any one restores the trap:
- `app.requestSingleInstanceLock()` gates the whole `ready` path; the loser quits and `second-instance` focuses the running window.
- **`/api/health` reports `instance_match`** — whether the caller's `X-Api-Token` matches that process's own token — and `waitForBackend` sends the header and resolves ONLY when it is true. The endpoint stays unauthenticated: a mismatch is a field in the body, never a 401, so rule #35 and the renderer's backend-down poller are untouched. With no token configured (manual `uvicorn`, pytest) it reports a match, which keeps the run-uvicorn-yourself dev workflow working.
- `backendReady` is set only after that check passes. Before it, a backend exit is a **startup** failure: the handler records `backendFailure` and returns instead of showing its own dialog.
- `waitForBackend` checks `backendFailure` on every tick and rejects with it, so the user reads "another copy is already running… restarting your computer will clear it" rather than a generic "engine stopped".

**The identity check is the load-bearing one, and it is not obvious why.** Without it the other three still fail, because they lose a race: uvicorn spends several seconds loading spaCy *before* it touches the port, so the orphan answers health long before our own process gets as far as `address already in use`. `backendReady` is therefore already true when the exit arrives, the exit takes the crashed-mid-session branch, and the user is told "Redaction Engine Stopped" on every launch until they reboot. Verified by force-quitting the packaged `.dmg` and relaunching — a dev-mode test cannot reach this, because dev and packaged spawn different interpreters.

Do not "simplify" the exit handler back into a single unconditional dialog either — it races `waitForBackend` and reports the wrong cause.

### 56. Detection context carries markdown bold; the RENDERER strips it, never the detector

`PIIDetector._get_context()` wraps the matched value in `**…**` — a leftover from the Streamlit UI, which rendered markdown. React renders text verbatim, so this shipped literal asterisks to teachers on the most-used screen (`...Student: **Billy Bob**...`).

It is fixed in `desktop/src/lib/context.ts` (`splitContext`), NOT in `pii_detector`, for two reasons: `_get_context` feeds the shipped **redact** pathway too, and the NER path (`pii_orchestrator`) builds context with **no markers at all**, so the same list carries both formats. `splitContext` must therefore leave unmarked text completely alone rather than assume every context is marked up — `desktop/tests/context.test.ts` asserts both shapes. If you ever do change the backend format, that test is the thing to update first.

### 57. The sidebar's active highlight covers the whole `<li>`, connector included

In `Sidebar.tsx` the active step is drawn by `<motion.div layoutId="activeStep" className="absolute inset-0 …">`. `inset-0` spans the entire `<li>`, and the connector line is a **child of that same `<li>`** — so an unpositioned connector gets painted over and the active step's line silently disappears (and its pill looks taller than every other row).

The connector div carries `relative` for exactly this reason. It looks like a redundant utility class; it is load-bearing. Same applies to the step-content div above it, which is already `relative`.

### 58. `should_replace()` is the de-identify gate — and verification must use the SAME gate

Contextual detection is deliberately generous: a `Parent/Guardian:` line makes the capitalised word on the **next** line a medium-confidence name candidate, so an Australian school form's `Phone:` row is routinely offered as PII **and ticked by default**. Replacing it rewrote the row to `[name]: [phone]`, as though someone were called Phone. `PseudonymMap` already knew better — `clean_person_name()` rejects those words — but `label_for()` never consulted it and fell through to `[name]`.

`PseudonymMap.should_replace(text, category)` is now the single gate. It declines ONLY when all three hold: the category is a person category, the text is entirely `_NOT_A_PERSON_TOKEN` words (`_is_form_label`), and it is neither a known variation nor a span containing one. Structured PII, user-entered names, and junk spans wrapping a real name are never skipped, so it cannot cause under-removal.

**Both callers must use it or the file quarantines itself.** `deidentify_text` skips the match; `_process_document` builds `replaced_matches` from the same predicate and derives `selected_texts` (verification) and the audit-log entries from that list. Verify a string the replacer deliberately left alone and `verify_deidentified` reports it "still visible" — a false quarantine on correct output. This is the same replace/verify symmetry rule #49 protects for cell separators.

### 59. `register_person` assigns a ROLE KEY, never a rendered label

It used to pass `f'[Person {n}]'` into `_add_person`'s **role** parameter. The label came out right only because `_Owner.stem` does `ROLE_LABELS.get(self.role, ROLE_LABELS[DEFAULT_ROLE])` and silently fell back — the right answer for the wrong reason, while an invalid role key leaked out through `/api/deidentify/people` as `"role": "[Person 1]"`. Anything that later validates or switches on `role` would have broken on it.

It passes `DEFAULT_ROLE` and returns `owner.label` (set by `_rebuild()`) rather than reconstructing a string. There is no `[Person N]` label scheme any more — unclassified people render as `[Other person]`, numbered by rule #53 when several share the stem.

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
| `workflowMode` | 'redact' \| 'deidentify' | Which pathway (default `redact`) — see rule #41 on why it doesn't reset detection |
| `inputMode` | 'file' \| 'folder' | One document or a whole folder (default `folder`) |
| `filePath` | string | Selected single document (file mode) |
| `fileValid` | boolean | Whether the single document exists and is a supported type |
| `autoAdvancedKey` | string | Input that already auto-skipped the conversion screen |
| `folderPath` | string | Selected input folder — derived from `filePath` in file mode |
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
| `deidentifyResults` | DeidentifyResults \| null | Final de-identification outcomes (incl. `key_file_path`) |
| `personRoles` | Record<string,string> | Confirmed role per discovered person — dies with any selection change |
| `personCustomLabels` | Record<string,string> | User-typed role text, sanitised backend-side |
| `ignoredPeople` | string[] | Names marked "not a person"; text still replaced via category fallback |
| `peopleReviewed` | boolean | Whether the user has been through the Who's who screen |
| `isProcessing` | boolean | A redact/de-identify request is in flight — hides the pathway-change link |
| `loading` | boolean | Generic loading overlay active |
| `loadingMessage` | string | Loading overlay text |
| `error` | string \| null | Global error toast message |
| `detectionParamsKey` | string | Fingerprint of last detection inputs — matching inputs skip re-detection |
| `conversionFolderPath` | string | Folder that produced conversionResults — mismatch triggers reprocessing |
| `backendReachable` | boolean | Backend answering `/api/health` — drives the top-of-app banner (rule #28) |
| `peopleAutoSkippedKey` | string | Input whose zero-people PeopleReview already auto-skipped — deliberately SEPARATE from `autoAdvancedKey` (rule #54b) |
| `lastOutputPath` | string | Where the last run wrote, for the "open folder" action on the completion screen |

`setFolderPath` is deliberately dumb (it fires on every keystroke); folder-change invalidation happens via `conversionFolderPath` in `ConversionStatus`, and `setDetectionResults` clears any stale `redactionResults`.

---

## Detection Confidence Values (Regex Engine)

| Category | Confidence | Rationale |
|----------|-----------|-----------|
| Student name | 0.95 | High — word-boundary matched against known name |
| Phone number | 0.95 | High — structured Australian pattern |
| Email address | 0.95 | High — standard pattern |
| Address | 0.95 | High — requires state + postcode |
| Address (street-only, no state/postcode) | 0.65 | Medium — capitalised street name + street type, no state/postcode anchor |
| Medicare number | 0.95 | High — contextual guard required |
| Date of birth | 0.95 | High — label required |
| Student ID (surname match) | 0.95 | High — prefix matches student surname |
| Student ID (no surname match) | 0.65 | Medium — pattern only, prefix mismatch |
| Centrelink CRN | 0.65 | Medium — contextual guard, pattern is broad |
| Family/parent (contextual) | 0.65 | Medium — inferred from keyword proximity |
| Parent/family (user-provided) | 0.95 | High — user explicitly named them |
| Organisation name | 0.95 | High — user-provided, word-level matching with generic word filter |
| NDIS number | 0.90 | High — 9-digit with keyword guard |
| ABN | 0.90 | High — 11-digit with keyword guard |
| Passport number | 0.65 | Medium — letter+7 digits, keyword guard |
| Student name (nickname) | 0.75 | Medium — bidirectional nickname map |
| Person name (NER) | 0.90 | High — spaCy PERSON entity |
| Person name (NER variation) | 0.85 | High — variation of NER-discovered name |
| Cross-line DOB/Medicare | 0.90 | High — label on previous line |
| Cross-line contextual name | 0.60 | Medium — family keyword on previous line |

---

## Test Structure

```
tests/                                # 651 tests total
├── test_pii_detector.py              # 71 tests: phone, email, address, Medicare, CRN, Student ID, DOB, NDIS, ABN, cross-line
├── test_pii_detector_names.py        # 68 tests: name variations, contextual detection, possessives, family, nicknames
├── test_pii_orchestrator.py          # 31 tests: orchestrator merge, dedup, NER-primary coordination
├── test_presidio_recognizers.py      # 23 tests: 6 custom AU Presidio recognizer unit tests
├── test_redactor.py                  # 26 tests: text-layer redaction routing, possessive+punctuation, redact_pdf robustness
├── test_signature_detection.py       # 16 tests: heuristic signature detection (unit + integration)
├── test_ocr_redaction.py             # 37 tests: image-only page detection, OCR redaction, word matching, fuzzy OCR matching
├── test_ocr_verification.py          # 7 tests: post-redaction OCR verification (300 DPI re-scan)
├── test_metadata_stripping.py        # 8 tests: PDF metadata removal (author, XMP, embedded files)
├── test_widget_redaction.py          # 7 tests: AcroForm widget deletion (incl. word-boundary match)
├── test_filename_redaction.py        # 13 tests: PII in filenames → [REDACTED] replacement
├── test_zone_redaction.py            # 5 tests: header/footer zone blanking (Stage 0)
├── test_manual_pii.py                # 4 tests: manual PII addition endpoint (validation, cache append, redact round-trip)
├── test_pseudonym_map.py             # 92 tests: label privacy invariant, person-identity merge, shared tokens, junk NER spans, valid role keys
├── test_text_deidentifier.py         # 40 tests: longest-first replacement, label re-match guard, exact + fuzzy verification, form-label skip
├── test_deidentification_service.py  # 48 tests: end-to-end text output, key file location, source-filename leaks, zones, cancel
├── test_backend_deidentify.py        # 7 tests: /api/deidentify contract, key file outside output, cache-miss 400
├── test_output_read_api.py           # 8 tests: /api/output/read guards — *_deidentified.txt only, never .UNVERIFIED.txt or the key file
├── test_role_suggester.py            # 27 tests: role keywords, guardian ambiguity, no false positives
├── test_person_roles_api.py          # 12 tests: /people + /labels contracts, roles reaching output, renumbering
├── test_single_document.py           # 25 tests: single-file conversion, /api/file/* endpoints, custom output filename, save-over-source guard
├── test_cleanup_api.py               # 21 tests: cleanup path-traversal guards, .txt patterns, key file undeletable
├── test_session_state.py             # 2 tests: session state key initialisation
├── test_binary_resolver.py           # 6 tests: cross-platform Tesseract/LibreOffice path resolution
├── test_text_extractor.py            # 4 tests: coord extraction + /api/preview fitz handle closing
├── test_backend_redact.py            # 10 tests: detect→redact selection, clean-500 error wrapping, OCR-warning response shape
├── test_api_auth.py                  # 15 tests: API token middleware, CORS on 401, health instance_match identity
├── test_integration.py               # 6 tests: end-to-end redaction pipeline (links, bookmarks, structure)
├── test_adversarial.py               # 7 tests: unicode edge cases, boundary conditions
└── test_false_positives.py           # 5 tests: false-positive regression tests
```

Tests use `sys.path.insert` to locate `src/core/` modules — this is required because the test runner runs from the repo root, not from within `src/`.

**OCR redaction tests** (`test_ocr_redaction.py`) mock `pytesseract.image_to_data` to return controlled word bounding boxes, avoiding a hard dependency on Tesseract being installed in the test environment. They test the matching logic (cleaned vs exact, possessives, email/URL handling) and the page-type routing (text-layer vs OCR path).

Run a single test file: `venv/bin/python3.13 -m pytest tests/test_pii_detector.py -v`
Run with output: `venv/bin/python3.13 -m pytest tests/ -v -s`
Backend API tests use FastAPI's TestClient: `from fastapi.testclient import TestClient` — available in the existing venv, no extra install needed.

**Mocking PyMuPDF in tests:** patch `<module>.fitz.open` (e.g. `redactor.fitz.open`, `text_extractor.fitz.open`). The `/api/preview` endpoint uses a function-scoped `import fitz`, so patch the real `fitz` module — not `backend.main.fitz` (which doesn't exist until the function runs). `fitz.Document.is_closed` is handy for asserting handles are released.

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

---

## LibreOffice Path Discovery

`document_converter.py` and `binary_resolver.py` check paths in order:
1. `which soffice` / `where soffice` (system PATH)
2. `/opt/homebrew/bin/soffice` (Apple Silicon Homebrew)
3. `/usr/local/bin/soffice` (Intel Mac Homebrew)
4. `/Applications/LibreOffice.app/Contents/MacOS/soffice` (Mac app bundle)
5. `C:\Program Files\LibreOffice\program\soffice.exe` (Windows default)
6. `C:\Program Files (x86)\LibreOffice\program\soffice.exe` (Windows 32-bit)

---

## CI/CD — GitHub Actions

`.github/workflows/release.yml` — triggered by pushing a `v*` tag:

1. **verify-version** (ubuntu-latest): Hard-fails in seconds if `desktop/package.json` ≠ tag
2. **create-release** (ubuntu-latest): Creates the GitHub Release for the tag, once — see the race note below
3. **build-mac** (macos-latest): Bundles Python + Tesseract, builds `.dmg` via electron-builder
4. **build-windows** (windows-latest): Bundles Python + Tesseract, builds `.exe` via electron-builder
5. **release-notes** (runs after both builds): Auto-generates teacher-friendly release notes with download links, setup guidance, categorised changelog, and collapsed auto-updater files

electron-builder uses `--publish always` to upload assets into that release. `build.publish.releaseType` is `"release"`, so nothing is ever a draft; the `release-notes` job overwrites the placeholder body and re-asserts `--draft=false`, so the release **publishes automatically** — no manual step required.

- **`create-release` exists to stop two releases landing on one tag, and must stay a `needs:` barrier for BOTH builds.** electron-builder creates the release itself when it can't find one for the tag. With `build-mac` and `build-windows` in parallel, both can look, both can miss, and both can create. That is not theoretical — it happened on v1.6.1: two releases, same tag, and the near-empty one won the tag's **download namespace**, so `.../download/v1.6.1/<installer>` returned **404 for both installers and for `latest.yml`** while the release still looked published. `release-notes` then died with HTTP 422 `Release.tag_name already exists`, leaving both bodies blank. Note the failure is invisible from the run summary alone — both build jobs go green, because each one genuinely succeeded at building and uploading into *its own* release. Recovery is to delete the duplicate **by release ID** (`gh api -X DELETE .../releases/<id>`); `gh release delete` takes a tag, which is precisely the thing that is ambiguous. Re-running the `release-notes` job afterwards regenerates the notes correctly.

- **`mac.identity: "-"` is REQUIRED, and removing it breaks signing SILENTLY.** electron-builder only ad-hoc signs when the identity is explicitly `"-"`; with no identity configured and none in the keychain (which is always the case on a CI runner) it logs `skipped macOS application code signing` and ships the app carrying nothing but Electron's own linker signature — `Identifier=Electron`, `flags=(adhoc,linker-signed)` — so `hardenedRuntime` and the entitlements never reach users. Older electron-builder fell back to ad-hoc automatically; **26.8.1 → 26.15.3 (an August 2026 `npm audit fix`) removed that fallback**, and v1.6.1 through v1.7.0 shipped unsigned as a result. Nobody noticed because the app still runs.

  A correct build reports `Identifier=au.com.antigravity.redaction-tool`, `flags=0x10002(adhoc,runtime)`. Check it after any electron-builder bump:
  ```
  codesign -dv --verbose=2 "release/mac-arm64/Redaction Tool.app"
  ```
  Ad-hoc signing with `hardenedRuntime` **requires** `com.apple.security.cs.disable-library-validation` in `assets/entitlements.mac.plist` or the app fails to launch when it loads the bundled Python/Tesseract dylibs — electron-builder warns about this at build time. That entitlement is already there; do not remove it. A `--dir` build plus an actual launch is the only check that catches it, since the signature itself looks fine either way.

- **Do NOT push tags to trigger builds unless code is merged to `main` first.** Triggered by `git tag vX.Y.Z && git push origin vX.Y.Z`.
- **Pushing a `v*` tag via Bash requires bypass permissions** — the tool's classifier blocks tag pushes that trigger public releases.
- **Branch pushes trigger NO CI** — only `v*` tags run a workflow. Pushing `test`/`main` is free; only release tags consume GitHub Actions minutes (no Cloud Build exists for this repo).
- **Version-sync before tagging:** bump `desktop/package.json` AND both `version` fields in `desktop/package-lock.json` to match the tag. electron-builder names/publishes artifacts from the `package.json` version while `release-notes` derives the version from the tag — a mismatch puts artifacts on the wrong release and breaks the download links (existing users keep being told they're up to date). The `verify-version` CI job now hard-fails the release in seconds if `desktop/package.json` ≠ tag, before any build runs; `cd desktop && npm ci` still guards package.json↔lockfile drift.
- **Changelog auto-generates from commit subjects** since the previous tag — use conventional-commit style (`fix(scope): subject`) so release notes read cleanly.
- `GH_TOKEN` is provided by `secrets.GITHUB_TOKEN` (no manual secret needed).

### Auto-Update

The app uses `electron-updater` to check for updates on launch. `useUpdater.ts` hook + `UpdateBanner.tsx` component handle the UX. Update metadata (`.yml` and `.blockmap` files) are published alongside installers.

**Platform reality — Windows and macOS take different routes:** Windows (NSIS) auto-updates through electron-updater unsigned; don't disable it. macOS **cannot** use electron-updater's installer: Squirrel.Mac rejects any update whose code signature doesn't match the running app, and an ad-hoc signature has a different fingerprint every build. Adding a `zip` target does not fix that on its own — the signature is the blocker, not the archive format.

So since v1.7.0 macOS **installs updates itself** (`macUpdate.cjs` + `macUpdateInstaller.cjs`) instead of being notify-only: electron-updater still does the *detection*, and we do the download and install. `autoDownload` stays `false` on macOS either way.

**Checks:** `cd desktop && npm run verify:mac-updater` — 43 checks over the swap script, the installer I/O and staged-update persistence. Run it after touching either updater module and **after any electron-builder or electron bump** (the installer check reads the live release manifest, so it catches asset-naming changes). It does NOT cover a packaged app replacing itself; do that by hand as below.

**VERIFIED END-TO-END on macOS 26.6.1** (Aug 2026): a locally-built 1.6.1, ad-hoc signed exactly as CI signs, installed in `/Applications`, self-updated to the genuine published 1.6.2 — real URL, real 568 MB download, real checksum, swap, relaunch. **macOS App Management (TCC) did NOT block the bundle swap** for an ad-hoc-signed app with no `TeamIdentifier`. That was the single biggest risk to this design; it is answered. Re-test if Apple tightens App Management.

The Mac flow, and why each step is the way it is:
1. `update-available` fires → we download the `.dmg` named in `latest-mac.yml` straight from the release URL (`v<version>` tag — see CI/CD).
2. The published **SHA-512 (base64, not hex)** is verified, and **fails closed** — a manifest without the field aborts rather than installing unverified bytes.
3. `hdiutil attach` → **`ditto`** (never `cp -R`, which mangles the symlinks inside framework bundles) → the new `.app` is staged in a hidden folder **beside the installed one**, so the later `mv` is a same-volume rename rather than a gigabyte copy.
4. The staged bundle's **`CFBundleIdentifier`** must match — that is the strict identity gate. The version is only logged if it differs, because `mac.bundleShortVersion` or a pre-release tag can legitimately change it, and the checksum has already pinned the bytes to this release.
5. On "Restart & Install", a **detached** bash script waits for the app's PID to exit, then swaps the bundles. It is deliberately NOT `set -e` (that would abort before the rollback), and every path is quoted because the bundle name contains a space.

**What the SHA-512 does and does not prove.** `latest-mac.yml` and the `.dmg` come from the same release over the same channel, so it detects **corruption, not tampering** — anyone who can publish a release can publish a matching hash. There is no signature and no out-of-band trust anchor. Do not describe it as a security control; if you want one, sign the manifest with a key compiled into the app.

**The real safety property is the swap**, and three things enforce it — all were defects first:
- The rollback's exit status **is checked** before anything is deleted. The backup lives *inside* the staging directory, so deleting that directory after a failed rollback left the user with no app at all.
- The script writes a **log and a failure marker** to `userData`. Everything it does happens after the app exits with stdio discarded; without these, a failed swap is invisible and the app silently re-downloads forever.
- `restart-and-install` confirms the staged app and script still exist **before quitting**, and aborts on spawn error. Quitting on a vanished script means the app closes and nothing ever reopens it.

**Failures before the quit fall back to `update-available-manual`** (the old notify-only behaviour). Failures *after* the quit cannot fall back — they are covered by the rollback and the failure marker instead. `selfUpdateBlockedReason()` refuses up front when the app isn't writable, is running from `/Volumes`, or is a dev build.

**Staged updates persist across launches.** `staged.json` in the staging folder records what is staged; `adoptStagedUpdate()` re-adopts it at launch. Deleting the folder unconditionally (the original behaviour) made anyone who postponed the restart re-download ~568 MB **on every launch, forever**. A *newer* version arriving while one is staged is **deferred**, not re-staged — re-staging deletes the working update first, so a failed download would lose a perfectly installable one.

**`pickMacAsset` prefers `.dmg` and filters by architecture.** The zip branch has never run in production; if a `zip` target is added later it must not silently become every Mac user's install path on the release that adds it. electron-updater has `filterFilesForArch()` for the same reason — without it, adding an x64 target would hand Intel builds to Apple Silicon users and every check would still pass. Ambiguity returns `null` → manual download.

**Asset names use dash-substitution, NOT percent-encoding.** Verified against a real build: the local artifact is `Redaction Tool-1.6.2-arm64.dmg` but `latest-mac.yml` records `Redaction-Tool-1.6.2-arm64.dmg`. electron-builder rewrites spaces to dashes for the published name and electron-updater matches (`p.replace(/ /g, "-")`); percent-encoding a space would 404.

**No Gatekeeper prompt on update:** macOS only attaches `com.apple.quarantine` to files downloaded by a *browser*. Because the app fetches the update itself, the swapped bundle launches with no security warning. The script does **not** run `xattr -dr` — it was pointless (nothing to strip) while acting as an explicit Gatekeeper bypass, and `/usr/bin/xattr` is a python3 shim that can pop the Command Line Tools installer. This does **not** help first-time installs, which still show the unidentified-developer warning until the app is signed.

**Updater spans 6 files — keep in sync:** `electron/main.cjs` `setupAutoUpdater()` (autoUpdater events → `webContents.send`) → `electron/macUpdate.cjs` + `electron/macUpdateInstaller.cjs` (macOS install) → `electron/preload.cjs` (`onUpdate*` bridges) → `src/hooks/useUpdater.ts` (state machine + a download-stall watchdog so it never hangs on "Downloading…") → `UpdateBanner.tsx`/`AboutModal.tsx` (render `available`/`error` with a Download link). The renderer is deliberately **platform-agnostic** — macOS now drives the same `update-available → download-progress → update-downloaded` events Windows does, so no UI branch was needed. `quitAndInstall(true, true)` (silent + relaunch) — don't revert to no-args; with NSIS `oneClick:false` the no-arg form pops the installer wizard.

**The renderer's stall watchdog resets on percent *change*, so progress must keep moving.** The download therefore owns only **0–90%** and the staging steps emit 92/96/98 — a `ditto` of a ~1 GB bundle reports nothing, and on a slow disk it exceeded `DOWNLOAD_STALL_MS` (90s), so a perfectly successful update told the user it had timed out. Below roughly 100 KB/s the download itself still can't advance a whole percent in 90s and correctly falls back to the manual prompt; don't "fix" that by lengthening the watchdog without also making progress finer-grained.

**Restart is blocked mid-run.** Both `UpdateBanner` and `UpdateCard` disable "Restart & install" while the store's `isProcessing` is true: quitting then would abort the redaction, and the Python backend could still hold port 8765 as the new copy starts (rule #55). The swap script also sleeps 2s before relaunching for the same reason — verified in the end-to-end run, where the relaunched app came up with a healthy backend and no port dialog.

**Where the update UI appears:** a full `UpdateCard` on `mode_selection` (the landing screen) and the `UpdateBanner` everywhere else — never both, since two notices read as two updates. The thin banner alone was easy to scroll past; the machine this was built on had been sitting on v1.5.0 while v1.6.2 was current. Only ACTIONABLE states get the card; "you're up to date" stays in the quiet banner, or the prominent slot trains people to ignore it.

**ESLint baseline:** `cd desktop && npm run lint` reports **7 errors + 1 warning** — errors across `DocumentCard.tsx`, `RedactionProgress.tsx`, `Sidebar.tsx`, `Walkthrough.tsx`, and `FinalConfirmation.tsx`; the warning in `DocumentReview.tsx` (`react-hooks/exhaustive-deps`). New code must not increase the count, but these aren't yours to fix unless you're already touching those files.
`eslint.config.js`'s `globalIgnores` includes `release` alongside `dist` — without it, a local Mac/Windows build (`npm run dist:mac`/`dist:win`) leaves `desktop/release/` on disk (gitignored, but not eslint-ignored) and `eslint .` sweeps up a bundled third-party file inside it, adding a spurious extra warning. Don't drop `release` from `globalIgnores`, or the baseline count above stops being deterministic.

---

## What's Next / Known Gaps

- **Code signing**: Mac DMG ad-hoc signed (not notarised — and see the `mac.identity: "-"` note under CI/CD; v1.6.1–v1.7.0 accidentally shipped with no ad-hoc signature at all); Windows `.exe` unsigned → first-launch OS warnings (release-notes template + README explain the bypass for both platforms). **Consequence:** the *install-time* warning remains on both platforms. It no longer affects updating — macOS self-updates without a signature as of v1.7.0 (see Auto-Update), and that path deliberately avoids Gatekeeper by downloading the update itself. Signing would still be worth buying purely to remove the first-launch warning for new users. Windows signing note: Azure Trusted Signing (cheapest) is **not available in Australia** (US/CA/EU/UK only); the AU path is a traditional OV cert on a hardware token/HSM, and EV no longer bypasses SmartScreen (changed 2024).
- **Desktop UX polish**: COMPLETED (March 2026). Walkthrough, tooltips, before/after preview, witty progress comments, custom output path, typographic logo.
- **Windows**: SUPPORTED as of v1.1.0. NSIS installer built via CI. Bundled Python + Tesseract. LibreOffice prompted on first run via Setup screen.
- **Linux**: Not supported. No current plans.
- **Auto-update**: Implemented via `electron-updater`. Checks on launch + manual "Check for Updates" in About modal. Uses `latest.yml`/`latest-mac.yml` from GitHub Releases.
- **Setup screen**: First-run LibreOffice + NER detection (`desktop/src/pages/Setup.tsx`). Shows download link, "Check Again", and "Skip for now". NER failure is now a blocking error.
- **Fuzzy name matching**: Nickname matching is now implemented via `nickname_map.py`. True fuzzy/edit-distance matching remains a future feature.
- **spaCy mislabels professions as `NRP (NER)`**: "Paediatrician", "Psychologist" etc. are detected as nationality/religious/political-group entities and so are offered for removal. Harmless in redact mode (a black box over a job title), but in de-identify mode removing the job title costs the AI real context while gaining no privacy — the role label already conveys it. The review screen lets the user deselect them. Not worked around, because changing detection would affect the shipped redact pathway too.
- **Non-student nicknames aren't tracked**: `include_nicknames=True` is only passed for the student (`pseudonym_map.py`), so `sanitise_custom_role` would not catch a custom role spelling out a *colleague's* nickname ("Genny" for Genevieve). Low likelihood for job titles; documented rather than silently assumed away.
- **GLiNER removed** (March 2026): GLiNER and PyTorch removed for bundle simplification. Two-engine architecture: regex + Presidio/spaCy.
- **Batch processing** (multiple students at once): Not implemented.
- **OCR redaction quality**: Depends entirely on scan quality. Low-DPI or blurry scans may cause missed words.
- **`docs/legacy/`**: Contains 6 legacy markdown files moved from root during cleanup. Outdated — README.md is the authoritative user documentation.
- **`docs/plans/`**: Contains implementation plans from each development phase. Reference only.
- **Dependency advisories (August 2026)**: `npm audit` is at **1 remaining high** — `electron` GHSA-9f4c-93c8-jc8g, which needs a major runtime bump and has its own plan (`docs/plans/2026-08-08-electron-major-upgrade.md`). Everything else is cleared. **Do NOT run `npm audit fix --force` here**: it resolves that last one by installing electron@43 — a three-major jump on the runtime that ships to users. Use the plan.

  Triage rule for this repo, because most advisories here are noise: `dependencies` in `desktop/package.json` ship, and so does **electron** (a devDependency only by convention — electron-builder bundles the runtime). Everything reached solely through `electron-builder`, `@electron/get`, vite or tailwind is **build-time only and never enters the `.dmg`/`.exe`**. The August sweep was 14 Dependabot alerts of which 12 were build-time; check the dependency path before treating a number as urgent.

  Also note `npm audit`'s count moves on its own as new advisories are published — 13 of those 14 appeared in the fortnight after the July pass, against an unchanged lockfile. A jump in the count does not imply anyone changed a dependency.

  History: the July pass cleared js-yaml, tar, shell-quote, brace-expansion and the vitest 2→3 bump. The August pass bumped `electron-updater` 6.8.3→6.8.9 (pulling `builder-util-runtime` 9.5.1→9.7.0, the one **shipped** high of the batch), and `npm audit fix` moved app-builder-lib, nanoid, postcss, undici and brace-expansion. esbuild's GHSA-g7r4-m6w7-qqqr was cleared **downward** — the vulnerable range is `>= 0.27.3, < 0.28.1`, so npm stepped to 0.27.2 rather than to the vite-8 cascade. That means the old "esbuild is unfixable without vite 8" note no longer applies, but the underlying constraint still does: vite 8 remains outside the peer range of `@vitejs/plugin-react`, `@tailwindcss/vite` and vitest 3.

---

## Sample Data

`sample/` contains real documents. This repo is public. Ensure real student documents are never committed — keep sample data synthetic or anonymised. The `sample/redacted_2/` and `sample/redaction_log.txt` files are in `.gitignore` (output files — never commit these).
