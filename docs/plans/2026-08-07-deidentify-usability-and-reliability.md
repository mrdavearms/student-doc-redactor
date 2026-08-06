# De-identify Usability & Reliability — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-08-07 · **Branch:** `test`
**Builds on:** the shipped de-identify pathway + roles (commits 11fc62e…5903d2a)

**Goal:** Fix the six defects found by running a realistic psych report through the pathway: over-removal that destroys clinical meaning, the Who's-who screen not applying what it displays, no in-app text preview/copy, no safety net for names detection missed, raw-extraction output formatting, and useless fallback filenames.

**Evidence (the probe that motivated this):** a WISC-style report produced
`"his [organisation] and [organisation] fall below the average range"` — spaCy tagged "Working Memory"/"Processing Speed" as ORGANIZATION, defaults selected them, and the output became clinically meaningless while verification passed. The same run showed suggestions displayed-but-not-applied (`[Other person 1]` where the dropdown said Teacher), a table exploded to one word per line, and `Billy Bob.pdf` → `document_deidentified.txt`.

---

### Task 1: Mode-aware default selections + human category names

**Problem:** "select everything" is right for redaction (over-removal = a black box) and wrong for de-identification (over-removal silently destroys the content the AI needs, for zero privacy gain).

**Files:** `desktop/src/store.ts`, `desktop/src/lib/categories.ts` (new), `desktop/src/pages/DocumentReview.tsx`, `desktop/src/pages/FinalConfirmation.tsx`, `desktop/tests/workflowMode.test.ts`

- New `lib/categories.ts`: `isPreselected(category, mode)` and `friendlyCategory(category)`.
  - In **redact** mode everything stays pre-selected (shipped behaviour, unchanged).
  - In **de-identify** mode, pre-UNselected: `ORGANIZATION (NER)`, `NRP (NER)`, `Date/Time (NER)`, and any unknown `* (NER)` fallback category — the auto-discovered, low-precision classes. Everything person-related, everything user-entered, all structured PII, `Location (NER)`, and `Manual` stay pre-selected. Rule of thumb: **a category is pre-unticked only when a false positive is likelier than a true one AND removal costs meaning.**
  - `friendlyCategory` maps engine jargon for display: `ORGANIZATION (NER)` → "Possible organisation (auto-detected)", `NRP (NER)` → "Possible group or profession (auto-detected)", `Date/Time (NER)` → "Date or time (auto-detected)". Fallback: the raw string.
- `setDetectionResults` becomes mode-aware via `state.workflowMode` (Zustand `set((state) => …)` already has access).
- `DocumentReview`: display `friendlyCategory`; in de-identify mode show pre-unticked items under a light visual cue ("left out by default — tick to remove") so the choice is visible, not buried.
- `FinalConfirmation` category breakdown uses `friendlyCategory` too.

**Tests:** defaults per mode per category; unknown `* (NER)` category unticked in deidentify, ticked in redact; friendly names.

**Verify:** `cd desktop && npm test && npm run build && npm run lint` (baseline 7+1).

---

### Task 2: Who's who commits what it displays

**Problem (bug):** the dropdown renders `personRoles[name] || suggested_role`, but Continue sends only `personRoles`. A user who reads sensible dropdowns and clicks Continue gets `[Other person N]`.

**Files:** `desktop/src/pages/PeopleReview.tsx`, `desktop/tests/workflowMode.test.ts`

