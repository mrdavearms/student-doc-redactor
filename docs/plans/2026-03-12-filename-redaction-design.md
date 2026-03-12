# Filename PII Redaction — Design Doc

**Date:** 2026-03-12
**Status:** Approved

---

## Problem

The current redaction pipeline strips PII from document *content* but leaves the student's name intact in the *output filename*. For example:

- Input: `Joe Bloggs DIP Vineland Report 2025.pdf`
- Output: `Joe Bloggs DIP Vineland Report 2025_redacted.pdf`

The filename itself is a PII leak.

## Use Case

**Recipient type B** — the recipient knows which student the folder belongs to, but the student's name should not be embedded in the filenames themselves. The document *type* must remain readable (e.g. "Vineland Report", "IEP", "Behavior Management Plan") so the recipient can identify documents without a manifest.

---

## Approach: Token-Strip

Reuse the same name variation list that `PIIDetector` already computes for the student, parents, and family members. Apply those variations as word-boundary regex replacements against the filename stem. Clean up leftover punctuation. Append `_redacted` as usual.

---

## Algorithm — `strip_pii_from_filename(stem, name_variations)`

A pure function. Steps in order:

1. **Sort variations longest-first** — prevents partial-match fragments (e.g. replace `"Joe Bloggs"` before `"Joe"`)
2. **Word-boundary regex replace** — case-insensitive, replaces each variation with `""`
3. **Possessive cleanup** — remove orphaned `'s` left after name removal (`"Joe's"` → `"'s"` → `""`)
4. **Separator cleanup** (in order):
   - Collapse multiple spaces → single space
   - Remove empty brackets: `( )`, `[ ]`, `(  )` etc.
   - Remove orphaned separators at start/end: leading/trailing `-`, `_`, `,`
   - Collapse double mid-string separators: `"Plan - - Report"` → `"Plan - Report"`
   - Strip surrounding whitespace
5. **Fallback** — if result is empty or fewer than 3 chars, return `"document"`

### Worked Examples

| Input stem | Name variations used | Output stem |
|---|---|---|
| `Joe Bloggs DIP Vineland Report 2025` | `["Joe Bloggs", "Joe", "Bloggs", "J. Bloggs"]` | `DIP Vineland Report 2025` |
| `Bloggs_Joe_Adaptive_Behaviour_Assessment_Summary` | same | `Adaptive_Behaviour_Assessment_Summary` |
| `Behavior Management Plan - Joe Bloggs (T1 2024)` | same | `Behavior Management Plan (T1 2024)` |
| `Overview of Joe's behaviours - Mary Bloggs` | + `["Mary Bloggs"]` (parent) | `Overview of behaviours` |
| `AA report` | same | `AA report` (unchanged) |
| `Joe` | same | `document` (fallback) |

### Variation Filter

Variations under 3 chars are excluded from filename stripping — consistent with the existing rule in `PIIDetector._generate_name_variations()`. Exception: `student_name` itself is always included regardless of length.

---

## Integration Points

### 1. `src/core/redactor.py`

`create_redacted_copy()` gets a new optional parameter:

```python
def create_redacted_copy(
    self,
    input_pdf: Path,
    output_folder: Path,
    redactions: List[RedactionItem],
    name_variations: List[str] = None,   # NEW
) -> Tuple[bool, str, Path]:
```

Filename construction changes:

```python
# Before
output_filename = f"{input_pdf.stem}_redacted.pdf"

# After
safe_stem = strip_pii_from_filename(input_pdf.stem, name_variations) if name_variations else input_pdf.stem
output_filename = f"{safe_stem}_redacted.pdf"
```

**Collision handling** — if `output_filename` already exists in `output_folder`, append `_2`, `_3`, etc. before the `.pdf` extension.

`strip_pii_from_filename` lives in this file (or a small `filename_utils.py` alongside it — decision for implementation).

### 2. `src/services/redaction_service.py`

The service already holds `student_name`, `parent_names`, `family_names`. It constructs a `PIIDetector` for detection — extract the variations list from the detector and pass it to `create_redacted_copy()`.

No new public API on `PIIDetector` is needed if we call `detector._generate_name_variations()` internally, but a public `detector.name_variations` property is cleaner and testable.

### 3. `src/ui/screens.py` — completion screen

Add a two-column mapping table: **Original filename → Redacted filename**. This gives the teacher an at-a-glance record and serves as a lightweight audit trail. No new session state key needed — derive the mapping from `user_selections` / output paths at render time.

---

## Edge Cases

| Case | Handling |
|---|---|
| Possessives (`Joe's`) | Strip orphaned `'s` after name removal |
| No PII in filename (`AA report.pdf`) | No variation matches → passthrough unchanged |
| Entire stem is the name (`Joe.pdf`) | Fallback → `document_redacted.pdf` |
| Two files produce same stripped name | Auto-number: `Vineland Report_redacted.pdf`, `Vineland Report_2_redacted.pdf` |
| Short name parts (<3 chars) | Excluded from variations (existing PIIDetector rule) |
| Parent names in filename | Stripped if entered by user in parent/family fields |

---

## Out of Scope

- Renaming the output *folder* (`redacted_2/`) — not a PII risk
- Modifying *source* files in the input folder — never touched
- Fuzzy/partial name matching in filenames — not needed for recipient type B
- Manual rename UI step — Approach C, rejected

---

## Tests — `tests/test_filename_redaction.py`

~12 tests covering:

1. Name in filename prefix
2. Name in filename suffix
3. Name embedded mid-filename with brackets
4. Underscore-separated format (`Bloggs_Joe_...`)
5. Parent/family name stripped
6. Possessive (`Joe's`) stripped cleanly
7. No-PII filename passes through unchanged
8. Short name parts not incorrectly stripped
9. Empty result → fallback to `"document"`
10. Result < 3 chars → fallback to `"document"`
11. Collision numbering (`_2`, `_3`)
12. Backward-compatible: `name_variations=None` → original behaviour

---

## Files Changed

| File | Change |
|---|---|
| `src/core/redactor.py` | Add `strip_pii_from_filename()`, update `create_redacted_copy()` |
| `src/services/redaction_service.py` | Pass name variations to `create_redacted_copy()` |
| `src/ui/screens.py` | Add original→redacted filename mapping table on completion screen |
| `tests/test_filename_redaction.py` | New test file (~12 tests) |
