# Plan: Replace Real Student Name with Synthetic Name

**Date:** 2026-03-14
**Branch:** test
**Goal:** Remove all references to the real student name "Joe Bloggs" (and associated PII like parent name "Mary Bloggs" and email "fred.bloggs@emaildomain.com") from tracked source code, tests, and documentation. Replace with the synthetic name "Joe Bloggs".

**Out of scope:** The `sample/` folder (real PDFs/DOCs) — handled separately via git history rewrite (Step 2).

---

## Replacement Mapping

| Real value | Replacement | Notes |
|---|---|---|
| `Joe Bloggs` | `Joe Bloggs` | Full name |
| `Joe` | `Joe` | First name |
| `Bloggs` | `Bloggs` | Surname |
| `joe` | `joe` | Lowercase |
| `bloggs` | `bloggs` | Lowercase |
| `JOE` | `JOE` | Uppercase (if found) |
| `BLOGGS` | `BLOGGS` | Uppercase (if found) |
| `Joe's` | `Joe's` | Possessive |
| `Bloggs_Joe` | `Bloggs_Joe` | Reversed underscore form (filenames) |
| `Mary Bloggs` | `Mary Bloggs` | Parent name (appears in tests + docs) |
| `fred.bloggs@emaildomain.com` | `fred.bloggs@emaildomain.com` | Teacher email in docs |

### Variant-Specific Notes

- **`BLOGGS_VARIATIONS`** — Test constant in `test_filename_redaction.py` and `test_ocr_redaction.py`. Contains `["Bloggs", "Joe", "Joe Bloggs"]`. Replace with `["Bloggs", "Joe", "Joe Bloggs"]`. Rename to `BLOGGS_VARIATIONS`.
- **`JOE_VARIATIONS`** — Similar test constant. Rename to `JOE_VARIATIONS`.
- **Possessive forms** — `Joe's` appears in test strings and doc references (e.g., `"Overview of Joe's behaviours"`). Must become `"Overview of Joe's behaviours"`.
- **Sample filenames referenced as strings** — Tests reference filenames like `"Behavior Management Plan - Joe Bloggs (T1 2024).doc"`. These are string literals in test fixtures, not actual file paths in the test. Replace the name portion only.

---

## Files to Modify (17 files, grouped by priority)

### Group 1: Source Code (1 file)

| File | Matches | What's there |
|---|---|---|
| `src/core/redactor.py` | 5 | Code comments only (e.g., `# "Joe's" → possessive handling`) |

**Action:** Replace name references in comments. No logic changes.

### Group 2: Tests (6 files)

| File | Matches | What's there |
|---|---|---|
| `tests/test_ocr_redaction.py` | 46 | Test fixtures, assertions, mock data |
| `tests/test_redactor.py` | 18 | Test fixtures, assertions |
| `tests/test_filename_redaction.py` | 16 | Test fixtures, `BLOGGS_VARIATIONS` constant, "Mary Bloggs" parent name |
| `tests/test_widget_redaction.py` | 13 | Test fixtures, assertions |
| `tests/test_pii_detector_names.py` | 12 | Test fixtures, assertions |
| `tests/test_pii_detector.py` | 9 | Test fixtures, assertions |

**Action:** Find-and-replace all name references. Rename test constants (`BLOGGS_VARIATIONS` → `BLOGGS_VARIATIONS`, etc.). Replace "Mary Bloggs" → "Mary Bloggs" where it appears.

### Group 3: Documentation (2 files)

| File | Matches | What's there |
|---|---|---|
| `README.md` | 12 | Usage examples, screenshots descriptions |
| `CLAUDE.md` | 2 | Technical rule explanations |

**Action:** Replace name references. Update example text.

### Group 4: Legacy Docs (4 files)

| File | Matches | What's there |
|---|---|---|
| `docs/legacy/FINAL_SUMMARY.md` | 4 | Historical references |
| `docs/legacy/PROJECT_SUMMARY.md` | 3 | Historical references |
| `docs/legacy/QUICK_START_CHECKLIST.md` | 2 | Usage example |
| `docs/legacy/LAUNCH_INSTRUCTIONS.md` | 1 | Usage example |

**Action:** Replace all name references.

### Group 5: Plan Docs (4 files)

