# Faster Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce required user clicks from 5+ to 3 across the full workflow by adding an Accept All shortcut, auto-running detection, auto-skipping zero-PII documents, and simplifying the folder conflict UI.

**Architecture:** All four changes are confined to `src/ui/screens.py`. No new services, core logic, session state keys, or tests are added — this is a pure UI layer change. All changes are independent of each other and can be committed separately.

**Tech Stack:** Streamlit session state, `navigate_to()` from `src/core/session_state.py`

---

## Task 1: Auto-run detection after conversion (remove "Continue" click)

**Files:**
- Modify: `src/ui/screens.py` — bottom of `conversion_status_screen()`, lines ~165–182

**Context:** Currently the user must click "Continue" to trigger detection after conversion
finishes. The goal is to have detection start automatically and navigate to document review
without requiring any button click.

**No unit test** — Streamlit UI. Manual smoke test described at end of task.

**Step 1: Replace the Continue button block**

Locate this block (around line 165):

```python
    # Continue button
    if results.processable_count == 0:
        st.error("No files available for processing. Please check your folder and try again.")
        if st.button("Back to Folder Selection"):
            session_state.navigate_to('folder_selection')
    else:
        st.info(f"Ready to process {results.processable_count} documents")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("Back", use_container_width=True):
                session_state.navigate_to('folder_selection')
        with col3:
            if st.button("Continue", use_container_width=True, type="primary"):
                with st.spinner("Extracting text and detecting PII..."):
                    _run_detection()
                session_state.navigate_to('document_review')
```

Replace it with:

```python
    # Auto-run detection
    if results.processable_count == 0:
        st.error("No files available for processing. Please check your folder and try again.")
        if st.button("Back to Folder Selection"):
            session_state.navigate_to('folder_selection')
    else:
        st.info(f"Ready to process {results.processable_count} documents")
        with st.spinner("Scanning for PII..."):
            _run_detection()
        session_state.navigate_to('document_review')
```

**Step 2: Smoke test**

Run the app: `source venv/bin/activate && streamlit run app.py`

- Enter a valid folder path and student name → click Start Processing
- Step 2 should show conversion results, then immediately show "Scanning for PII…" spinner
- After scanning, should automatically land on Step 3 (document review) with no button click required
- Also test: a folder with zero valid documents — should show the error and Back button and stop

**Step 3: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: auto-run PII detection after conversion, remove Continue button"
```

---

## Task 2: "Accept All" button at top of document review

**Files:**
- Modify: `src/ui/screens.py` — top of `document_review_screen()`, after the early return guard

**Context:** The document review screen currently shows one document at a time. We add a
prominent button at the very top that accepts all PII across all documents and jumps to the
final confirmation screen.

**No unit test** — Streamlit UI. Manual smoke test described at end of task.

**Step 1: Add the Accept All button**

In `document_review_screen()`, locate this block (around line 220):

```python
    current_idx = st.session_state.current_doc_index
    total_docs = len(st.session_state.documents)
    current_doc = st.session_state.documents[current_idx]
```

Insert the Accept All section immediately BEFORE this block (after the early return guard for
`if not st.session_state.documents`):

```python
    # ── Accept All shortcut ──────────────────────────────────────────────
    if st.button(
        "✓ Accept All & Continue to Summary",
        use_container_width=True,
        type="primary",
        help="Mark all detected PII across every document for redaction and skip to the summary.",
    ):
        for doc in st.session_state.documents:
            matches = st.session_state.detected_pii.get(doc, {}).get('matches', [])
            for i in range(len(matches)):
                st.session_state.user_selections[f"{doc}_{i}"] = True
        session_state.navigate_to('final_confirmation')

    st.caption("All detected PII will be marked for redaction — or review each document below.")
    st.divider()
    # ─────────────────────────────────────────────────────────────────────
```

**Step 2: Smoke test**

- Run through to Step 3 with a folder that has multiple documents
- The Accept All button should appear at the top above the progress bar
- Click it — should land immediately on Step 4 (final confirmation)
- Verify the summary shows the correct total count (all PII across all docs selected)
- Also verify: stepping through documents one at a time still works exactly as before

**Step 3: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: add Accept All button to document review screen"
```

---

## Task 3: Auto-skip zero-PII documents during manual review

**Files:**
- Modify: `src/ui/screens.py` — top of `document_review_screen()`, just after the Accept All block

**Context:** When stepping through documents manually, any document with zero detected PII
matches currently still requires a "Next Document" click. We skip these automatically and
show a brief notice so the user knows what happened.

**No unit test** — Streamlit UI. Manual smoke test described at end of task.

