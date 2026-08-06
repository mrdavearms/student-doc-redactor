# De-identify for AI — Second Pathway Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-08-06
**Branch:** test
**Goal:** Add a second workflow pathway, chosen at app commencement: instead of blacking out PII in PDFs, replace every detected PII item in the document *text* with a non-identifying label (`[Student]`, `[Parent 1]`, `[phone]`…) and output a plain-text file per document that is safe to paste into an AI chatbot. The existing redaction pathway is untouched.

**Architecture:** Detection, conversion, and review are 100% reused — the new mode differs only in the *output* step. A new `PseudonymMap` (core) builds a privacy-safe label map, a new `text_deidentifier` (core) performs longest-first replacement over extracted text, and a new `DeidentificationService` (service layer) mirrors `RedactionService.execute()` but writes `.txt` files plus a local key file. The frontend gains a mode-selection screen before folder selection and branches on `workflowMode` at the final-confirmation and completion steps only.

**Tech Stack:** Python 3.13 (no new dependencies), FastAPI, React + Zustand + TypeScript.

---

## Critical design decision: labels must carry ZERO information from the real name

**Initials are not pseudonyms.** `Student(BB)` for "Billy Bob" is identifiable in a small school community. The rules:

1. **No letters, initials, or fragments of any real name appear in any label.** Labels are role + sequence number only.
2. **Numbering is by order of entry / first discovery**, which leaks nothing.
3. **Re-identification lives only in a local key file** whose filename itself screams not to share it (see Task 3).

### Label scheme

| Who / what | Label | Notes |
|---|---|---|
| Student (name + all variations + nicknames) | `[Student]` | App is single-student per run — no number needed |
| Each user-entered parent/guardian | `[Parent 1]`, `[Parent 2]`… | Order = order entered |
| Each user-entered family member | `[Family member 1]`… | Order = order entered |
| Each user-entered organisation | `[Organisation 1]`… | Order = order entered |
| Each NER-discovered person not already covered | `[Person 1]`, `[Person 2]`… | Order = first appearance across the run; identity rules below |
| A *surname* token shared by ≥2 people (e.g. "Bob" shared by student "Billy Bob" and parent "Mrs Bob") | `[Family name]` | A bare shared surname is genuinely ambiguous — a neutral label is both safer and clearer for the AI reading it |
| A *given-name* token shared by ≥2 people (e.g. "Billy" shared by student "Billy Bob" and classmate "Billy Chen") | Highest-priority claimant's label | Priority: Student > Parent > Family member > Person. Bare first-name mentions in a report overwhelmingly mean the subject student; the key file records the ambiguity. Privacy is preserved either way — the tradeoff is only semantic accuracy |
| Phone number | `[phone]` | |
| Email address | `[email]` | |
| Address (both confidence tiers) | `[address]` | |
| Date of birth | `[date of birth]` | |
| Medicare number | `[Medicare number]` | |
| Student ID | `[student ID]` | |
| Centrelink CRN | `[Centrelink CRN]` | |
| NDIS number | `[NDIS number]` | |
| ABN | `[ABN]` | |
| Passport number | `[passport number]` | |
| Contextual/cross-line family names (`Parent/family (contextual)`) | `[Person N]` | Grouped by variation like NER persons |
| Manual items and anything unmapped | fallback: `[name]` for name-like categories, `[redacted]` otherwise | Safety net — replacement must never silently skip a selected item |

**Consistency guarantee:** one label map is built per run and applied to *every* document, so the same person gets the same label in every output file. This is what makes the output usable for AI analysis across a document set.

### Identity rules — multiple people, multiple students in one file

Reports routinely name other children (classmates, siblings) alongside the subject student. NER discovers them, and they must become distinct `[Person N]` labels — merging two different children under one label would attribute one child's behaviour to another in the AI's output. The naive rule "merge if any variation is already mapped" is WRONG: classmate "Billy Chen" shares the variation "Billy" with student "Billy Bob" and would be swallowed into `[Student]`.

**Merge rule (two names are the same person only if):**
- their normalised full names are equal, **or**
- one full name appears in the other's `generate_name_variations()` output (so "S. Williams" merges with "Sarah Williams", and a bare NER hit "Billy" resolves to an existing owner rather than minting a new person).

