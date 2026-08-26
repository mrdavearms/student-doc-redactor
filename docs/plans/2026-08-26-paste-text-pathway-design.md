# Paste Text — Third Input Pathway Design

**Date:** 2026-08-26
**Branch:** test
**Status:** Design agreed, not yet planned or implemented.

**Goal:** Let a user paste a slab of text straight into the app, review what was
detected, and get it back either blacked out or de-identified — copied to the
clipboard, or saved as a file. No document, no folder, nothing written to disk
unless the user asks for it.

**Tech stack:** Python 3.13, FastAPI, React + Zustand + TypeScript. **No new
dependencies** — PyMuPDF already lays out text, and the replacement engine is
already written.

---

## 1. The core decision: paste is a third INPUT, not a third PATHWAY

`inputMode` gains `'paste'` alongside `'file'` and `'folder'`. `workflowMode`
(`'redact'` / `'deidentify'`) is untouched.

This falls out of what the feature is for. Both outputs are wanted — blacked-out
text, and text reframed by role — and those are precisely the two pathways the
app already has. Modelling paste as a third *pathway* would mean reimplementing
the redact/de-identify branch inside it. Modelling it as a third *input* means
both outputs arrive for free and the review screen, the Who's Who screen and the
confirm screen are reused with no changes at all.

### Screen ladder

`screensFor(mode)` becomes `screensFor(mode, inputMode)`:

| Step | Redact (paste) | De-identify (paste) |
|------|----------------|---------------------|
| 1 | Enter Text | Enter Text |
| 2 | Scan Text | Scan Text |
| 3 | Review PII | Review PII |
| 4 | — | Who's Who |
| 5 | Confirm | Confirm |
| 6 | Result | Result |