**Step 1: Add auto-skip logic**

Immediately after the Accept All block added in Task 2 (before `current_idx = ...`), insert:

```python
    current_idx = st.session_state.current_doc_index
    total_docs = len(st.session_state.documents)

    # ── Auto-skip zero-PII documents ─────────────────────────────────────
    # Find docs with PII at or after the current position
    docs_with_pii = [
        i for i, doc in enumerate(st.session_state.documents)
        if st.session_state.detected_pii.get(doc, {}).get('matches', [])
    ]
    future_pii = [i for i in docs_with_pii if i >= current_idx]

    if not future_pii:
        # No PII in any remaining document — go straight to confirmation
        session_state.navigate_to('final_confirmation')
        return

    next_pii_idx = future_pii[0]
    if next_pii_idx != current_idx:
        skipped_names = [
            st.session_state.documents[i].name
            for i in range(current_idx, next_pii_idx)
        ]
        st.session_state.current_doc_index = next_pii_idx
        current_idx = next_pii_idx
        st.info(
            f"Skipped {len(skipped_names)} document(s) with no PII detected: "
            + ", ".join(skipped_names)
        )
    # ─────────────────────────────────────────────────────────────────────

    current_doc = st.session_state.documents[current_idx]
```

**Important:** Remove the original `current_idx`, `total_docs`, and `current_doc` lines that
were already in the function — they are now defined in the block above. Do not duplicate them.

**Step 2: Smoke test**

- Use a folder where at least one document has no PII matches (or temporarily force
  `detected_pii[doc]['matches'] = []` for one doc to test)
- Step through documents manually — the zero-PII document should be skipped
- The info banner should appear naming the skipped file
- If ALL documents have no PII: should navigate straight to final confirmation
- Verify Accept All path still works (it runs before this block, so no interaction)

**Step 3: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: auto-skip zero-PII documents during manual review"
```

---

## Task 4: Replace folder conflict radio with a checkbox

**Files:**
- Modify: `src/ui/screens.py` — folder conflict block in `final_confirmation_screen()`, lines ~353–363

**Context:** When a `redacted/` folder already exists, the current 3-option radio forces an
explicit selection even though Overwrite is almost always correct. Replace with a simple
checkbox that defaults to Overwrite.

**No unit test** — Streamlit UI. Manual smoke test described at end of task.

**Step 1: Replace the radio block**

Locate this block (around line 352):

```python
    if redacted_folder.exists():
        st.info("A 'redacted' folder already exists")
        folder_action = st.radio(
            "Choose an action:",
            ["Overwrite existing folder", "Create new folder (redacted_2)", "Cancel"],
            index=0
        )
```

Replace it with:

```python
    if redacted_folder.exists():
        st.info("A 'redacted' folder already exists — it will be overwritten.")
        create_new = st.checkbox("Create a new folder instead (redacted_2)")
        folder_action = "Create new folder (redacted_2)" if create_new else "Overwrite existing folder"
```

**Step 2: Remove the disabled guard**

Locate this line (a few lines below, in the Create Redacted Documents button):

```python
        disabled = (folder_action == "Cancel") if folder_action else False
```

Replace with:

```python
        disabled = False
```

The Cancel option no longer exists, so this guard is moot. The existing "Cancel" button in the
button row still allows the user to abort.

**Step 3: Smoke test**

- Run through to final confirmation with a student folder that already has a `redacted/` subfolder
- Should show the info message + an unchecked checkbox
- By default (checkbox unchecked): clicking Create Redacted Documents should overwrite
- Tick the checkbox: should create `redacted_2/` instead
- With no existing redacted folder: confirm no change in UI (no checkbox shown)

**Step 4: Commit**

```bash
git add src/ui/screens.py
git commit -m "feat: replace folder conflict radio with overwrite-default checkbox"
```

---

## Final Verification

After all four tasks are committed, run a full end-to-end smoke test:

**Fast path (3 clicks):**
1. Enter folder + student name → Start Processing
2. Watch conversion + detection run automatically → auto-navigate to Step 3
3. Click "Accept All & Continue to Summary" → Step 4
4. Click "Create Redacted Documents" → completion screen

**Manual review path (confirm nothing broke):**
1. Same setup → Step 3
2. Step through each document using Previous / Next
3. Use per-document Select All / Deselect All
4. Navigate to Review Summary → Step 4
5. Complete redaction

**Edge cases:**
- Folder with zero processable files: stops at Step 2 with error
- All documents have no PII: Accept All still works; manual path auto-advances to Step 4
- Existing redacted folder: checkbox appears, default (unchecked) overwrites correctly