- **Continue commits the displayed value** for every person without an explicit answer (skipping ignored people): build the effective map and store it before navigating. "Accept all suggestions" button becomes redundant → remove it (fewer controls, same outcome; the screen's default IS accept-all now).
- **The live label preview must reflect displayed values**: the `/api/deidentify/labels` request sends the effective map (explicit answers merged over displayed suggestions), so the preview chip never disagrees with the dropdown.
- Empty state: when there are no people and the auto-skip guard has already fired (user pressed Back), render a friendly "No people to classify in these documents" message instead of a blank list.

**Tests:** effective-map builder (extract as a pure helper so it's vitest-testable): suggestion committed on continue; explicit answer wins over suggestion; ignored person excluded.

---

### Task 3: Layout-aware output formatting

**Problem:** output is raw extraction — mid-sentence line breaks, tables exploded one word per line, and the file header still says "[Parent 1]" (stale since roles).

**Files:** `src/services/deidentification_service.py`, `tests/test_deidentification_service.py`

- New `_format_page_text(page, drop_header_footer)` for **native pages** (OCR pages keep raw OCR text + existing warning):
  1. `page.get_text("blocks")`, text blocks only.
  2. If `drop_header_footer`: drop blocks whose bbox sits in the header/footer zones **by geometry** — replaces the string-matching `_zone_lines`/`_page_text` dance for native pages entirely (simpler and strictly more precise than rule #49's counted matching; that rule gets rewritten).
  3. Group blocks into rows by y-midpoint tolerance (~4pt). A row with 2+ blocks is a table row → cells sorted by x0, joined `" | "`. A single-block row → join its internal lines with a space (undoes hard wrapping).
  4. Vertical gap between rows > ~1.4× median line height → blank line (paragraph break).
- Replacement and verification run on the FORMATTED text. Safe because replacement is string-based document-wide and `_pattern_for` treats any whitespace run as a separator — reflow can only make split-across-lines matches MORE likely to hit, never less.
- Fallback: if reopening/formatting a page fails for any reason, use the cached raw text for that page (never fail the run over formatting).
- Fix the output header copy: "labels such as [Student] and [Teacher 1]".
- Known limitation to document: genuinely multi-column layouts will join columns with `|` on shared rows — rare in this domain, and still better than interleaving.

**Tests:** wrapped paragraph reflows to one line; a 4-column table reconstructs as `A | B | C | D` rows; paragraph gap produces a blank line; header/footer blocks dropped by geometry (body line with identical text survives — preserves the rule #49 regression guarantee); OCR page text untouched; formatting failure falls back to cached text; header copy updated.

**Verify:** `venv/bin/python3.13 -m pytest tests/ -q`

---

### Task 4: NER sweep of the finished output

**Problem:** verification re-checks only detected-and-selected strings. A name detection never found ships to the AI with no net underneath.

**Files:** `src/core/pii_orchestrator.py` (small public helper), `src/services/deidentification_service.py`, `backend/schemas.py`, `backend/main.py`, `desktop/src/types.ts`, `desktop/src/pages/DeidentifyCompletion.tsx`, `tests/`

- `pii_orchestrator.find_person_entities(text) -> List[str]`: PERSON entities via the shared NLP engine (`_get_shared_nlp_engine`, already cached per process). Returns `[]` when Presidio is unavailable (Streamlit degraded mode) — the sweep is a net, not a dependency.
- Service, per successful document: sweep `strip_labels(output_text)`; drop hits that are (a) a known label, (b) a string the user **deliberately deselected** (their choice stands), (c) < 3 chars. Result → `leftover_name_warnings: List[str]` on the document result, shown as a strong amber warning: *"This still contains what looks like a name: 'J. Nguyen' — check before sharing."*
- **Warning, not quarantine** — NER false positives are common enough that quarantining correct output would erode trust; the deliberate-deselection carve-out keeps it from nagging about choices the user made. The plan reviewer should challenge this call.
- Completion banner honesty (part of fix 6, lands here): "ready to paste into an AI tool" only when there are **no** failures and **no** leftover warnings; otherwise "check the warnings below before sharing".
- Response schema: `leftover_name_warnings` on `DeidentifyDocumentResultResponse`.
- The warnings contain REAL NAMES by construction → they go to the UI response and **never** into the audit log or any file in the output folder.

**Tests:** an undetected name in output is flagged; a deselected name is not; labels are not; Presidio-absent → empty; warnings absent from log_content; banner logic (frontend).

---

### Task 5: In-app text preview + Copy button

**Problem:** the product moment is pasting into an AI, and the app ends at a folder path.

**Files:** `backend/main.py`, `backend/schemas.py`, `desktop/src/api.ts`, `desktop/src/pages/DeidentifyCompletion.tsx`, `tests/test_cleanup_api.py`-style guard tests in a new `tests/test_output_read_api.py`

- `POST /api/output/read {output_folder, file_path}` → `{content}`. Guards mirror `/api/cleanup`'s: resolved path must be inside the resolved folder, filename must end `_deidentified.txt` (NOT `.UNVERIFIED.txt` — quarantined text may contain PII and must be opened in an editor deliberately, not surfaced casually; and never the key file, which matches neither pattern). Size-capped read (2 MB) with a clear error beyond it.
- Completion screen, per successful document: **Copy text** button (fetch → `navigator.clipboard.writeText` → "Copied ✓" flash) and an expandable preview. Content lives in **component state only** — same principle as rule #24; it's de-identified, but the store shouldn't accumulate document bodies.
- Quarantined files get no copy/preview affordance — the existing red card already directs the user to review them manually.

**Tests:** read guards (traversal, wrong suffix, key file, UNVERIFIED refused); happy path; auth middleware covers the route.

---

### Task 6: Filename fallback + flow papercuts

**Files:** `src/services/deidentification_service.py`, `desktop/src/pages/FinalConfirmation.tsx`, `desktop/src/store.ts`, docs

- **Filename:** when `strip_pii_from_filename` leaves only its generic fallback (confirm the exact token in `redactor.py` first), de-identify mode uses `Student document` → `Student document_deidentified.txt`, `Student document_2_…`. Document-type words that survive stripping ("Support Plan") keep winning as today. Redact mode untouched.
- **Back target:** `FinalConfirmation`'s three-way back plus: if the people screen auto-skipped (no people), Back goes to `document_review` — reuse the `autoAdvancedKey` value PeopleReview stamps.
- **Remove `peopleReviewed`** from the store: written, never read — dead state invites false confidence. (Continue-commits from Task 2 makes it meaningless anyway.) Update its tests.
- **Docs:** CLAUDE.md — rewrite rule #49 (geometry-based zones), amend #51 (Continue commits displayed suggestions), new rules for mode-aware defaults ("pre-unticked only when FP-likelier AND removal costs meaning") and the NER sweep (warnings carry real names → response-only); README — brief additions on the sweep and copy button; test-count refresh.
- Final: re-run all four e2e scratchpad scripts (`e2e_realistic.py` must now show the Working Memory sentence intact by default, roles applied via displayed suggestions, a pipe-formatted table, and a sensible filename) + the redact regression script.

---

## Task order

3 → 4 → 5(backend) → 1 → 2 → 5(frontend) → 6. Backend first (pure Python, independently testable), then frontend.

## Out of scope

- `.md` output (pipe rows read fine in .txt; extension change ripples through Save As, cleanup patterns, filenames — revisit if users ask).
- Changing DETECTION (the NRP/ORG false positives at the source) — shared with the shipped redact pathway; handled here by selection defaults instead.
- Reordering/merging multi-column layouts.