Sharing a *single token* ("Billy" in "Billy Bob" vs "Billy Chen") is **not** identity — it creates a new person, and the shared token itself falls under the shared-token rules in the label table (surname position → `[Family name]`; given-name position → highest-priority claimant). Token position (given vs surname) is known from where it sits in each owner's full name. A single-token NER candidate that matches multiple owners resolves to the highest-priority owner (Student > Parent > Family member > Person). Full multi-token names always win over token collisions because replacement is longest-first — "Billy Chen" in the text becomes `[Person 1]` before any bare-"Billy" pass runs.

Siblings work out naturally: "Sally Bob" → `[Person 1]` (full name, longest-first), bare "Sally" → `[Person 1]`, shared surname "Bob" → `[Family name]`.

**Key file transparency:** every shared token and its resolution is listed in the key file (e.g. `"Billy" appears alone in the text and was labelled [Student]; note another person "Billy Chen" [Person 1] shares this first name`), so the teacher can sanity-check the AI's reading.

**Future batch mode:** the app is single-student per run today, so `[Student]` is singular. If multi-student batch processing ever lands, the scheme extends to `[Student 1]`/`[Student 2]` without redesign.

### Why plain-text output (not a rebuilt PDF)

The user's goal is pasting into an AI. Text sidesteps every hard problem: no font/width/reflow issues, and scanned pages work automatically because `TextExtractor.extract_text_from_pdf()` already OCRs image-only pages. A labelled-PDF variant (PyMuPDF `add_redact_annot(text=...)` overlay text) is explicitly **out of scope** for v1.

### What the mode reuses unchanged

- Word → PDF conversion (`ConversionService`) — de-identification reads text from the converted PDF.
- The whole detection pipeline and review screen — including selections, manual PII additions, and the server-side `_detection_cache`.
- `detectionParamsKey` — the mode is deliberately **not** part of the detection fingerprint. Detection inputs are identical in both modes, so a user who switches mode after reviewing does not re-run detection.
- Cooperative cancel (`_redaction_control`), audit logging (`logger.py`), filename PII stripping (`strip_pii_from_filename`).

### Out of scope

- Streamlit app (`app.py`) — legacy, desktop-only feature.
- Labelled-PDF output.

(`redact_header_footer` is **in** scope — reinterpreted as dropping header/footer-zone text from the output; see Task 3.)

---

## Selection semantics

Replacement honours the review screen the same way redaction does: the service receives the user-selected matches per document. For each document, collect the **unique selected match texts**, then replace each of those strings document-wide (longest first). Deselecting a false positive (e.g. "Ann" flagged inside a heading) leaves that string untouched everywhere, exactly matching how users understand the redact path.

---

### Task 1: `PseudonymMap` — build the label map

**Files:**
- Create: `src/core/pseudonym_map.py`
- Create: `tests/test_pseudonym_map.py`

**Spec:**

```python
CATEGORY_LABELS = {
    'Phone number': '[phone]', 'Email address': '[email]', 'Address': '[address]',
    'Date of birth': '[date of birth]', 'Medicare number': '[Medicare number]',
    'Student ID': '[student ID]', 'Centrelink CRN': '[Centrelink CRN]',
    'NDIS number': '[NDIS number]', 'ABN': '[ABN]', 'Passport number': '[passport number]',
}

class PseudonymMap:
    def __init__(self, student_name, parent_names, family_names, organisation_names):
        # Build {variation_lower: label} for every known person/org using the SAME
        # variation generators the detector uses:
        #   - student: generate_name_variations(include_nicknames=True) → '[Student]'
        #   - each parent/family/org (comma-split, in order) → '[Parent N]' etc.
        #     Orgs use the detector's word-level split minus GENERIC_ORG_WORDS.
        # Shared-variation rule: if a variation is claimed by ≥2 owners → '[Family name]'.

    def register_person(self, full_name: str) -> str:
        # Called for NER-discovered persons. Apply the MERGE RULE (see design section):
        #   - same person only if normalised full names are equal, or one full name
        #     is in the other's generate_name_variations() output → return that
        #     owner's label, additionally mapping any new variations.
        #   - a single-token candidate matching an existing owner's variation
        #     resolves to the highest-priority such owner (Student > Parent >
        #     Family member > Person) — no new person minted.
        #   - otherwise assign '[Person N]' (N increments across the run) and map
        #     full_name plus its generate_name_variations(include_nicknames=False)
        #     variations. Token collisions with existing owners go to the
        #     shared-token rules (surname → '[Family name]', given name →
        #     highest-priority claimant) — they never merge identities.

    def label_for(self, match_text: str, category: str) -> str:
        # 1. name-like category → look up match_text.lower() in the variation map
        # 2. category in CATEGORY_LABELS → that token
        # 3. fallback: '[name]' if 'name' in category.lower() else '[redacted]'

    def key_entries(self) -> list[tuple[str, str]]:
        # [('[Student]', 'Billy Bob'), ('[Parent 1]', 'Mrs Smith'), ...] for the key file.
        # Uses the ORIGINAL entered/discovered full names, not variations.
```

