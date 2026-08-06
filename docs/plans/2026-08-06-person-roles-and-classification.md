# Person Roles & User Classification — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-08-06 · **Revised after senior review** (13 required/medium changes folded in; see *Review outcomes* at the end)
**Branch:** `test`
**Builds on:** `docs/plans/2026-08-06-deidentify-for-ai-mode.md` (shipped — commits 11fc62e…da8c3d1)

**Goal:** In de-identify mode, replace the semantically empty `[Person 1]` with a *role* label the user has confirmed — `[Teacher]`, `[Paediatrician]`, `[Parent 2]` — via a new "Who's who?" screen that proposes a role with its evidence and lets the user correct it.

**Architecture:** `PseudonymMap` already groups every name variation into one owner. That owner gains a `role`. A new `role_suggester` module proposes a role from surrounding text and reports *why*. Two new endpoints return the discovered people and compute their labels; the user's answers come back on the de-identify request and drive the output.

**Tech Stack:** Python 3.13, FastAPI, React + Zustand. No new dependencies.

---

## Why this matters

The tool cannot know that "Sarah Williams" is a speech pathologist rather than a classroom teacher, or that "Ms Chen" is a parent advocate rather than staff. A real student file routinely contains teachers, principals, aides, paediatricians, psychologists, speech pathologists, OTs, NDIS support workers, social workers, guardians, foster carers and parents — **and several of each**.

| | Consequence |
|---|---|
| **Label everyone `[Person N]`** (today) | Safe but useless. An AI reads "[Person 1] recommends continued small-group support" and cannot tell a teacher's classroom judgement from a paediatrician's clinical recommendation. |
| **Guess the role and be wrong** | Actively harmful. "[Teacher 1]" over a paediatrician's advice invites an AI to reason about it as classroom observation. Worse than no label. |

So the tool **proposes with evidence and lets the user decide** — never guesses silently. With no evidence the answer is `[Other person N]`, not a plausible-sounding guess.

### Privacy note (must appear in the UI)

