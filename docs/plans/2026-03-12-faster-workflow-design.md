# Design: Faster Workflow — Reduced Intervention

**Date:** 2026-03-12
**Status:** Approved

## Problem

The current 5-screen workflow requires multiple unnecessary clicks and waits. Users running
the app repeatedly (e.g. multiple students per session) find the per-document review loop
and mid-processing button click especially onerous.

## Approved Changes (Approach B)

### 1. Combined processing — remove the "Continue" click on Step 2

**Current:** Conversion runs → results shown → user clicks Continue → detection runs → navigate to review.

**New:** After conversion runs and results are displayed, detection starts automatically with a
"Scanning for PII…" spinner. No Continue button. Once detection finishes, the app navigates to
document review automatically.

- If zero processable files: show error + Back button, stop before detection runs.
- If conversion has warnings/failures/password-protected files: still shown as now; detection
  still auto-starts for the processable files.
- Removes one required button click and one perception of "waiting twice".

**Files affected:** `src/ui/screens.py` — `conversion_status_screen()`

---

### 2. "Accept All" button on document review

**Current:** User clicks through each document individually, approving/rejecting PII items.

**New:** A full-width primary button at the top of Step 3:
> **Accept All & Continue to Summary**
> *All detected PII will be marked for redaction.*

Clicking it:
1. Sets `user_selections[f"{doc}_{i}"] = True` for every doc and every match index.
2. Navigates to `final_confirmation`.

The existing per-document review flow below the button is completely unchanged.

**Files affected:** `src/ui/screens.py` — `document_review_screen()`

---

### 3. Auto-skip zero-PII documents during manual review

**Current:** Documents with no matches still require a Next Document click.

**New:** When advancing to a document (via Next or on initial load), if that document has zero
PII matches, automatically advance to the next document. If all remaining documents have no PII,
navigate directly to `final_confirmation`.

A banner is shown listing skipped documents so nothing is hidden from the user:
> *Skipped 2 documents with no PII detected: report.pdf, notes.pdf*

**Files affected:** `src/ui/screens.py` — `document_review_screen()`

---

### 4. Simplify folder conflict choice on final confirmation

**Current:** When `redacted/` folder already exists, a 3-option radio (Overwrite / New folder /
Cancel) blocks proceeding.

**New:** Replace the radio with a single checkbox:
> ☐ Create a new folder instead of overwriting

Unchecked by default (Overwrite is the default action). Cancel is removed — the existing Cancel
button in the button row already covers this. The disabled state on "Create Redacted Documents"
only triggers if the checkbox's underlying action would be problematic (not applicable with this
change).

**Files affected:** `src/ui/screens.py` — `final_confirmation_screen()`

---

## What Is NOT Changing

- The final confirmation screen itself remains as a safety gate before redaction runs.
- The per-document review flow (checkboxes, Select All / Deselect All per doc, Previous/Next)
  is fully preserved.
- No changes to detection engines, redactor, services, or session state keys.
- No new session state keys required.

## Fast Path After Changes

1. Fill in folder + student name → **Start Processing** (1 click)
2. Conversion + detection run automatically → auto-navigates to review
3. **Accept All & Continue to Summary** (1 click)
4. **Create Redacted Documents** (1 click)

**3 clicks total** from folder entry to redaction start, down from 5+ with per-doc review.

## Testing Notes

- No new services or core logic — all changes are in `screens.py`.
- No new unit tests required (UI layer only).
- Manual smoke test: verify fast path (3 clicks), verify manual review path still works,
  verify auto-skip banners show correctly, verify folder conflict checkbox defaults correctly.
