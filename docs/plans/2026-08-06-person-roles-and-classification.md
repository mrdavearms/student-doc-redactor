# Person Roles & User Classification — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-08-06
**Branch:** `test`
**Builds on:** `docs/plans/2026-08-06-deidentify-for-ai-mode.md` (shipped — commits 11fc62e…47475ba)

**Goal:** In de-identify mode, replace the semantically empty `[Person 1]` with a *role* label the user has confirmed — `[Teacher]`, `[Paediatrician]`, `[Parent 2]` — via a new "Who's who?" screen that proposes a role with its evidence and lets the user correct it.

**Architecture:** `PseudonymMap` already groups every name variation into one owner. That owner gains a `role`. A new `role_suggester` module proposes a role from the surrounding text and reports *why*. A new endpoint returns the discovered people for the user to confirm; their answers come back on the de-identify request and drive the labels.

**Tech Stack:** Python 3.13, FastAPI, React + Zustand. No new dependencies.

---

## Why this matters (the problem being solved)

The tool cannot know that "Sarah Williams" is a speech pathologist rather than a classroom teacher, or that "Ms Chen" is a parent advocate rather than staff. A real student file routinely contains teachers, principals, aides, paediatricians, psychologists, speech pathologists, OTs, NDIS support workers, social workers, guardians, foster carers, and parents — **and several of each**.

Two failure modes, and they are not symmetrical:

| | Consequence |
|---|---|
| **Label everyone `[Person N]`** (today) | Safe but useless. An AI reads "[Person 1] recommends continued small-group support" and cannot tell whether that is a teacher's classroom judgement or a paediatrician's clinical recommendation. |
| **Guess the role and be wrong** | Actively harmful. "[Teacher 1]" over a paediatrician's advice invites an AI to reason about it as classroom observation. Worse than no label. |

So the tool must **propose with evidence and let the user decide** — never guess silently. The safe default when it has no evidence is `[Other person N]`, not a plausible-sounding guess.

### Privacy note (must appear in the UI)