A role is more identifying than `[Person N]`. In a small school, "[Speech pathologist]" plus context may point at one individual. That is a real trade-off the user is entitled to make, so it is surfaced as one plain line of copy, not a blocker. The **invariant is unchanged**: a label must contain no part of a real name (CLAUDE.md rule #42).

---

## Role vocabulary

| key | Label | Covers |
|---|---|---|
| `parent` | `[Parent]` | Mother, father, step-parent |
| `carer` | `[Carer]` | Guardian, foster carer, kinship carer |
| `teacher` | `[Teacher]` | Classroom and specialist teachers |
| `school_staff` | `[School staff]` | Principal, deputy, aide/SSO, wellbeing coordinator, counsellor, chaplain |
| `health` | `[Health professional]` | Paediatrician, psychologist, speech pathologist, OT, physio, psychiatrist |
| `support_worker` | `[Support worker]` | NDIS worker, social worker, case manager, advocate |
| `other_student` | `[Other student]` | Classmates, siblings at school |
| `other` | `[Other person]` | **Default when unsure** |
| *(custom)* | user's own text | e.g. `[Speech pathologist]` |

**`[Student]` is unchanged** and is never in the classification list.

### Custom roles — sanitisation (required change 1)

`sanitise_custom_role(text, pmap)` returns `Optional[str]`. Rejects when the text:

- contains a digit, is >30 chars, or is empty after cleaning;
- contains anything but letters, spaces, hyphens and apostrophes;
- **contains any known name variation belonging to ANY owner in the map** — student, parents, family, discovered people *and organisations*.

That last check **must reuse `redactor._pii_visible_in_text()`**, not a fresh substring test. That helper is already hardened against the traps this would otherwise rediscover: whole-word matching so "Ann" inside "Annual" is not a false positive (rule #9), and `_PII_SEP` tokenisation so hyphen/space variants are still caught (rule #45). Scope is *every* owner, not just the one being classified — "Sarah's colleague" typed against a different person must still be rejected.

Rejected input falls back to `[Other person]` and the UI says why.

**Residual risk to document** (CLAUDE.md Known Gaps): nicknames are only generated for the student (`include_nicknames=True` at `pseudonym_map.py:180`), so a custom role spelling out a *colleague's* nickname ("Genny" for Genevieve) is not caught. Low likelihood for job titles; acknowledged rather than silently ignored.

### Numbering — one namespace, keyed on the rendered stem (required change 2)

Number only when 2+ owners share a label stem: one teacher is `[Teacher]`, three are `[Teacher 1..3]`.

**Numbering is computed over the FINAL RENDERED STEM TEXT** (case- and whitespace-normalised), across built-in and custom roles **together** — not per role key. Without this, two people who independently type "Speech pathologist", or one assigned the built-in `health` role while another types the custom text "Health professional", both emit a bare unnumbered label and become indistinguishable in the output. That is the rule #44 meaning failure, user-induced instead of merge-induced.

---

## Suggestion engine (`src/core/role_suggester.py`)

```python
ROLE_KEYWORDS = {
  'parent':         ['mother','mum','mom','father','dad','parent','stepmother',
                     'stepfather','step-mother','step-father'],
  'carer':          ['carer','caregiver','foster','kinship','guardian'],
  'teacher':        ['teacher','classroom teacher','class teacher','tutor'],
  'school_staff':   ['principal','deputy','assistant principal','aide','sso',
                     'wellbeing','coordinator','integration aide','chaplain',
                     'counsellor','counselor','learning support officer'],
  'health':         ['paediatrician','pediatrician','psychologist','psychiatrist',
                     'speech','pathologist','occupational therapist','ot',
                     'physiotherapist','physio','gp','doctor','clinician',
                     'therapist','audiologist','optometrist'],
  'support_worker': ['ndis','support worker','social worker','case manager',
                     'caseworker','case worker','advocate','support coordinator'],
  'other_student':  ['classmate','peer','fellow student','another student',
                     'sibling','brother','sister'],
}
```

**All matching uses `\b` word boundaries** (required change 13) — never manual space-padding, which misses a keyword at the very start or end of a snippet ("OT recommended…"). This is what keeps `ot` and `gp` from firing inside ordinary words.

**The bare keyword `'student'` is deliberately absent** (required change 11). It is near-ubiquitous in these reports and almost always refers to the report's subject, who is excluded from this screen anyway; a lone "student" near a teacher's name would mislabel them a classmate. Only qualifying phrases count.

```python
@dataclass
class RoleSuggestion:
    role_key: str
    confidence: str      # 'likely' | 'possible' | 'unknown'
    evidence: str        # the phrase found, '' when unknown
    snippet: str         # the context it came from, for display

def suggest_role(name: str, contexts: List[str]) -> RoleSuggestion
```

Rules: keyword in the same snippet as the name → `likely`. Honorific `Dr` with nothing else → `health`/`possible`. Ties or no match → `other`/`unknown`. **Never emit a confident guess without a quotable phrase.** `'guardian'` sits under both `parent` and `carer` on purpose; a tie resolves to `unknown` so the user decides — the ambiguous case that motivated the feature.

User-entered people are not guessed at: the Parent/Guardian box pre-fills `parent`, the Family box pre-fills `other` (a sibling is not necessarily a student). Both stay editable.

---

### Task 1: Roles in `PseudonymMap`

**Files:** Modify `src/core/pseudonym_map.py`; modify `tests/test_pseudonym_map.py`

- `ROLE_LABELS: Dict[str, str]`; `DEFAULT_ROLE = 'other'`.
- `_Owner` gains `role: str` and `custom_label: Optional[str]`. **No `role_locked` field** — see *What was cut*.
- `register_person(full_name, role=None)`; `assign_role(full_name, role_key, custom_label=None)` resolving the name through the existing merge rule, so "Ms Williams" and "Sarah Williams" set the same owner.
- `sanitise_custom_role(text)` as specified above.
- **Split `_rebuild()` into two passes** (required change 10): `_resolve_shared_tokens()` — today's priority-based logic, byte-for-byte unchanged — and a new `_assign_role_labels()` computing stems and numbering. Both called from `_rebuild()`. Role numbering must not be able to corrupt the delicate priority logic rule #44 depends on.
- `people()` → `List[PersonInfo]` (`full_name`, `label`, `role`, `custom_label`, `source`).

**Tests:** one teacher → `[Teacher]`, three → `[Teacher 1..3]`; assignment via a variation hits the right owner; **two owners with the identical custom text get numbered `[Speech pathologist 1..2]`**; **a custom role colliding with a built-in label's text shares its numbering namespace**; custom role containing any owner's name (including an org, and including a *different* person's name) rejected; digits rejected; `TestNoIdentityLeaksIntoLabels` extended to loop over every role label including customs; default `[Other person N]`; `[Student]` undisturbed; numbering stable across two documents; the shared-surname rule (rule #44) still holds after role assignment.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_pseudonym_map.py -v`

---

### Task 2: `role_suggester.py`

**Files:** Create `src/core/role_suggester.py`; create `tests/test_role_suggester.py`

**Tests:** each role from a realistic sentence; `Dr` → `health`/`possible`; no evidence → `unknown`; `guardian` ambiguity → `unknown`; `ot`/`gp`/`physio` do not fire inside "note"/"gpa"/"physiology"; a keyword at the very start of a snippet still matches; bare "student" does NOT suggest `other_student`; evidence string is actually present in the returned snippet.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_role_suggester.py -v`

---

### Task 3: Service + two endpoints

**Files:** Modify `src/services/deidentification_service.py`, `backend/main.py`, `backend/schemas.py`; create `tests/test_person_roles_api.py`

`DeidentifyRequest` gains `person_roles: Dict[str, str]`, `person_custom_labels: Dict[str, str]`, `ignored_people: List[str]` (all keyed by discovered full name). Applied after registration, before any replacement.

**Ignored people**: not registered as a person; their text still gets replaced via its category fallback, so nothing is silently skipped.

**`POST /api/deidentify/people`** (required change 3) — takes **the same request body as `/api/deidentify`** (names + `selected_keys`) so it builds an identical `PseudonymMap`, and **registers only SELECTED matches**, exactly as `execute()` does via `_selected_matches()`. Returns per person: `full_name`, `label`, `suggested_role`, `confidence`, `evidence`, `snippet`, `occurrences`, `source`.

**`POST /api/deidentify/labels`** (required change 7) — takes a proposed `{person_roles, person_custom_labels, ignored_people}` and returns `{full_name: label}` for **every** person. This exists so the screen's live label preview is computed by the one Python implementation instead of a TypeScript reimplementation of the stem/numbering algorithm, which would drift exactly as rule #45 warns. It also naturally satisfies required change 8: reassigning one person can renumber others, so the endpoint returns the whole set and the UI re-renders every card.

Both endpoints return the same 400 on a cache miss, wording matching `no cached detection data` (rule #41).

**The people list must never be persisted or logged** — it contains real names by construction. Response only.

**Tests:** endpoint shapes; cache-miss 400; **a person whose only occurrence was deselected does not appear**; roles reaching output labels end-to-end; ignored person's text still replaced; custom label applied; assignment through a variation; key file gains a role column; **the audit log still contains no real names** (rule #43); labels endpoint renumbers siblings when one assignment changes.

**Verify:** `venv/bin/python3.13 -m pytest tests/ -q`

---

### Task 4: The "Who's who?" screen

**Files:** Create `desktop/src/pages/PeopleReview.tsx`; modify `types.ts`, `store.ts`, `api.ts`, `App.tsx`, `Sidebar.tsx`, `DocumentReview.tsx`, `FinalConfirmation.tsx`, `lib/errorMessage.ts`; modify `desktop/tests/workflowMode.test.ts`

New screen `people_review`, **de-identify mode only**, between `document_review` and `final_confirmation`.

`SCREENS` becomes `screensFor(mode: WorkflowMode)` — 6 steps in de-identify mode, 5 in redact. Sidebar must tolerate `findIndex` → -1 for screens outside the array (`setup`, `mode_selection`).

**Routing (required change 5).** All **three** `navigateTo('final_confirmation')` sites in `DocumentReview.tsx` (lines 127, 307, 317) route via `people_review` in de-identify mode. `NoPiiFound.tsx:93` deliberately **does not**: zero matches means zero selected person-category matches, so there is nobody to classify — stated here so it reads as a decision, not an oversight. `FinalConfirmation.tsx`'s `backTarget` (line 113) becomes three-way and must not bounce through an auto-skipped empty `people_review`.

**Per-person card:** the name as it appears in the document (local UI only, never written to disk); occurrence count and one context snippet; the suggested role **and its evidence** — *"Suggested because 'speech pathologist' appears nearby"*, or *"Not enough context to tell — please choose"*; a dropdown (8 roles + "Something else…" + "Not a person — ignore"); and the server-computed label preview.

**Screen behaviour:** unknowns sorted first; a header count (*"3 of 5 need your input"*); **"Accept all suggestions"** for the fast path; never mandatory (unknowns are already safe); one line on the trade-off (*"A role tells the AI more, but is a little more identifying than 'Person 1'. Use a general role if you're unsure."*); empty state auto-skips with the `autoAdvancedKey` guard pattern (rule #38); **clears `detectionParamsKey` on a `no cached detection data` 400** (required change 6, rule #41).

**Store:** `personRoles`, `personCustomLabels`, `ignoredPeople`, `peopleReviewed`. Cleared by `setDetectionResults`, `setWorkflowMode`, **and every selection mutation — `toggleSelection`, `selectAll`, `deselectAll`, `addManualMatch`** (required change 4). `document_review` sits before this screen, so a user can go back and change selections after classifying; a role assigned to a since-deselected person must not linger. **Not** part of `detectionParamsKey`.

**Verify:** `cd desktop && npm test && npm run build && npm run lint` (lint must stay at 7 errors + 1 warning)

---

### Task 5: Copy, docs, end-to-end

**Files:** Modify `CLAUDE.md`, `README.md`, `Walkthrough.tsx`, `AboutModal.tsx`

New CLAUDE.md rules: (a) roles are **proposed, never assumed** — no evidence ⇒ `[Other person]`; (b) custom roles are sanitised via `_pii_visible_in_text` against *every* owner's variations, or they bypass rule #42; (c) numbering is keyed on the rendered stem across built-in and custom roles together; (d) the people list is response-only and never written to disk; (e) people-review state dies with any selection change. Plus the nickname residual risk under Known Gaps.

New e2e script: a paediatrician, a speech pathologist, an NDIS worker, two teachers and a guardian — asserting correct numbering, no name in any label, no name in the log, and the key file's role column. Re-run the two existing e2e scripts.

Manual QA note: the Sidebar's `layoutId="activeStep"` shared-element animation across a 5→6 step array when switching mode mid-flow (Sidebar never remounts, rule #23) — worth a look even if functionally fine.

**Verify:** full suite + all three e2e scripts.

---

## Task order

1 → 2 → 3 → 4 → 5. Tasks 1–3 are pure Python and independently testable before any UI exists.

## Out of scope

- Remembering roles between runs (a cross-session person register would be a stored list of real names — a new privacy surface, wrong to add casually).
- Role detection in redact mode (labels are irrelevant there).
- Inferring roles from a document's *type* rather than its text.

## What was cut

**Backend-enforced `role_locked`.** No privacy invariant depends on it: the student is excluded from the classification list regardless, and the only other beneficiaries are pre-filled Parent/Family entries the plan already wanted editable. The UX protection is achieved purely in the frontend — "Accept all suggestions" simply never includes a pre-filled, untouched card in its payload, while any explicit dropdown change is sent as a real assignment. This removes a backend field, an `assign_role()` edge case, and the `is_locked`/`role_locked` naming confusion.

## Review outcomes

Senior review returned "not ready as written" with 9 required + 4 medium changes. All are folded in above: custom-role sanitisation reusing `_pii_visible_in_text` across all owners (1); stem-keyed numbering namespace (2); people-endpoint request schema and selected-only registration (3); store invalidation on selection changes (4); all four `final_confirmation` call sites enumerated (5); `detectionParamsKey` clearing on the new screen (6); server-computed label preview instead of a TS reimplementation (7); whole-list re-render on any change (8); `role_locked` cut rather than specified (9); `_rebuild()` split in two (10); bare `'student'` keyword removed (11); counsellor/physio/caseworker/chaplain/step-parent keywords added (12); word-boundary matching throughout (13). Optional items taken: org variations in the forbidden list, nickname residual risk documented, Sidebar animation QA note.
