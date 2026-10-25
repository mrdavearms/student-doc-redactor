# Security Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every lead, coverage gap and data-protecting hardening note from security audit run-1, so that a "redacted" or "de-identified" output holds no recoverable student PII and no PII copy outlives the session.

**Architecture:** Every lead is first proven with a failing pytest or vitest test built from synthetic documents, then fixed at the last trusted decision point. A new post-save residue check (`verify_no_hidden_residue`) inspects the layers the existing render-and-OCR verifier cannot see: image bytes, attachments, document properties and thumbnails. Lifecycle ownership of temporary PII copies moves to Electron, which outlives the backend process.

**Tech Stack:** Python 3.13, PyMuPDF 1.27.2 (`import fitz`), Pillow 13, pytesseract, FastAPI; Electron 43 main-process CommonJS, React 19, vitest 5.

**Spec:** The audit output in `~/security-audit-skill/redaction-tool/run-1/`: `NEEDS-VALIDATION.md` (the seven leads, each with its trace and validation plan) and `REPORT.md` sections 6 and 7 (hardening notes and the two deferred coverage units). Read the lead's section in `NEEDS-VALIDATION.md` before starting its task.

## Global Constraints

- Work on the `test` branch only. Never merge `test` into `main` without Dave's explicit OK (global CLAUDE.md).
- Python tests: `venv/bin/python3.13 -m pytest` (never `venv/bin/pytest`; its shebang is broken).
- Desktop checks: `cd desktop && npm test`, `npm run build`, `npm run lint`. The lint baseline is 7 errors + 1 warning; it must not rise.
- Test fixtures are synthetic only. Never read, copy or reference anything under `sample/`. Use the dummy names "Joe Bloggs", "Billy Bob" and "Dummy School".
- Never use `fitz.PDF_REDACT_IMAGE_REMOVE` (CLAUDE.md rule 14).
- Every case-sensitivity decision goes through `_pii_visible_in_text` / `case_rules` (CLAUDE.md rules 7 and 7a). A new verifier that disagrees with them will quarantine correct files.
- Electron main-process logic goes in a pure `.cjs` module with vitest tests, never inline in `main.cjs` (CLAUDE.md "Test (desktop)").
- A file that fails any verifier is quarantined through the existing `os.replace` path in `redaction_service._process_document` (rule 67). Do not add a second quarantine path.
- Commit messages use conventional-commit titles on one line, with the body written through `git commit -F <file>` (memory: garbled titles broke release notes).
- Each task updates the CLAUDE.md rule it changes, in the same commit.

## Review Focus

1. **Rotated scans.** A `/Rotate 90` searchable scan must have the name's pixels blanked in the right place, not a stripe beside it. Test added to Task 2.
2. **One image used on many pages.** A letterhead image shared by every page must not be blanked on pages it was not redacted on, and the Task 3 fresh-resources change must not blank page 2 when page 1 is rebuilt. Tests added to Tasks 2 and 3.
3. **Tesseract missing at verification time.** The residue check must quarantine with a clear message, never crash or pass silently. Test added to Task 7.
4. **Output folder reached through a symlink or a different letter case.** `folder_holds` must still detect that it contains the source folder. Test added to Task 8.
5. **A temp folder Electron cannot delete** (antivirus lock on Windows, permission error). Startup and quit must carry on and must never delete anything outside the app's own folders. Test added to Task 11.

---

## Phase 0: Branch

### Task 0: Reset `test` to `main`

`test` (local and GitHub) is at 18f6d71, the old history with garbled commit titles. Merging it into `main` later would put those titles into the next release notes.

