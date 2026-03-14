# Desktop App Comprehensive Update — Design Document

**Date**: 2026-03-13
**Goal**: Fix all feature gaps, add cancel/abort, About footer, and wire up missing API fields — single DMG rebuild.

---

## Context

The Phase 2 desktop app (Electron + React) is missing several features that exist in the Streamlit version, plus new UX requirements. The backend already supports all needed fields (`organisation_names`, `redact_header_footer`, `parent_names`, `family_names` in redact). The gaps are **frontend-only**.

---

## 1. Store + API Wiring (Feature Parity)

### store.ts
- Add `organisationNames: string` (default `''`) and `redactHeaderFooter: boolean` (default `false`)
- Add setters: `setOrganisationNames`, `setRedactHeaderFooter`
- Include both in `reset()`

### api.ts
- `detectPII()`: add `organisation_names` param
- `redact()`: add `parent_names`, `family_names`, `organisation_names`, `redact_header_footer` params

### Callers
- `ConversionStatus.tsx` `handleContinue`: pass `organisation_names` from store
- `FinalConfirmation.tsx` `handleRedact`: pass all four missing fields from store

---

## 2. FolderSelection.tsx — New Input Fields

- **Organisation names**: text input, comma-separated, optional. Same style as parent/family names.
- **Redact header/footer zones**: checkbox. Label: "Blank the top and bottom of each page (removes letterheads, school logos, and addresses)"

Both wired to new store fields.

---

## 3. DocumentReview.tsx — Accept All + Auto-Skip

### "Accept All & Continue to Summary" button
- Top of page, above per-document review
- Marks all selections `true` across all documents, navigates to `final_confirmation`
- Styled as secondary/outline button

### Auto-skip zero-PII documents
- Forward navigation skips documents with zero matches
- Brief note: "Skipped N documents with no PII detected"
- Previous button still allows viewing skipped docs

---

## 4. FinalConfirmation.tsx — Default Selection + Cancel

### Fix null default
- `folderAction` initial state: `null` → `'new'`

### Cancel during redaction
- `AbortController` on redact API call
- "Cancel" button visible while processing
- Confirmation dialog: "Are you sure? Progress will be lost."
- On confirm: abort fetch, return to document_review

---

## 5. ConversionStatus.tsx — Cancel During Processing

- `AbortController` for folder processing and PII detection API calls
- "Cancel" button during active processing
- Confirmation dialog → abort → return to folder_selection

---

## 6. Sidebar — About Footer

- Version: **v0.1.0**
- Clickable "GitHub" link → opens repo URL in default browser
- Small text: "Report issues on GitHub"

### Electron IPC for external links
- Preload: `openExternal: (url) => ipcRenderer.invoke('open-external', url)`
- Main: `ipcMain.handle('open-external', (_, url) => shell.openExternal(url))`
- Type declaration updated in `electron.d.ts`

---

## 7. Completion.tsx — Filename Audit

- Collapsible section showing which output filenames had PII removed
- Compare `document_name` vs `output_path` from redaction results
- Only show section if any renames occurred

---

## Files Changed

| File | Changes |
|------|---------|
| `desktop/src/store.ts` | Add organisationNames, redactHeaderFooter, setters, reset |
| `desktop/src/api.ts` | Add missing params to detectPII and redact |
| `desktop/src/electron.d.ts` | Add openExternal type |
| `desktop/electron/preload.cjs` | Add openExternal IPC bridge |
| `desktop/electron/main.cjs` | Add open-external IPC handler |
| `desktop/src/pages/FolderSelection.tsx` | Org names input, header/footer checkbox |
| `desktop/src/pages/ConversionStatus.tsx` | Cancel button, AbortController, pass org names |
| `desktop/src/pages/DocumentReview.tsx` | Accept All button, auto-skip zero-PII docs |
| `desktop/src/pages/FinalConfirmation.tsx` | Default folderAction, cancel button, pass all API fields |
| `desktop/src/pages/Completion.tsx` | Filename audit table |
| `desktop/src/components/Sidebar.tsx` | About footer with version + GitHub link |