Do **not** filter variations through `_CONTEXTUAL_NAME_EXCLUDE` (CLAUDE.md rule #34). Respect the short-name guard (rule #7): the student's exact entered name always maps even if < 3 chars.

**Tests must cover:** no label ever contains a character of the real name (assert programmatically: for every key entry, no word ≥ 2 chars from the real name — and no initials pattern — appears in the label); shared-surname → `[Family name]`; shared given name resolves to `[Student]` while the full names stay distinct (**the Billy Bob / Billy Chen case**: "Billy Chen" → its own `[Person N]`, "Chen" → that person, bare "Billy" → `[Student]`); sibling case ("Sally Bob" → `[Person N]`, "Bob" → `[Family name]`); initialised-form merge ("S. Williams" and "Sarah Williams" → one person, either discovery order); `register_person` dedup against user-entered people ("Mrs Bob" NER hit when family name "Bob" was entered → existing owner, no new `[Person N]`); nickname variations map to `[Student]`; ordering stability; fallback labels; key file records shared-token ambiguity notes.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_pseudonym_map.py -v`

---

### Task 2: `text_deidentifier` — replacement over extracted text

**Files:**
- Create: `src/core/text_deidentifier.py`
- Create: `tests/test_text_deidentifier.py`

**Spec:**

```python
def deidentify_text(text: str, selected_matches: list[PIIMatch], pmap: PseudonymMap) -> tuple[str, int]:
    # 1. unique (match_text, category) pairs from selected_matches
    # 2. sort by len(match_text) DESC  ← longest-first so 'Billy Bob' is consumed
    #    before a lone 'Billy' pass can split it
    # 3. for each, ONE compiled regex, case-insensitive, using the orchestrator's
    #    lookaround boundaries (?<![A-Za-z0-9]) … (?![A-Za-z0-9]) — \b fails on
    #    variations like 'J. Smith'. Non-alphabetic PII (emails, numbers) uses
    #    re.escape'd literal matching with the same lookarounds.
    # 4. replace with pmap.label_for(...); count replacements
    # Possessives fall out naturally: replacing 'Billy' in "Billy's" yields "[Student]'s".
```

Guard against double-processing: a replacement must never match inside an already-inserted label (labels contain `[`/`]` which the lookarounds treat as boundaries — add an explicit test for a student named e.g. "Person" to prove `[Person 1]` isn't re-mangled; if it is, switch to a single-pass combined-alternation regex).

Verification helper: `verify_deidentified(text, selected_texts) -> list[str]` — reuse `_pii_visible_in_text()` imported from `redactor` (whole-word semantics, CLAUDE.md rule #9) to return any PII string still visible.

**Fuzzy verification pass (OCR-sourced text only):** in redact mode a garbled OCR misread ("Bi11y") just means a black box lands imperfectly; in this mode the OCR text *is the deliverable*, so a misread name ships readable. After the exact check, run a fuzzy scan of the output words against every selected *alphabetic 5+ char* PII string using the exact thresholds of CLAUDE.md rule #32 (Levenshtein 1 for 5–7 letters, 2 for 8+; never fuzz shorter words or non-alphabetic PII) — reuse/extract `_fuzzy_word_match()` from `redactor.py` rather than duplicating it. A fuzzy hit is a verification failure like any other. Apply this pass only to pages the extractor flagged as OCR-sourced; text-layer pages can't misspell.

**Tests must cover:** longest-first ordering; possessive (`Billy's` → `[Student]'s`); case-insensitivity preserving no trace; email/URL exact matching; hyphenated surname; PII at start/end of text; label-collision guard; replacement count; verifier catching a deliberate miss.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_text_deidentifier.py -v`

---

### Task 3: `DeidentificationService`

**Files:**
- Create: `src/services/deidentification_service.py`
- Create: `tests/test_deidentification_service.py`

Mirror `RedactionService.execute()`'s shape (same request fields, results shape analogous to `RedactionResults`, `should_cancel` checked between documents, audit log via `logger.py` with the mode noted).

**Audit log must be label-only in this mode.** `LogEntry.text` currently records the raw matched PII, and the log is saved into the output folder — in this mode that would place a file full of real names next to the "safe to upload" outputs, defeating the whole point. De-identify log entries record the *label* (`[Student]`, `[Parent 1]`…) in the text field, never the raw string; the key file is the **only** re-identifying artifact in the folder. Add a test asserting no user-entered or NER-discovered name appears anywhere in the generated log content.

Per document:

1. `TextExtractor.extract_text_from_pdf()` (OCR pages included; record which docs used OCR as informational warnings, same spirit as rule #11).
2. **Header/footer filtering** when `redact_header_footer=True`: the option keeps working in this mode, reinterpreted as *dropping* extracted text that falls inside the same zones Stage 0 blanks (`HEADER_ZONE_RATIO` 12% top, `FOOTER_ZONE_RATIO` 8% bottom — import the constants from `redactor.py`, don't restate them). Text-layer pages: filter blocks by bbox from `page.get_text('blocks')`; OCR pages: filter words by their `image_to_data` y-coordinates. This is what removes school letterheads the user never typed into the organisation field.
3. **Embedded images on text-layer pages never reach the output** — text extraction reads the text layer only, so a PII-bearing email screenshot simply doesn't appear (in redact mode Stage 2 OCRs those images; here omission *is* the protection). This is a feature, but also silent information loss: count embedded raster images per document and surface "N image(s) were not included in the text output" as an informational note in the results and audit log.
4. `deidentify_text()` with that document's selected matches.
5. Output filename: `strip_pii_from_filename(stem)` + `_deidentified.txt`, into `deidentified/` subfolder (or `custom_output_path`). Include `--- Page N ---` separators between pages. Honour `custom_output_filename` only when exactly one document (rule #39) and force a `.txt` suffix via the same `_sanitise_output_filename` approach. Keep the never-overwrite-source guard (`is_same_file`) even though a `.txt` colliding with a source is unlikely — a source `.txt`-adjacent name costs nothing to check.
6. `verify_deidentified()` including the fuzzy pass on OCR-sourced pages; on failure, write as `<name>.UNVERIFIED.txt` and record in `verification_failures` — same quarantine semantics as redaction.

**The key file:** written once per run into the output folder as
`DO-NOT-UPLOAD-name-key.txt` — the warning is in the *filename* because the likeliest failure mode is a user dragging the whole output folder into an AI chat. Contents: a header block ("This file re-identifies the documents in this folder. Keep it private. Never upload or paste it anywhere.") then `label → real name` lines from `pmap.key_entries()`. The audit log records that a key file was written, but **never** its contents.

**Tests must cover:** end-to-end on a small generated PDF (fitz-created, like existing service tests); consistency of labels across two documents in one run; key file name + header + no key contents in audit log; **audit log contains labels only — no raw names anywhere in the generated log**; header/footer zone text dropped when the flag is on (text-layer bbox path; OCR y-coordinate path via mocked `image_to_data`); embedded-image count surfaced as an informational note; quarantine path (including a fuzzy-hit quarantine on a mocked OCR page); cancel between documents; custom filename single-doc rule; filename PII stripping.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_deidentification_service.py -v` then full suite `venv/bin/python3.13 -m pytest tests/ -v`

---

### Task 4: Backend endpoint

**Files:**
- Modify: `backend/schemas.py` — `DeidentifyRequest` (same fields as `RedactionRequest`, including `redact_header_footer`), `DeidentifyResponse` (typed models — remember rule #40: no `Dict[str, X]` for mixed-type rows; reuse `OcrWarning`).
- Modify: `backend/main.py` — `POST /api/deidentify`.
- Create: `tests/test_backend_deidentify.py`

The endpoint is a sibling of `/api/redact`: same `_detection_cache` read, same selection-key derivation (`range(len(matches))`, rule #31 ordering), same 400 when the cache is missing (must return a `no cached detection data` message so the frontend's `detectionParamsKey` clearing logic — rule #41 — fires on its existing pattern), same cooperative-cancel plumbing, same clean-500 error wrapping. Response includes per-document output paths, replacement counts, OCR warnings, verification failures, `key_file_path`, and `cancelled`.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_backend_deidentify.py tests/test_api_auth.py -v` (auth middleware must cover the new route automatically — add one assertion).

---

### Task 5: Frontend — pathway choice and mode-aware final steps

**Files:**
- Modify: `desktop/src/types.ts` — add `'mode_selection'` to `Screen`; add `export type WorkflowMode = 'redact' | 'deidentify'`; response interfaces for `/api/deidentify`.
- Modify: `desktop/src/store.ts` — `workflowMode: WorkflowMode` (default `'redact'`), `setWorkflowMode` (clears `redactionResults` + de-identify results; must NOT clear `detectionParamsKey` — detection is mode-independent).
- Create: `desktop/src/pages/ModeSelection.tsx`
- Modify: `desktop/src/App.tsx` (route), `desktop/src/components/Sidebar.tsx`, `desktop/src/pages/FolderSelection.tsx` (Back → mode_selection; reword the header/footer checkbox in de-identify mode: "Remove header/footer content (letterheads, school addresses)"), `desktop/src/pages/FinalConfirmation.tsx`, `desktop/src/pages/Completion.tsx`, `desktop/src/api.ts`, `desktop/src/lib/errorMessage.ts`, `desktop/src/lib/filename.ts` (`.txt` suggestion in de-identify file mode).
- Modify: `desktop/tests/` — store, api, errorMessage test additions.

**ModeSelection screen:** first screen after setup (setup's dependency gate is unchanged and runs before it). Two large cards in the app's existing card style:

- **Redact documents** — "Black out personal information. Produces redacted PDFs you can share or file." (current pathway)
- **De-identify for AI** — "Replace names and details with labels like [Student] and [Parent 1]. Produces plain-text files safe to paste into AI tools, plus a private key to re-identify the results."

Selecting a card sets `workflowMode` and navigates to `folder_selection`. The sidebar shows the chosen mode with a small "change" affordance that returns to `mode_selection`. `SCREENS` step numbering is unchanged (mode selection is step 0/pre-step, like setup — not in the `SCREENS` array).

**FinalConfirmation:** branch on `workflowMode` — button label ("Create De-identified Documents"), call `api.deidentify(...)`, Save As accepts/forces `.txt`. Everything else (progress component, cancel button behaviour per rule #36) is shared.

**Completion:** in de-identify mode show the output folder, per-document replacement counts, and a prominent warning card: "A file named `DO-NOT-UPLOAD-name-key.txt` was saved alongside your documents. It re-identifies every label — never upload it or paste it into an AI tool." Reuse `DocumentCard` with mode-appropriate fields; no before/after PDF preview in this mode (output is text — show a text snippet preview from the response instead, held in component state only, per the spirit of rule #24).

**errorMessage.ts:** add patterns for any new backend `HTTPException` strings introduced in Task 4, with test cases (rule #29).

**Verify:** `cd desktop && npm test && npm run build && npm run lint` (lint count must not exceed the documented baseline) and `node --check electron/main.cjs` untouched-check.

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md` — new screen-flow diagram (mode_selection), new store keys, new key files rows, new Critical Rules for: the no-initials label invariant + key-file naming, the person-identity merge rule (full-name identity, never single-token), and the label-only audit log in de-identify mode; test-structure additions.
- Modify: `README.md` — user-facing description of the two pathways and the key-file warning.

**Verify:** re-read both diffs for accuracy against the shipped code.

---

## Task order & dependencies

1 → 2 → 3 → 4 → 5 → 6, strictly sequential (each layer consumes the previous). Tasks 1–3 are pure Python and independently testable before any UI work exists.

## Manual end-to-end check (after Task 5)

`cd desktop && npm run dev:electron` → choose **De-identify for AI** → run the synthetic sample folder → confirm: labels consistent across documents, no initials anywhere, a second person sharing the student's first name gets a distinct `[Person N]` label, key file present with warning name and ambiguity notes, output text pastes cleanly, **audit log contains no real names**, letterhead text absent when the header/footer option is on, Back/mode-switch does not re-run detection.