- [ ] **Step 1: Dave runs this in a terminal** (the agent's force push is refused by the permission check):

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool" && git push --force-with-lease=test:18f6d71 origin main:test && git checkout test && git reset --hard origin/test
```

- [ ] **Step 2: Verify** with `git rev-parse --short test origin/test main`. Expected: all three print `8f87713`.

- [ ] **Step 3: Commit this plan on `test`**

```bash
git add docs/plans/2026-10-24-security-audit-fixes.md
git commit -m "docs(plans): security audit fixes plan"
```

---

## Phase 1: Redacted PDF output

### Task 1: Shared synthetic-PDF fixtures

**Files:**
- Create: `tests/security_fixtures.py`
- Test: `tests/test_security_fixtures.py`

**Interfaces:**
- Produces:
  - `text_png(text: str, width: int = 1240, height: int = 1754, at: tuple[int, int] = (150, 900), font_size: int = 48) -> bytes`: white PNG with black text, using `ImageFont.load_default(size=font_size)`.
  - `make_image_only_pdf(path: Path, png: bytes, pages: int = 1, share_resources: bool = False) -> None`: each page holds only the PNG at `page.rect`. `share_resources=True` points every page's `/Resources` at one indirect dictionary.
  - `make_searchable_scan_pdf(path: Path, png: bytes, hidden_text: str, rect: fitz.Rect, rotate: int = 0) -> None`: full-page image plus `insert_textbox(..., render_mode=3)` of `hidden_text` inside `rect`.
  - `image_sha256s(pdf_path: Path) -> set[str]`: SHA-256 of `doc.extract_image(x)["image"]` for every xref whose `/Subtype` is `/Image`.
  - `mean_luminance(pdf_path: Path, page_index: int, rect: fitz.Rect) -> float`: mean 0–255 grey value of the page's largest image, cropped to `rect` mapped into image pixels.
  - `ocr_words_for(text: str, box: tuple[int, int, int, int]) -> dict`: a `pytesseract.image_to_data` DICT result with one word per token, split evenly across `box`, in the shape `tests/test_ocr_redaction.py` already mocks.

- [ ] **Step 1:** Write `test_text_png_is_png`, `test_searchable_scan_has_hidden_text` (`page.get_text()` contains the text, `len(page.get_images()) == 1`) and `test_image_sha256s_finds_inserted_png`.
- [ ] **Step 2:** Run `venv/bin/python3.13 -m pytest tests/test_security_fixtures.py -v`. Expected: FAIL, `ModuleNotFoundError: security_fixtures`.
- [ ] **Step 3:** Implement the module. Insert `sys.path` for `src/core` the way `tests/test_metadata_stripping.py` does.
- [ ] **Step 4:** Rerun. Expected: 3 passed.
- [ ] **Step 5:** Commit: `test(security): synthetic PDF fixtures for redaction residue tests`.

### Task 2: Lead 1, blank image pixels under text-layer redactions

**Files:**
- Modify: `src/core/redactor.py:318` (main loop) and `:530` (`_redact_zones` text-layer branch)
- Test: `tests/test_redaction_residue.py` (new)

**Interfaces:**
- Consumes: Task 1 fixtures.

- [ ] **Step 1: Write the failing tests** in class `TestTextLayerImagePixels`. Patch `redactor.pytesseract.image_to_data` to return no words, so Stage 2 misses.
  - `test_name_pixels_blanked_when_ocr_misses`: searchable scan with "Joe Bloggs" drawn at `(150, 900)` and hidden text over the same rect. After `redact_pdf(..., [RedactionItem(page_num=1, text="Joe Bloggs")])`, assert `mean_luminance(out, 0, name_rect) < 40`.
  - `test_header_zone_pixels_blanked`: "Dummy School" drawn in the top 10%. After `redact_header_footer=True`, assert `mean_luminance(out, 0, header_rect) < 40`.
  - `test_rotated_scan_name_pixels_blanked`: same as the first test with `rotate=90`. Assert the name region is blanked, and that `mean_luminance` of an untouched body region stays `> 200`.
  - `test_shared_image_other_page_untouched`: two pages sharing one image xref; redact a name only present on page 1's hidden text. Assert page 2 renders identically outside the name rect (pixel compare of `get_pixmap` regions).
- [ ] **Step 2:** Run `venv/bin/python3.13 -m pytest tests/test_redaction_residue.py -k TextLayer -v`. Expected: the first three FAIL (luminance about 255).
- [ ] **Step 3:** Change both calls to `apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)`. Update the comment above line 318, and rule 14 in CLAUDE.md, to say PIXELS is required and REMOVE is still forbidden.
- [ ] **Step 4:** Rerun the class, then the full suite. Expected: all pass, including `tests/test_zone_redaction.py` and `tests/test_redactor.py`.
- [ ] **Step 5:** Commit: `fix(redactor): blank image pixels under text-layer redactions`.

### Task 3: Lead 2, drop the original scan when a page is rebuilt

**Files:**
- Modify: `src/core/redactor.py` (`_redact_ocr_page` around lines 899-906, `_redact_zones` image-only branch around lines 513-517)
- Test: `tests/test_redaction_residue.py`

**Interfaces:**
- Produces: `PDFRedactor._replace_page_with_image(page: fitz.Page, png: bytes) -> None`. Both call sites use it.

- [ ] **Step 1: Write the failing tests** in class `TestPageReplacement`, mocking OCR with `ocr_words_for("Joe Bloggs", box)`.
  - `test_original_scan_not_in_output`: `orig = image_sha256s(src)`; after redaction `assert orig.isdisjoint(image_sha256s(out))`.
  - `test_zone_blanking_drops_original_scan`: same assertion with `redact_header_footer=True` and no items.
  - `test_shared_resources_other_page_keeps_its_image`: `make_image_only_pdf(..., pages=2, share_resources=True)`. Redact page 1 only. Assert page 2's pixmap is not blank (mean luminance `< 250` over the text area).
- [ ] **Step 2:** Run with `-k PageReplacement`. Record whether `test_original_scan_not_in_output` fails. If it passes, MuPDF's `clean=True` sanitize already drops the image: lead 2 is refuted. Keep the tests as regression guards, and still do Step 3, because the fix makes the behaviour independent of a library default.
- [ ] **Step 3:** Implement `_replace_page_with_image`: `page.clean_contents()`, empty every content xref, then `doc.xref_set_key(page.xref, "Resources", "<<>>")` so the page gets its own empty resource dictionary (never edit a shared one), then `page.insert_image(page.rect, stream=png, overlay=True)`. Replace both call sites. Update CLAUDE.md rule 16 to show the fresh-resources line.
- [ ] **Step 4:** Rerun the class and `tests/test_ocr_redaction.py`. Expected: all pass.
- [ ] **Step 5:** Commit: `fix(redactor): rebuilt scanned pages no longer carry the original image`.

### Task 4: Lead 3, remove attachments and embedded media from pages

**Files:**
- Modify: `src/core/redactor.py` (`_delete_pii_annotations`, lines 962-982)
- Test: `tests/test_metadata_stripping.py`

**Interfaces:**
- Produces: module constant `_EMBEDDING_ANNOT_TYPES = {fitz.PDF_ANNOT_FILE_ATTACHMENT, fitz.PDF_ANNOT_SOUND, fitz.PDF_ANNOT_MOVIE, fitz.PDF_ANNOT_RICH_MEDIA, fitz.PDF_ANNOT_3D, fitz.PDF_ANNOT_SCREEN}`. Task 7 imports it.

- [ ] **Step 1:** Write `test_file_attachment_annotation_removed`. Call `page.add_file_annot(fitz.Point(500, 50), b"Joe Bloggs original draft", "orig.txt", desc="attachment")`, with body text "Joe Bloggs attended". Redact "Joe Bloggs". Assert no annotation in the output has type `PDF_ANNOT_FILE_ATTACHMENT`, and `b"Joe Bloggs" not in out_doc.tobytes(expand=255)`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** In `_delete_pii_annotations`, delete any annotation whose `annot.type[0]` is in `_EMBEDDING_ANNOT_TYPES` before the text match. Fix the comment at line 1056 to say the name tree and page attachments are both removed.
- [ ] **Step 4:** Rerun `tests/test_metadata_stripping.py`. Expected: all pass.
- [ ] **Step 5:** Commit: `fix(redactor): strip file-attachment and media annotations`.

### Task 5: Lead 4, remove the whole Info dictionary and other hidden carriers

**Files:**
- Modify: `src/core/redactor.py` (`_strip_metadata`, lines 1040-1073)
- Test: `tests/test_metadata_stripping.py`

**Interfaces:**
- Produces: `PDFRedactor._strip_hidden_carriers(doc: fitz.Document) -> None`, called at the end of `_strip_metadata`.

- [ ] **Step 1: Write failing tests:**
  - `test_custom_info_key_removed`: add `/StudentName (Joe Bloggs)` and `/Company (Dummy School)` with `doc.xref_set_key(info_xref, ...)`. After redaction, `doc.xref_get_key(-1, "Info")[0] == "null"`, or every key is absent.
  - `test_page_thumbnail_removed`: set the page `/Thumb` to an image xref. After redaction, `xref_get_key(page.xref, "Thumb")[0] == "null"`.
  - `test_page_and_image_xmp_removed`: give the page and its image a `/Metadata` stream holding "Joe Bloggs". Assert `b"Joe Bloggs" not in tobytes(expand=255)`.
  - `test_piece_info_removed`: page and catalog `/PieceInfo` holding "Joe Bloggs"; same assertion.
- [ ] **Step 2:** Run them. Expected: all four FAIL.
- [ ] **Step 3:** Replace the keyed `set_metadata` call with `doc.set_metadata({})`, which nulls `/Info` in PyMuPDF 1.27.2. Implement `_strip_hidden_carriers`: for every page, null `Thumb`, `Metadata` and `PieceInfo`; for every image xref, null `Metadata`; on the catalog, null `PieceInfo`. Update CLAUDE.md rule 10 with the full list.
- [ ] **Step 4:** Rerun `tests/test_metadata_stripping.py`. Expected: all pass. `test_author_cleared_after_redaction` must still pass.
- [ ] **Step 5:** Commit: `fix(redactor): remove the whole Info dictionary, thumbnails and page metadata`.

### Task 6: Inherited form-field values

**Files:**
- Modify: `src/core/redactor.py` (`_delete_pii_widgets`, lines 910-948)
- Test: `tests/test_widget_redaction.py`

- [ ] **Step 1:** Write `test_parent_field_value_removed`. Build an AcroForm with a parent field `/V (Joe Bloggs)` and one kid widget that inherits it (set with `xref_set_key`). Redact "Joe Bloggs". Assert `b"Joe Bloggs" not in tobytes(expand=255)`.
- [ ] **Step 2:** Run it. Expected outcome is unknown. If it passes, keep it as a regression guard, skip Step 3, and record that the hunter's hardening note was refuted.
- [ ] **Step 3:** After deleting a matching widget, walk `/Parent` from its xref (captured before deletion) and null `/V` and `/DV` on any ancestor whose value matches.
- [ ] **Step 4:** Rerun `tests/test_widget_redaction.py`. Expected: all pass.
- [ ] **Step 5:** Commit: `fix(redactor): clear inherited form-field values`.

### Task 7: Residue verifier, a second check the render cannot fool

**Files:**
- Modify: `src/core/redactor.py` (add `verify_no_hidden_residue`), `src/services/redaction_service.py:386-395`
- Test: `tests/test_redaction_residue.py`, `tests/test_quarantine.py`

**Interfaces:**
- Consumes: `_EMBEDDING_ANNOT_TYPES` (Task 4).
- Produces: `PDFRedactor.verify_no_hidden_residue(pdf_path: Path, redacted_texts: List[str]) -> Tuple[bool, List[str]]`, with the same contract as `verify_redaction_ocr`: `(all_clean, failure_messages)`, handle closed in `finally`.

- [ ] **Step 1: Write failing tests** in class `TestResidueVerifier`. Each builds a bad PDF directly, not through `redact_pdf`:
  - `test_flags_unredacted_image_bytes`: image-only PDF of "Joe Bloggs" with a black rectangle drawn over it as page content. Patch `redactor.pytesseract.image_to_string` to return "Joe Bloggs". Expect `(False, [msg])` with "image" in `msg`.
  - `test_flags_info_key`, `test_flags_file_attachment` and `test_flags_thumbnail`: one failure each.
  - `test_clean_output_passes`: run `redact_pdf` on the Task 2 searchable scan, then the verifier with OCR patched to return "". Expect `(True, [])`.
  - `test_lowercase_common_word_not_flagged`: image OCR returns "young people", redacted text "Young". Expect a pass (rule 7a).
  - `test_tesseract_missing_quarantines` (Review Focus 3): patch `image_to_string` to raise `pytesseract.TesseractNotFoundError`. Expect `(False, [msg])` with a message naming the image check.
  - In `tests/test_quarantine.py`, `test_residue_failure_quarantines`: patch `verify_no_hidden_residue` to return `(False, ["x"])`. Assert the output ends `.UNVERIFIED.pdf` and `result.success is False`.
- [ ] **Step 2:** Run both files. Expected: FAIL (`AttributeError: verify_no_hidden_residue`).
- [ ] **Step 3:** Implement four checks:
  1. Every `/Image` xref: `extract_image` → Pillow → `pytesseract.image_to_string`, then each text through `_pii_visible_in_text` with `len(text.strip()) >= 2`, matching `verify_redaction_ocr`.
  2. `/Info` present with any key.
  3. `embfile_count() > 0`, or any annotation type in `_EMBEDDING_ANNOT_TYPES`.
  4. Any page `/Thumb`.

  In `_process_document`, call it after `verify_redaction_ocr`, extend `ocr_failures` with its messages, and let the existing quarantine branch run. Add the new check to CLAUDE.md rule 9 as a third verification method.
- [ ] **Step 4:** Run the full Python suite. Expected: all pass. Then time `tests/test_common_word_names.py::TestNoQuarantineEitherPathway` before and after, and record both times in the commit body.
- [ ] **Step 5:** Commit: `feat(redactor): verify image bytes, attachments and properties after redaction`.

---

## Phase 2: Output folders and logs

### Task 8: Lead 5, an output folder that contains the originals

**Files:**
- Modify: `src/core/redactor.py` (add `folder_holds` beside `is_same_file`, line 21), `src/services/deidentification_service.py:333` and `:382-393`, `desktop/src/pages/DeidentifyCompletion.tsx:117-128`
- Test: `tests/test_deidentification_service.py`, `tests/test_single_document.py`

**Interfaces:**
- Produces: `folder_holds(outer: Path, inner: Path) -> bool`. True when `inner` is `outer` or lies anywhere beneath it. It compares `outer` with `inner` and each of `inner.parents` using `os.path.samefile`, which handles case-insensitive file systems and symlinks. It returns False on `OSError`. Task 9 uses it.

- [ ] **Step 1: Write failing tests:**
  - `test_ancestor_output_folder_flags_originals`: `folder_path=tmp/Reports/Billy`, `custom_output_path=tmp/Reports`. Assert `results.output_folder_holds_originals is True`, and the key file text contains "Do not share the folder itself".
  - `test_child_output_folder_is_safe`: the default `deidentified/` inside the source folder gives `False`.
  - `test_folder_holds_symlink_and_case` (Review Focus 4): a symlinked parent, and on macOS an upper-case spelling of the parent, both give True.
- [ ] **Step 2:** Run them. Expected: the first test FAILS.
- [ ] **Step 3:** Implement `folder_holds`. Delete `_same_folder` and use `folder_holds(output_folder, request.folder_path)`. In `DeidentifyCompletion.tsx`, make the safe-to-share sentence also depend on `!hasVerificationFailures` (REPORT.md section 6). Update CLAUDE.md rule 50 to say "contains", not "is".
- [ ] **Step 4:** Rerun both files, then `cd desktop && npm run build && npm run lint`. Expected: pass, lint at baseline.
- [ ] **Step 5:** Commit: `fix(deidentify): treat an output folder that contains the originals as unsafe`.

### Task 9: Coverage gap 2, the redact-mode output folder and log

**Files:**
- Modify: `src/services/redaction_service.py` (`RedactionResults`, `execute`), `src/core/logger.py` (`generate_log`, lines 60-75), `backend/schemas.py:211-220`, `backend/main.py` (`/api/redact` response builder), `desktop/src/types.ts`, `desktop/src/pages/Completion.tsx`
- Test: `tests/test_backend_redact.py`, `tests/test_filename_redaction.py`

**Interfaces:**
- Consumes: `folder_holds` (Task 8).
- Produces: `RedactionResults.output_folder_holds_originals: bool = False`, mirrored in `RedactionResultsResponse` and the TypeScript `RedactionResults`.

- [ ] **Step 1: Write failing tests:**
  - `test_redact_flags_output_folder_holding_originals`: run `custom_output_path` equal to `folder_path`, then a parent of it. Assert the response field is True both times.
  - `test_redact_log_carries_do_not_share_header`: `log_content` begins with a line containing "contains the names that were removed".
  - `test_output_and_quarantine_names_have_no_student_name`: a source named "Billy Bob Report.pdf", once forced to fail verification. Neither the output name nor the `.UNVERIFIED.pdf` name contains "Billy" or "Bob".
- [ ] **Step 2:** Run them. Expected: the first two FAIL; record the result of the third.
- [ ] **Step 3:** Set the flag in `execute` with `folder_holds(redacted_folder, request.folder_path)`. Add the header line, first in `generate_log`, only when `operation` is the redact default. Pass the flag through the schema and response. In `Completion.tsx`, show the same red "Don't share the folder itself, send the individual PDFs; it also holds your originals and redaction_log.txt" panel style that `DeidentifyCompletion.tsx` uses. Fix filename stripping only if the third test failed.
- [ ] **Step 4:** Run the Python suite, then `npm run build && npm run lint`. Expected: pass, lint at baseline.
- [ ] **Step 5:** Commit: `fix(redact): warn when the output folder holds the originals and the log`.

### Task 10: De-identify audit log carries no names

**Files:**
- Modify: `src/services/deidentification_service.py:264-267` and `:323-327`
- Test: `tests/test_deidentification_service.py`

- [ ] **Step 1:** Write `test_deidentify_log_has_no_folder_or_file_names`. The folder is `tmp/Billy Bob/` and the file `Billy Bob plan.pdf`, with one document forced to raise. Assert "Billy" and "Bob" are absent from `log_content`.
- [ ] **Step 2:** Run it. Expected: FAIL (the `Folder:` line and the exception branch).
- [ ] **Step 3:** Construct `RedactionLogger` with the folder name passed through `strip_pii_from_filename`, and use `safe_name` in the exception branch. Keep `RedactionLogger`'s signature unchanged (rule 43). The redact log stays byte-for-byte as it was apart from Task 9's header line.
- [ ] **Step 4:** Rerun. Expected: pass.
- [ ] **Step 5:** Commit: `fix(deidentify): keep folder and file names out of the label-only log`.

---

## Phase 3: PII copies on disk

### Task 11: Lead 6, Electron owns the conversion temp folder

**Files:**
- Create: `desktop/electron/tempRoot.cjs`, `desktop/tests/tempRoot.test.ts`
- Modify: `desktop/electron/main.cjs` (`startBackend` env around line 219; the `before-quit` exit path, lines 743-771; app `ready`), `src/core/document_converter.py:30-38`
- Test: `tests/test_document_converter.py`

**Interfaces:**
- Produces (`tempRoot.cjs`):
  - `createRoot(tmpdir: string) -> string`: `fs.mkdtempSync(path.join(tmpdir, 'redaction-tool-'))`.
  - `removeRoot(root: string) -> boolean`: `fs.rmSync(root, {recursive: true, force: true})` inside try; returns false on error.
  - `sweepStale(tmpdir: string, keep: string) -> string[]`: removes every direct child named `redaction-tool-*` that is a real directory (`lstatSync().isDirectory()`, not a symlink), is not `keep`, and on POSIX has `uid === process.getuid()`. It returns the removed paths and never throws.
- Produces (Python): `_temp_root()` uses `REDACTION_TEMP_ROOT` when it is set, absolute and an existing directory. Otherwise it falls back to `mkdtemp`. The `atexit` registration stays in both cases.

- [ ] **Step 1: Write failing tests:**
  - vitest: `createRoot makes a private directory`; `sweepStale removes old roots and keeps the current one`; `sweepStale ignores a symlink named redaction-tool-x and leaves its target intact`; `sweepStale ignores unrelated folders`; and for Review Focus 5, `removeRoot returns false and does not throw on an undeletable path` (make the path a read-only parent on POSIX; skip on win32).
  - pytest: `test_temp_root_uses_env_when_set`, and `test_temp_root_ignores_relative_env`.
- [ ] **Step 2:** Run `cd desktop && npm test -- tempRoot` and the pytest file. Expected: FAIL.
- [ ] **Step 3:** Implement `tempRoot.cjs`. In `main.cjs`, on `ready` before `startBackend`: call `sweepStale(os.tmpdir(), '')`, then `createRoot`, and pass the result as `REDACTION_TEMP_ROOT`. Call `removeRoot` after the backend's `exit` and in the 6-second `SIGKILL` branch of `before-quit`. Implement the Python env-var branch. Update CLAUDE.md rule 66: Electron creates and deletes the folder on every platform and every kind of exit, and sweeps leftovers at launch.
- [ ] **Step 4:** Run the vitest and pytest files, `node --check electron/main.cjs`, then `npm run build`. Expected: pass.
- [ ] **Step 5:** Commit: `fix(lifecycle): Electron removes unredacted conversions on every exit`.

### Task 12: "Start over" also deletes the converted copies

**Files:**
- Modify: `backend/main.py` (`discard_detection`, line 598), `src/core/document_converter.py` (add `clear_conversions() -> None`)
- Test: `tests/test_folder_scan.py`

**Interfaces:**
- Produces: `document_converter.clear_conversions() -> None`: `rmtree(_temp_root() / "converted", ignore_errors=True)`, but only if `_TEMP_ROOT` is already set (it must not create one).

- [ ] **Step 1:** Write `test_discard_clears_converted_pdfs`: put a file in `_conversion_dir()`, POST `/api/detection/discard` with TestClient, and assert the file is gone.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `clear_conversions`, and call it from `discard_detection` after the cache is cleared. Add a line to CLAUDE.md rule 71.
- [ ] **Step 4:** Rerun. Expected: pass.
- [ ] **Step 5:** Commit: `fix(lifecycle): starting over deletes converted copies`.

### Task 13: Error log cannot keep names

**Files:**
- Modify: `desktop/src/components/ErrorBoundary.tsx:20-28`, `desktop/electron/main.cjs:681-691`
- Create: `desktop/electron/errorLog.cjs`, `desktop/tests/errorLog.test.ts`

**Interfaces:**
- Consumes: `sanitiseForReport` from `desktop/src/lib/faultReport.ts`.
- Produces: `appendBounded(file: string, entry: string, maxEntryBytes = 8192, maxFileBytes = 1048576) -> void`. It truncates the entry, and when the file would exceed the limit it renames it to `error.log.1`, replacing any earlier one.

- [ ] **Step 1:** Write vitest tests `truncates a long entry`, `rotates past one megabyte`, and in `faultReport.test.ts` `ErrorBoundary payload is sanitised` (test the exported helper the boundary calls).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Pass `message` and `stack` through `sanitiseForReport` in `ErrorBoundary` before `logError`. Use `appendBounded` in the `log-error` handler.
- [ ] **Step 4:** Run `npm test`, `npm run build` and `npm run lint`. Expected: pass, lint at baseline.
- [ ] **Step 5:** Commit: `fix(errors): sanitise and bound the local error log`.

---

## Phase 4: Nothing leaves the machine; only the app talks to its engine

### Task 14: Coverage gap 1, lock LibreOffice down before it opens a Word file

**Files:**
- Modify: `src/core/document_converter.py` (`_profile_dir`, lines 41-52; `convert_to_pdf`, around line 130)
- Test: `tests/test_document_converter.py`

**Interfaces:**
- Produces: `_write_locked_profile(profile: Path) -> None`. It writes `profile/user/registrymodifications.xcu` once per process, before the first `soffice` call.

- [ ] **Step 1:** Find the exact configuration paths of these properties in the installed schema:

```bash
grep -o '<component-schema[^>]*oor:name="[^"]*"[^>]*\|<group oor:name="[^"]*"\|<prop oor:name="\(DisableMacrosExecution\|MacroSecurityLevel\|BlockUntrustedRefererLinks\|DisableActiveContent\)"' /Applications/LibreOffice.app/Contents/Resources/registry/main.xcd | grep -B8 'DisableMacrosExecution\|MacroSecurityLevel\|BlockUntrustedRefererLinks\|DisableActiveContent'
```

  Also find the Writer link-update setting (`Update/Link` under a Writer `Content` group) in `writer.xcd`. Record each full `/org.openoffice.Office.<Component>/<Group>/...` path in the function's docstring. Values: `DisableMacrosExecution=true`, `MacroSecurityLevel=3`, `BlockUntrustedRefererLinks=true`, `DisableActiveContent=true`, Writer link update = never (record the schema's value for "never").
- [ ] **Step 2:** Write failing tests:
  - `test_profile_written_before_conversion`: mock `subprocess.run` and assert the `.xcu` exists, holding each of the four property names with the values above, at the time of the call.
  - `test_no_remote_fetch_from_linked_image`, marked `@pytest.mark.skipif(resolve_libreoffice() is None)`: start a `http.server` on `127.0.0.1:0` in a thread that records requests. Build a synthetic `.docx` (python-docx, plus a relationship with `TargetMode="External"` pointing at that server), convert it through `DocumentConverter`, and assert zero requests were recorded.
- [ ] **Step 3:** Run them. Expected: the first FAILS. Record the second's result; if it passes before the fix, keep it as a regression guard.
- [ ] **Step 4:** Implement `_write_locked_profile`, and call it from `_profile_dir()` the first time. Add CLAUDE.md rule 82: LibreOffice runs with a locked profile; why; and the test that proves no network request.
- [ ] **Step 5:** Rerun `tests/test_document_converter.py`. Expected: pass.
- [ ] **Step 6:** Commit: `fix(convert): LibreOffice runs with macros, active content and remote links off`.

### Task 15: Lead 7, prove the engine's identity without sending the token

**Files:**
- Create: `desktop/electron/backendIdentity.cjs`, `desktop/tests/backendIdentity.test.ts`
- Modify: `backend/main.py` (`health_check`, lines 204-227), `backend/schemas.py:339-348`, `desktop/electron/main.cjs` (`waitForBackend`, lines 88-127), `desktop/src/api.ts` (`health`)
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Produces (`backendIdentity.cjs`):
  - `newNonce() -> string`: 32 random bytes, hex.
  - `healthHeaders(nonce: string) -> object`: returns `{ 'X-Health-Nonce': nonce }` and never includes `X-Api-Token`.
  - `isOwnBackend(body: object, token: string, nonce: string) -> boolean`: true only when `body.proof` is a 64-character hex string equal under `crypto.timingSafeEqual` to HMAC-SHA256(key = token, message = nonce), hex.
- Produces (backend): `HealthResponse.proof: Optional[str]`, which is `hmac.new(token, nonce, sha256).hexdigest()` when a token is configured and the nonce is 64 hex characters, otherwise None. `instance_match` is removed. Health stays unauthenticated.

- [ ] **Step 1: Write failing tests:**
  - vitest: `rejects a peer that claims instance_match true`; `rejects a wrong proof`; `accepts the correct HMAC`; `healthHeaders never carries the token`.
  - pytest, replacing the `instance_match` tests: `test_health_proof_matches_hmac`; `test_health_without_nonce_has_no_proof`; `test_health_rejects_malformed_nonce`; `test_health_never_reads_x_api_token` (send a wrong token plus a valid nonce: the proof is still correct and the response is still 200).
- [ ] **Step 2:** Run both. Expected: FAIL.
- [ ] **Step 3:** Implement the backend change and the module. `waitForBackend` makes a new nonce per probe, sends `healthHeaders(nonce)`, and resolves only on `isOwnBackend`. In `api.ts`, `health` calls `fetch` directly without the token (the renderer only needs reachability). Rewrite CLAUDE.md rule 55's "identity check" bullet: an HMAC proof replaces `instance_match`, and the token is never sent to an unverified listener.
- [ ] **Step 4:** Run `npm test`, `node --check electron/main.cjs`, the Python suite, and `npm run build`. Expected: pass.
- [ ] **Step 5:** Commit: `fix(startup): verify the engine by HMAC proof, never by sending the token`.

### Task 16: Narrow the token holder's reach

**Files:**
- Modify: `backend/main.py` (middleware lines 94-107; `/api/folder/open` lines 1077-1093; `/api/file/process` and `/api/file/validate`; `/api/preview` lines 1038-1074; `/api/redact` result path)
- Test: `tests/test_api_auth.py`, `tests/test_single_document.py`, new `tests/test_endpoint_narrowing.py`

**Interfaces:**
- Produces: module set `_previewable: set[str]`, holding resolved paths that are document keys in `_detection_cache` plus output and quarantine paths returned by `/api/redact`. It is cleared with the cache on discard.

- [ ] **Step 1: Write failing tests:**
  - `test_options_without_preflight_headers_requires_token`: a plain OPTIONS to `/api/redact` with no `Origin` returns 401.
  - `test_folder_open_refuses_a_file`: 400.
  - `test_file_process_refuses_relative_path` and `test_file_validate_refuses_relative_path`: 400.
  - `test_preview_refuses_unrelated_pdf`: 403. `test_preview_allows_detected_document_and_its_output`: 200.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement each change. The OPTIONS bypass applies only when both `Origin` and `Access-Control-Request-Method` are present. Map new error strings in `desktop/src/lib/errorMessage.ts` with tests (rule 29). Update CLAUDE.md rule 35 for the OPTIONS change, and the memory note "audit-2026-09-open-items" now that the preview item is closed.
- [ ] **Step 4:** Run the Python suite and `npm test`. Expected: pass.
- [ ] **Step 5:** Commit: `fix(api): narrow folder-open, preview and preflight handling`.

### Task 17: Pin Electron's browser settings

**Files:**
- Modify: `desktop/electron/main.cjs` (`webPreferences`, lines 301-305; after window creation), `desktop/electron/navigation.cjs:21-46`, `desktop/vite.config.ts`
- Test: `desktop/tests/navigation.test.ts`

- [ ] **Step 1:** Write a vitest test `file URL with a different host is refused` (`file://otherhost/<same path>`). Run it. Expected: FAIL.
- [ ] **Step 2:** Compare `url.host` as well in `isAllowedNavigation`. Set `sandbox: true` explicitly. Add `session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false))`. Add a Vite `transformIndexHtml` plugin that injects a CSP meta tag in `build` mode only:

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src http://127.0.0.1:8765; object-src 'none'; base-uri 'none'; frame-src 'none'
```

  Check `dist/index.html` for inline scripts first; if any exist, they must be moved out, not allowed by the policy.
- [ ] **Step 3:** Run `npm test`, `npm run build` and `npm run lint`. Then do a packaged `--dir` launch (rule 81's procedure) and confirm a full redaction run works with no CSP errors in the console.
- [ ] **Step 4:** Commit: `fix(electron): pin sandbox, deny permissions, add a content security policy`.

### Task 18: Updater never installs an older staged copy

**Files:**
- Modify: `desktop/electron/macUpdate.cjs` (`stagedUpdateIsUsable`, lines 213-219), `desktop/electron/main.cjs` (`adoptStagedUpdate` line 411; `restart-and-install` lines 618-664)
- Test: `desktop/tests/macUpdate.test.ts`

**Interfaces:**
- Produces: `isNewerVersion(candidate: string, current: string) -> boolean`, a numeric dotted compare in which pre-release tags sort below the release. It also produces `stagingPaths(appPath: string) -> {stagingDir, stagedApp, backupPath, scriptPath}`, derived from `path.dirname(appPath)`.

- [ ] **Step 1:** Write vitest tests `older staged version is not adopted`, `equal version is not adopted`, `stagingPaths derives every path from the app folder`. Run them. Expected: FAIL.
- [ ] **Step 2:** Implement both. `adoptStagedUpdate` uses `isNewerVersion` and deletes a stale staging folder. `restart-and-install` uses `stagingPaths`, never the marker's paths, regenerates the script with `buildSwapScript()`, and re-reads `CFBundleIdentifier` from the staged bundle before spawning. Create the staging folder with a non-recursive `mkdir` followed by an `lstat` check (real directory, owned by the current uid).
- [ ] **Step 3:** Run `npm test` and `npm run verify:mac-updater` (this reads the live manifest, which is normal for this repo).
- [ ] **Step 4:** Commit: `fix(updater): never swap in an older staged copy; derive paths, not trust them`.

---

## Phase 5: Verify and hand back

### Task 19: Full verification

- [ ] **Step 1:** Run `venv/bin/python3.13 -m pytest tests/ -v`. Expected: all pass. Record the new test count in CLAUDE.md "Test".
- [ ] **Step 2:** Run `cd desktop && npm test && npm run build && npm run lint`. Expected: pass, lint at baseline. Record the new vitest count in CLAUDE.md.
- [ ] **Step 3:** Do a packaged macOS `--dir` build and launch. Run synthetic documents through each pathway: a text PDF, an image-only scan, a searchable scan, a Word file, and pasted text. Then quit, and confirm no `redaction-tool-*` folder is left in `$TMPDIR`. Confirm `codesign -dv` still shows `flags=0x10002(adhoc,runtime)`.
- [ ] **Step 4:** Run the security audit again as run-2, with a sandbox available if possible, so the leads can move from needs-validation to fixed with evidence.
- [ ] **Step 5:** Ask Dave before merging `test` into `main` or tagging a release.

## Out of this plan

Release-pipeline hardening is a separate follow-up plan, because pinning action SHAs and generating hashed lock files needs network lookups. It covers: checksums for python-build-standalone and the spaCy model, `--require-hashes` pip installs, least-privilege workflow permissions with `persist-credentials: false`, actions pinned by commit SHA, and a test job before publish.