A role is more identifying than `[Person N]`. In a small school, "[Speech pathologist]" plus context may point at one individual. This is a real trade-off the user is entitled to make, so it is surfaced as one plain line of copy, not a blocker. The **invariant is unchanged**: a label must still contain no part of a real name (CLAUDE.md rule #42).

---

## Role vocabulary

Chosen to cover the Australian school + allied-health context in as few options as a teacher will tolerate. `key` is stable (stored/sent); `label` is what appears in the output.

| key | Label | Covers |
|---|---|---|
| `parent` | `[Parent]` | Mother, father, step-parent |
| `carer` | `[Carer]` | Guardian, foster carer, kinship carer |
| `teacher` | `[Teacher]` | Classroom and specialist teachers |
| `school_staff` | `[School staff]` | Principal, deputy, aide/SSO, wellbeing coordinator |
| `health` | `[Health professional]` | Paediatrician, psychologist, speech pathologist, OT, psychiatrist |
| `support_worker` | `[Support worker]` | NDIS worker, social worker, case manager, advocate |
| `other_student` | `[Other student]` | Classmates, siblings at school |
| `other` | `[Other person]` | **Default when unsure** |
| *(custom)* | user's own text | e.g. `[Speech pathologist]` — see below |

**Custom roles.** The user may type their own (e.g. "Speech pathologist", "Paediatrician") when the generic label loses something that matters. Sanitised: letters/spaces/hyphens only, ≤30 chars, title-cased, and **rejected if it contains any known name variation** — otherwise a custom role becomes a back door around rule #42. Falls back to `[Other person]` if rejected.

**Numbering.** Number only when a role has 2+ people: one teacher is `[Teacher]`, three are `[Teacher 1..3]`. Reads better and is decided per run, when the totals are known.

**`[Student]` is unchanged** — the subject of the report keeps its dedicated label and is never in the classification list.

---

## Suggestion engine (`src/core/role_suggester.py`)

For each discovered person, scan the `context` of every match attributed to them for role keywords, plus honorific evidence from the name itself.

```python
ROLE_KEYWORDS = {
  'parent':         ['mother','mum','father','dad','parent','stepmother','stepfather','guardian '],
  'carer':          ['carer','caregiver','foster','kinship','guardian'],
  'teacher':        ['teacher','classroom teacher','class teacher','year \\d teacher','tutor'],
  'school_staff':   ['principal','deputy','assistant principal','aide','sso','wellbeing',
                     'coordinator','integration aide','learning support officer'],
  'health':         ['paediatrician','pediatrician','psychologist','psychiatrist','speech',
                     'pathologist','occupational therapist',' ot ','physiotherapist',
                     'gp','doctor','clinician','therapist','audiologist','optometrist'],
  'support_worker': ['ndis','support worker','social worker','case manager','advocate',
                     'support coordinator'],
  'other_student':  ['classmate','peer','friend','student','sibling','brother','sister'],
}
```

Returns `RoleSuggestion(role_key, confidence, evidence)` where `evidence` is the **actual phrase found and the snippet it came from**, so the screen can say *why*. Rules:

- A keyword within the same context snippet as the name → `confidence='likely'`.
- Honorific `Dr` on the name, with no other evidence → `health`, `confidence='possible'`.
- Two roles tie or nothing matches → `other`, `confidence='unknown'`.
- Never emit a confident guess without a quotable phrase. **No evidence ⇒ `unknown` ⇒ `[Other person]`.**

`'guardian'` deliberately appears under both `parent` and `carer`; a tie resolves to `unknown` so the user decides — exactly the ambiguous case that motivated this feature.

**User-entered people are not guessed at.** Anyone typed into the Parent/Guardian box starts as `parent`, the Family members box as `other` (a sibling is not necessarily a student), pre-filled but still editable.

---

### Task 1: Roles in `PseudonymMap`

**Files:** Modify `src/core/pseudonym_map.py`; modify `tests/test_pseudonym_map.py`

- `ROLE_LABELS: Dict[str, str]` per the table; `DEFAULT_ROLE = 'other'`.
- `_Owner` gains `role: str` and `role_locked: bool` (True for the student and for user-entered people, so a later assignment cannot silently retype them unless the user asked).
- `register_person(full_name, role=None)` stores the role.
- `assign_role(full_name, role_key, custom_label=None)` sets it after the fact — this is what the API calls with the user's answers. Resolves the name through the same merge rule, so "Ms Williams" and "Sarah Williams" set the same owner's role.
- `sanitise_custom_role(text, forbidden_variations)` → `Optional[str]`; rejects anything containing a known name variation, anything with digits, >30 chars, or empty after cleaning.
- Label assignment moves into `_rebuild()`: group owners by effective label stem, number only when a stem has 2+ owners. `[Student]`, `[Parent N]`, `[Family member N]` behaviour for user-entered people is **preserved** unless the user reassigns.
- `people()` → `List[PersonInfo]` (`full_name`, `label`, `role`, `is_locked`, `source`), for the API.

**Tests must cover:** one teacher → `[Teacher]`, three → `[Teacher 1..3]`; role assignment via a variation ("Ms Williams") hits the right owner; custom role containing a real name is rejected; custom role with digits rejected; rule #42 invariant still holds for **every** role label including customs (extend `TestNoIdentityLeaksIntoLabels` to loop over all roles); default is `[Other person N]`; assigning a role does not disturb `[Student]`; numbering is stable across two documents.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_pseudonym_map.py -v`

---

### Task 2: `role_suggester.py`

**Files:** Create `src/core/role_suggester.py`; create `tests/test_role_suggester.py`

```python
@dataclass
class RoleSuggestion:
    role_key: str
    confidence: str      # 'likely' | 'possible' | 'unknown'
    evidence: str        # the phrase found, '' when unknown
    snippet: str         # the context it came from, for display

def suggest_role(name: str, contexts: List[str]) -> RoleSuggestion
```

Case-insensitive, whole-word matching (`ot` and `gp` need word boundaries or they fire inside ordinary words). Longest keyword wins within a role; across roles, most distinct hits wins; a tie → `unknown`.

**Tests must cover:** each role from a realistic sentence ("Sarah Williams, speech pathologist, assessed…"); `Dr` honorific → `health`/`possible`; no evidence → `unknown`; 'guardian' ambiguity → `unknown`; `ot`/`gp` do not fire inside "note"/"gpa"; evidence string is actually present in the snippet.

**Verify:** `venv/bin/python3.13 -m pytest tests/test_role_suggester.py -v`

---

### Task 3: Service + `/api/deidentify/people`

**Files:** Modify `src/services/deidentification_service.py`, `backend/main.py`, `backend/schemas.py`; create `tests/test_person_roles_api.py`

- `DeidentifyRequest` gains `person_roles: Dict[str, str]` and `person_custom_labels: Dict[str, str]` (keyed by the discovered full name), and `ignored_people: List[str]`.
- After building the map and registering people, apply the user's assignments before any replacement.
- **Ignored people**: a name the user marks "not a person" (NER junk like a form label) is *not* registered as a person; its text still gets replaced via its category fallback, so nothing is silently skipped.
- The key file's `LABEL -> REAL NAME` table gains a role column, and states which roles the user confirmed vs which were left at the default.

`POST /api/deidentify/people` — reads `_detection_cache`, builds the map exactly as `execute()` does, and returns for each discovered person: `full_name`, `suggested_role`, `confidence`, `evidence`, `snippet`, `occurrences`, `is_locked`, `source`. Same 400 on a cache miss as the other endpoints (wording must keep matching `no cached detection data`, per rule #41).

**The person list must never be persisted or logged** — it contains real names by construction. Response only.

**Tests must cover:** the endpoint's shape; cache-miss 400; roles reaching the output labels end-to-end; an ignored person's text still replaced; custom label applied; role assignment through a variation; the key file's role column; **the audit log still contains no real names** (rule #43) now that roles are involved.

**Verify:** `venv/bin/python3.13 -m pytest tests/ -q`

---

### Task 4: The "Who's who?" screen

**Files:** Create `desktop/src/pages/PeopleReview.tsx`; modify `types.ts`, `store.ts`, `api.ts`, `App.tsx`, `Sidebar.tsx`, `DocumentReview.tsx` (Continue target), `FinalConfirmation.tsx` (Back target), `lib/errorMessage.ts`; modify `desktop/tests/workflowMode.test.ts`

New screen `people_review`, **de-identify mode only**, between `document_review` and `final_confirmation`.

`SCREENS` becomes `screensFor(mode: WorkflowMode)` so the sidebar numbers 6 steps in de-identify mode and 5 in redact mode. Sidebar must tolerate `findIndex` → -1 for screens outside the array (`setup`, `mode_selection`).

Per person, one card:
- The name **as it appears in the document** (local UI only — never written to disk).
- How many times it appears, and one context snippet.
- The suggested role and **the evidence**: *"Suggested because 'speech pathologist' appears nearby."* When unknown: *"Not enough context to tell — please choose."*
- A role dropdown (the 8 roles + "Something else…" revealing a text input, + "Not a person — ignore").
- A live preview of the resulting label: `[Teacher 2]`.

Screen behaviour:
- **Sort unknowns first** — the ones needing attention lead.
- A header count: *"3 of 5 need your input."*
- **"Accept all suggestions"** primary action for the fast path; the screen is never mandatory (unknowns are already safe as `[Other person]`).
- One line of copy on the trade-off: *"A role tells the AI more, but is a little more identifying than 'Person 1'. Use a general role if you're unsure."*
- Empty state (no discovered people): auto-skip forward, with the same `autoAdvancedKey` guard pattern as `ConversionStatus` so Back doesn't bounce the user (rule #38).

Store: `personRoles`, `personCustomLabels`, `ignoredPeople`, `peopleReviewed`. Cleared by `setDetectionResults` and by `setWorkflowMode`. **Not** part of `detectionParamsKey`.

**Tests must cover:** store reducers; `screensFor` returns 6/5 steps; label preview helper; new error-mapper patterns.

**Verify:** `cd desktop && npm test && npm run build && npm run lint` (lint must stay at 7 errors + 1 warning)

---

### Task 5: Copy, docs, end-to-end

**Files:** Modify `CLAUDE.md`, `README.md`, `desktop/src/components/Walkthrough.tsx`, `AboutModal.tsx`

- CLAUDE.md: new screen in the flow diagram, new store keys, new rules — (a) roles are **proposed, never assumed**; no evidence ⇒ `[Other person]`, (b) custom roles are sanitised against name variations or they bypass rule #42, (c) the people list is response-only and never written to disk.
- README: a plain-English section on classifying people, with the privacy trade-off stated.
- Walkthrough/About: mention the second pathway and this step.
- Re-run both scratchpad e2e scripts plus a new one covering a paediatrician, a speech pathologist, an NDIS worker, two teachers and a guardian, asserting: correct numbering, no name in any label, no name in the log, and the key file's role column.

**Verify:** full suite + both e2e scripts.

---

## Task order

1 → 2 → 3 → 4 → 5. Tasks 1–3 are pure Python and independently testable before any UI exists.

## Explicitly out of scope

- Remembering roles between runs (a person map across sessions would be a stored register of real names — a new privacy surface, and wrong to add casually).
- Role detection in redact mode (labels are irrelevant there).
- Inferring roles from a document's *type* rather than its text.