| File | Matches | What's there |
|---|---|---|
| `docs/plans/2026-03-12-filename-redaction.md` | 22 | Design examples, "Mary Bloggs" |
| `docs/plans/2026-03-13-image-ocr-redaction.md` | 15 | Code examples, "fred.bloggs" email |
| `docs/plans/2026-03-12-filename-redaction-design.md` | 13 | Design tables, "Mary Bloggs" |
| `docs/plans/2026-03-11-fix-over-redaction.md` | 4 | Bug report examples |

**Action:** Replace all name references, "Mary Bloggs" → "Mary Bloggs", email replacement.

---

## Files NOT Modified (safe to ignore)

| Path | Reason |
|---|---|
| `bundled-python/` | Untracked. Third-party libraries. "Bloggs" matches are "Bloggseberg" (SPDX license). |
| `desktop/release/` | Untracked. Built app bundle. Will be rebuilt after changes. |
| `desktop/package-lock.json` | False positive — "bloggs" substring in a base64 integrity hash. |
| `sample/redaction_log.txt` | Untracked (in `.gitignore`). Output file. |
| `sample/*.pdf`, `sample/*.doc` | Step 2 (git history rewrite). Not part of this task. |

---

## Execution Order

### Task 1: Source code comment replacement
- Edit `src/core/redactor.py` — 5 comment-only replacements

### Task 2: Test file replacements (largest batch)
- Edit `tests/test_ocr_redaction.py` — 46 replacements
- Edit `tests/test_redactor.py` — 18 replacements
- Edit `tests/test_filename_redaction.py` — 16 replacements + "Mary Bloggs" → "Mary Bloggs"
- Edit `tests/test_widget_redaction.py` — 13 replacements
- Edit `tests/test_pii_detector_names.py` — 12 replacements
- Edit `tests/test_pii_detector.py` — 9 replacements

### Task 3: Run tests
```bash
source venv/bin/activate && pytest tests/ -v
```
- All 257 tests must pass (or same pre-existing failures as before)
- Any new failures = name replacement broke test logic → fix before continuing

### Task 4: Documentation replacements
- Edit `README.md` — 12 replacements
- Edit `CLAUDE.md` — 2 replacements

### Task 5: Legacy + plan docs replacements
- Edit all 8 files in `docs/legacy/` and `docs/plans/`
- Include "Mary Bloggs" → "Mary Bloggs" and email replacement

### Task 6: TypeScript check
```bash
cd desktop && npx tsc --noEmit
```
- Should pass (no TS files contain PII, but confirms nothing broke)

### Task 7: Final verification grep
```bash
grep -rn -i "joe\|bloggs\|mary bloggs\|fred.bloggs" --include="*.py" --include="*.md" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v venv | grep -v bundled-python | grep -v desktop/release | grep -v __pycache__ | grep -v '.git/'
```
- Must return zero results

### Task 8: Commit
```bash
git add -A
git commit -m "chore: replace real student name with synthetic 'Joe Bloggs' across tests, docs, and comments

Remove all references to real student PII (name, parent name, teacher email)
from tracked source files. Replaced with synthetic equivalents for privacy.

Sample folder (real documents) will be handled separately via git history rewrite."
```

### Task 9: Push
```bash
git push origin test
```

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Test breakage from name length difference ("Joe" 4 chars → "Joe" 3 chars) | Run full test suite after replacement. Length-dependent assertions are unlikely but possible in OCR bounding box tests. |
| Missed variant (e.g., `BLOGGS` in a constant name) | Final verification grep catches anything missed. |
| Breaking a regex pattern in tests | "Joe" and "Bloggs" are both simple alpha strings — no special regex chars. Safe replacement. |
| Partial word replacement ("Bloggs" inside another word) | Use word-boundary-aware replacement where possible. Manual review for edge cases. |
| `sample/` filenames still referenced in test strings | These are string literals — they get updated. The actual `sample/` files stay until Step 2. |

---

## Post-Completion

After this plan is executed:
1. **All tracked code is PII-free** (grep verification confirms)
2. **Tests still pass** (pytest confirms)
3. **Step 2 remains:** Remove `sample/` folder from git history via `git filter-repo`
4. **CLAUDE.md memory:** Update auto-memory to note PII replacement is complete