Step 2 is **replaced, not skipped**. An earlier draft of this design removed it,
on the grounds that pasted text needs no Word-to-PDF conversion. That was wrong
for a reason worth recording: the detection fingerprint (rule #41) is computed
inside `ConversionStatus.tsx`, so removing the step removes the thing that
decides whether to re-detect.

Replacing it also avoids adding a **third** auto-skip key. The app already
carries `autoAdvancedKey` (rule #38) and `peopleAutoSkippedKey` (rule #54b), and
those had to be kept as separate fields because sharing one re-armed a
forward-bounce trap. A third skip would be a third chance to re-arm it. Nothing
is skipped here, so there is no bounce to trap.

---

## 2. Detection: the seam already exists

`PIIOrchestrator.detect_pii_in_text(text, page_num)` is already pure text-in.
Pasted text goes straight into it with `page_num=1`. No `TextExtractor`, no PDF,
no OCR.

### The reserved cache key

`_detection_cache` in `backend/main.py` is keyed by path string. Paste caches
under the reserved key `<pasted-text>`, synthesising the usual shape:

```python
{"pages": {1: {"text": pasted}}, "ocr_pages": []}
```

Three things make this key the right choice:

- **Selection keys keep their contract.** They become `<pasted-text>_0`,
  `<pasted-text>_1`, … — the same `f"{doc_path}_{index}"` format `/api/redact`
  and `/api/pii/manual` already derive by iterating `range(len(matches))`. So
  `DocumentReview` and manual PII addition (rule #31, append-only) work
  untouched.
- **It cannot collide with a real document.** `<` and `>` are invalid in Windows
  filenames, and it is not an absolute POSIX path. `/api/pii/detect` must
  nonetheless reject it explicitly rather than relying on that.
- **`fitz.open('<pasted-text>')` raises `FileNotFoundError`**, verified. Any code
  path that tries to open the pseudo-document degrades rather than misbehaving —
  `_formatted_pages` already catches this and falls back to cached text.

### `ocr_pages` stays EMPTY, deliberately

Marking the pasted page as OCR-sourced would be the intuitive move — there is no
page geometry to rebuild, and `_formatted_pages` uses cached text for OCR pages.
It would also be a bug.

Rule #45 adds a **fuzzy** verification pass on OCR-sourced pages, tolerating
single-character misreads. That is right for OCR and wrong for typed text: a
pasted document mentioning a classmate "Smyth" while the student is "Smith" is
edit-distance 1 over 5 letters, which the fuzzy pass would report as a leftover
and quarantine — a false failure on correct output.

Empty `ocr_pages` gets the same cached-text behaviour via the `pdf is None`
branch, with exact verification only. That is the correct semantics for text the
user typed or copied.

### Size cap, measured

Detection is superlinear (roughly O(n^1.9)), measured on this machine with
`require_ner=True`:

| Pasted text | Detection time |
|-------------|----------------|
| 1,725 chars | 0.16s |
| 8,625 chars | 0.31s |
| 20,700 chars | 1.21s |
| 43,125 chars | 4.60s |

- **Soft warning above 20,000 characters** — "this may take a few seconds".
- **Hard block above 50,000 characters** — refused at Step 1 with a redirect:
  that is document-sized, and the app already does documents well.

The first detection in a session additionally pays spaCy's model load (~7s
measured cold). This is existing behaviour — rule #37 caches the engine
module-level for the process — but the paste flow is where a user will most
notice it, so the Scan Text screen's message must own it rather than looking
hung.

---

## 3. Blackout output: fixed-width blocks, and why the PDF is not obvious

### Representation

Removed items become a **fixed-width run of six full-block characters**
(`█` x 6), regardless of the original's length. Fixed rather than
length-matched: a length-matched block leaks the size of what was removed, and
"██" is visibly a short first name. Fixed width leaks nothing.

The cost is accepted knowingly: a name and a full postal address collapse to the
same width, so a reader loses the shape of the original. That is the correct
trade for a privacy tool.

### The replacement engine is already written

`text_deidentifier.deidentify_text(text, selected_matches, pmap)` touches `pmap`
through exactly two methods — `should_replace()` and `label_for()`. So blackout
mode is an adapter, not a second engine:

```python
class BlackoutMap:
    BLOCK = '█' * 6
    def should_replace(self, text, category): return True
    def label_for(self, text, category): return self.BLOCK
```

Longest-first ordering, the single-pass alternation that stops a replacement
being re-matched inside an inserted one, and boundary handling all come along
unchanged, already covered by the 40 tests in `test_text_deidentifier.py`.

**One deliberate divergence:** `should_replace()` returns `True`
unconditionally, bypassing rule #58's form-label guard. That guard exists
because rewriting a `Phone:` row to `[name]: [phone]` is a *meaning* failure in
de-identify mode. In blackout mode a black box over the word "Phone" costs
nothing, and rule #54a already establishes that over-removal is the correct bias
for the redact pathway.

### The PDF cannot simply render the cleaned text

Verified against PyMuPDF 1.27.1: the built-in base-14 fonts are Latin-1 only and
have no glyph for U+2588 (`fitz.Font('helv').has_glyph(0x2588)` returns 0).
Rendering the cleaned text directly produces:

```
Name: ?????? was absent.
```

— silently wrong output, not an error. This is the single most important
finding in this design.

**The fix**, verified working, needs no bundled font and reuses machinery
`redactor.py` already relies on:

1. Lay the text out with `insert_textbox`, substituting a Latin-1 **sentinel**
   for each block run.
2. `page.search_for(sentinel)` to get each rectangle.
3. `page.add_redact_annot(rect, fill=(0, 0, 0))`.
4. `page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)`.

### The sentinel must be chosen per render, not hard-coded

A fixed sentinel is a live bug, verified: laying out
`"Marks: XXXXXXXX out of ten. Name: XXXXXXXX."` makes `search_for('XXXXXXXX')`
return **two** hits, so the user's own text gets blacked out alongside the
redaction.

So the sentinel character is picked at render time: the first character from a
Latin-1 candidate list (`¤ ¦ ¿ ~ ^ ¶ §`) that does **not** occur anywhere in the
cleaned text, repeated a fixed six times. Fixed repetition keeps every box the
same width, which is what makes the fixed-width decision in the text carry
through to the PDF. In the implausible case that every candidate occurs, fall
back to laying out `[REMOVED]` and boxing that instead.

This must have its own test. It is the kind of defect that only shows up on real
documents — a maths report containing `XXXX`, a table of `~~~~` separators — and
that produces a *wrong* PDF rather than an error.

### Pagination

`insert_textbox` returns the leftover vertical space, **negative when the text
does not fit** (measured: `-444.8` for an overlong slab, `+673.6` for a short
one). Paginate by binary-splitting the remaining text on paragraph then word
boundaries until the return value is non-negative, then start a new page with
the remainder. Redaction annotations are applied per page after all text is
laid out.

`apply_redactions` both removes the sentinel text and paints the box, so
extraction of the saved PDF yields the surrounding words and nothing else. Note
this is *true* redaction of a sentinel, not a rectangle drawn over hidden text —
the PII was never placed in the PDF in the first place, so there is nothing
underneath either way. `_strip_metadata()` runs before save, per rule #10.

`images=fitz.PDF_REDACT_IMAGE_NONE` is used per rule #14 even though a generated
text PDF has no images, so the constant never drifts across the codebase.

---

## 4. De-identify output

Reuses `PseudonymMap`, `deidentify_text`, `strip_labels` and
`verify_deidentified` unchanged.

`DeidentificationService.build_map()`, `describe_people()` and
`preview_labels()` are static and **touch no disk** — verified. They are reused
verbatim with a synthetic `DeidentifyRequest` whose `documents` is
`[Path('<pasted-text>')]`.

What is *not* reused is `DeidentificationService.execute()` / `_process_document()`.
Those are fundamentally about writing a file into an output folder: filename
collision counters, `is_same_file()` guards, `strip_pii_from_filename` on the
source name, the audit log. None of that has meaning for a paste, and bending it
would be worse than a thin sibling.

### The key never touches disk, and never shares a text area

Rule #43 says the key file goes with the originals, never in the output folder,
because the output folder must be safe to upload. Paste has **no originals on
disk**, so the rule has no analogue and the key is shown on screen only.

That creates a new hazard the document pathway never had: the safe text and the
re-identifying key are on the same screen. A careless select-all-copy would put
the key on the clipboard alongside the thing the user is about to paste into an
AI chat.

So: **separate boxes, separate Copy buttons, key collapsed behind a click.**
Never one scrollable area containing both.

Rule #42 still binds — labels are role plus sequence number, and
`sanitise_custom_role()` still rejects custom role text containing any owner's
variation.

---

## 5. Backend surface

**New modules**

| Module | Purpose |
|--------|---------|
| `src/services/text_cleanup_service.py` | `blackout()` and `deidentify()` over a string. No disk I/O; returns strings. |
| `src/core/text_pdf.py` | `render(text, path)` — the sentinel + `add_redact_annot` technique above, plus metadata stripping. |

**New endpoints**

| Endpoint | Purpose |
|----------|---------|
| `POST /api/text/detect` | Text + the four name fields in; `DetectionResultsResponse` out; caches under `<pasted-text>`. |
| `POST /api/text/people` | Thin wrapper — builds the synthetic `DeidentifyRequest` server-side and calls `describe_people()`. |
| `POST /api/text/labels` | Same, calling `preview_labels()`. |
| `POST /api/text/clean` | Selections + role answers in; cleaned text, replacement count, leftover warnings out — plus, in de-identify mode, the key entries (name → label, with rule #44's ambiguity notes) for on-screen display. |
| `POST /api/text/save` | The cleaned text **as displayed** + a path the user chose in a native dialog; writes `.pdf` or `.txt`. |
| `POST /api/text/discard` | Clears the cache entry on leaving the flow. |

`/api/text/save` deliberately takes the text back from the client rather than
re-reading the cache: what gets saved is then byte-for-byte what the user was
shown and approved. The text is already safe by that point, so there is no
privacy cost to the round trip.

`/api/text/people` and `/api/text/labels` exist as wrappers rather than reusing
`/api/deidentify/*` directly so the **renderer never fabricates a folder path**.
`DeidentifyRequest.folder_path` is unused by `build_map()`; a test should assert
that stays true.

All new endpoints sit behind the existing token middleware (rule #35) with no
changes — they are simply not `/api/health`.

---

## 6. Frontend surface

**Store**

- `InputMode` gains `'paste'`.
- New field `pastedText: string` + `setPastedText`.
- The detection fingerprint includes `pastedText`, so editing the slab re-runs
  detection instead of reusing a stale cache — the protection rule #41 gives
  folder runs.

`pastedText` is raw PII living in the Zustand store. It has to be, because it
spans four screens. So it is cleared aggressively — on "Clean another", on
leaving the flow, and on switching `inputMode` away from paste — each paired
with `POST /api/text/discard`.

**The de-identify key entries are NOT store state.** They carry real names.
Rule #24 already sets the precedent (preview images stay in React component
state so they die on unmount); the key entries follow it exactly.

**`pastedText` must survive `setBackendReachable(false)`.** That setter clears
`detectionParamsKey` today; it must not clear the slab the user typed. Losing
several hundred words to a momentary backend blip is the worst avoidable
failure in this feature.

**Screens**

| Screen | Change |
|--------|--------|
| `FolderSelection` (Step 1) | Third input choice. Picking "Paste text" swaps the file/folder picker for a textarea with live character count, soft warning at 20,000, block at 50,000. Name fields unchanged; `studentName` stays mandatory. |
| `TextScan` (Step 2, new) | Lean progress screen. Calls a new shared `useDetection()` hook. |
| `ConversionStatus` | Refactored to call the same `useDetection()` hook. Its auto-advance logic (rule #38) stays local to it. |
| `DocumentReview` (Step 3) | **No change.** The paste presents as a document named "Pasted text". |
| `PeopleReview` (Step 4) | **No change.** |
| `FinalConfirmation` (Step 5) | Small branch — no Save As dialog, just a summary and a Clean Text button. |
| `PasteCompletion` (Step 6, new) | Branches internally on `workflowMode`; the two variants share most of their layout, unlike `Completion` / `DeidentifyCompletion`. |

**Why `studentName` stays mandatory.** It is the single biggest lever on
detection quality — user-entered names are confidence 0.95 and seed
`generate_name_variations()`. And `PseudonymMap` is constructed around a
student: with no name nobody is ever labelled `[Student]`, and every person
discovered falls through to `[Other person]`. Three seconds of typing buys a
materially better result.

**Completion screen contents**

- Cleaned text, read-only, with its own **Copy** button.
- **Save as PDF** (blackout) or **Save as .txt** (de-identify), via native dialog.
- De-identify only: the name key, collapsed, in a separate box with a separate
  Copy button.
- Any `leftover_name_warnings` from rule #54c's NER sweep, as warnings.
- **Clean another** — clears `pastedText`, discards the cache, returns to Step 1.

---

## 7. Nothing touches disk until asked

The entire run lives in backend memory and React state. The user gets Copy,
Save as PDF / Save as .txt, and that is all. No audit log, no key file, no temp
file.

A temp-file approach — render the paste to a temp PDF and run the existing
document pipeline over it — was considered and rejected. It would need almost no
new backend code, but it writes unredacted PII to disk, which cuts against the
app's central promise for the sake of implementation convenience.

---

## 8. Error handling

| Case | Behaviour |
|------|-----------|
| Empty or whitespace-only paste | Continue disabled, no error shown |
| Over 50,000 characters | Blocked at Step 1, redirect to the document pathway |
| Zero detections | Existing `no_pii_found` branch, with a Copy button so the trip is not wasted |
| Backend unreachable mid-flow | Existing banner (rule #28); `pastedText` preserved |
| Detection or clean failure | New patterns in `lib/errorMessage.ts` per rule #29, with tests |
| Save dialog cancelled | No-op, stay on the completion screen |
| Verification finds leftovers | Warn prominently, do not block; the saved file is named `.UNVERIFIED.txt`, matching the document pathway |

**No cooperative cancel.** The document pathway needs it because a folder run is
unbounded (rule #36). A paste is a single call of 5s or less, hard-capped.

---

## 9. Testing

| File | Covers |
|------|--------|
| `tests/test_text_pdf.py` | **The load-bearing one.** Render, extract, assert neither the PII nor the sentinel appears and that filled rectangles exist. Direct regression test for the U+2588 finding — without it a font change silently ships `??????`. Also: text containing every sentinel candidate; text containing the default candidate (asserting the user's own `XXXXXXXX` is *not* boxed); and a slab long enough to paginate. |
| `tests/test_text_cleanup_service.py` | Fixed-width invariant, longest-first via the reused engine, replacement counts, `should_replace` divergence |
| `tests/test_backend_paste.py` | Reserved-key contract, selection-key format, `/api/pii/detect` rejects the reserved key, size cap returns 400, cache discard, **`ocr_pages` is empty** |
| `tests/test_text_privacy_invariants.py` | No character of any removed PII survives in blackout output; every block run is the same length |

Desktop: vitest for the fingerprint and store-clearing rules. Components go via
`npm run build` (tsc) + `npm run lint` — there is no React harness, and the lint
baseline of 7 errors + 1 warning must not increase.

---

## 10. Out of scope

Inline-highlight review UI; cooperative cancel; audit logging for paste runs;
rich-text or formatting preservation (paste is flattened to plain text);
Streamlit parity (desktop-only, as de-identify mode already is); multiple slabs
in one run.

---

## 11. New CLAUDE.md rules this will need

Drafted here so they are not lost between design and implementation:

- **`<pasted-text>` is a reserved detection-cache key.** `/api/pii/detect` must
  reject it. It is chosen because `<` and `>` are invalid in Windows filenames
  and it is not an absolute POSIX path, so it can never collide with a real
  document — and because `fitz.open()` on it raises, so any code that tries to
  treat it as a document degrades safely.
- **A pasted page's `ocr_pages` must stay EMPTY.** Marking it OCR-sourced looks
  right (no geometry to rebuild) but triggers rule #45's fuzzy verification,
  which false-quarantines near-miss names in typed text.
- **The blackout PDF must never rely on the U+2588 glyph.** Base-14 PDF fonts
  are Latin-1 only; U+2588 renders as `?`. Lay out a Latin-1 sentinel and remove
  it with `add_redact_annot` + `apply_redactions`.
- **That sentinel must be chosen per render, never hard-coded.** `search_for`
  cannot tell our sentinel from the same characters occurring in the user's own
  text, so a fixed sentinel blacks out real content. Pick the first candidate
  absent from the cleaned text.
- **The de-identify key and the safe output must never share a text area.**
  Separate boxes, separate Copy buttons, key collapsed. Rule #43 has no analogue
  for paste because there are no originals on disk, so this is what replaces it.
- **`pastedText` must survive `setBackendReachable(false)`.** That setter clears
  `detectionParamsKey`; it must not clear the user's typed text.
