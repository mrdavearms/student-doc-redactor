# Desktop Comprehensive Update — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all feature gaps in the Electron + React desktop app before the next DMG build — add missing store/API fields, cancel buttons, accept-all, auto-skip, sidebar about, filename audit, and fix the folder-action default.

**Architecture:** All changes are frontend-only. The FastAPI backend already supports every field we need (`organisation_names`, `redact_header_footer`, `parent_names`, `family_names`). We wire up the React store + API client, then update each page component.

**Tech Stack:** React 18, Zustand, TypeScript, Tailwind v4, Electron IPC (contextBridge)

---

### Task 1: Store — add organisation names + header/footer fields

**Files:**
- Modify: `desktop/src/store.ts:14-77`

**Step 1: Add interface fields and setters**

In `desktop/src/store.ts`, add two fields to the `AppState` interface (after line 24, after `folderValid: boolean;`):

```typescript
  organisationNames: string;
  redactHeaderFooter: boolean;
  setOrganisationNames: (names: string) => void;
  setRedactHeaderFooter: (val: boolean) => void;
```

**Step 2: Add to initialState**

In the `initialState` object, after `familyNames: '',` (line 67), add:

```typescript
  organisationNames: '',
  redactHeaderFooter: false,
```

**Step 3: Add setter implementations**

In the `create<AppState>` block, after `setFolderValid` (line 88), add:

```typescript
  setOrganisationNames: (names) => set({ organisationNames: names }),
  setRedactHeaderFooter: (val) => set({ redactHeaderFooter: val }),
```

**Step 4: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add desktop/src/store.ts
git commit -m "feat(desktop): add organisationNames and redactHeaderFooter to store"
```

---

### Task 2: API client — add missing params to detectPII and redact

**Files:**
- Modify: `desktop/src/api.ts:37-59`

**Step 1: Add organisation_names to detectPII**

Replace the `detectPII` method params (lines 37-46) with:

```typescript
  detectPII: (params: {
    pdf_paths: string[];
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, options?: RequestInit) =>
    request<import('./types').DetectionResults>('/api/pii/detect', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),
```

Note: the extra `options` parameter lets callers pass an `AbortSignal` for cancellation.

**Step 2: Add missing fields to redact**

Replace the `redact` method params (lines 48-59) with:

```typescript
  redact: (params: {
    folder_path: string;
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
    redact_header_footer: boolean;
    documents: string[];
    detected_pii: Record<string, unknown[]>;
    selected_keys: string[];
    folder_action: string | null;
  }, options?: RequestInit) =>
    request<import('./types').RedactionResults>('/api/redact', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),
```

**Step 3: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: Errors in ConversionStatus.tsx and FinalConfirmation.tsx (callers not updated yet) — that's fine, we'll fix those in later tasks.

**Step 4: Commit**

```bash
git add desktop/src/api.ts
git commit -m "feat(desktop): add missing API params for org names, header/footer, cancel support"
```

---

### Task 3: Electron IPC — add openExternal bridge

**Files:**
- Modify: `desktop/electron/main.cjs:6,151-160`
- Modify: `desktop/electron/preload.cjs:8-14`
- Modify: `desktop/src/electron.d.ts:5-11`

**Step 1: Add shell import in main.cjs**

Change line 6 of `desktop/electron/main.cjs` from:

```javascript
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
```

to:

```javascript
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
```

**Step 2: Add open-external IPC handler in main.cjs**

After the `select-folder` handler (after line 160), add:

```javascript
ipcMain.handle('open-external', async (_event, url) => {
  await shell.openExternal(url);
});
```

**Step 3: Add openExternal to preload.cjs**

In `desktop/electron/preload.cjs`, add after `selectFolder` (line 11):

```javascript
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
```

**Step 4: Update TypeScript declaration**

In `desktop/src/electron.d.ts`, add after `selectFolder` (line 8):

```typescript
      openExternal: (url: string) => Promise<void>;
```

**Step 5: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No new errors from these files

**Step 6: Commit**

```bash
git add desktop/electron/main.cjs desktop/electron/preload.cjs desktop/src/electron.d.ts
git commit -m "feat(desktop): add openExternal IPC bridge for opening URLs in browser"
```

---

### Task 4: FolderSelection — add org names input + header/footer checkbox

**Files:**
- Modify: `desktop/src/pages/FolderSelection.tsx:7-13,41,95-154`

**Step 1: Add store fields to destructure**

Change the destructure block (lines 8-13) to:

```typescript
  const {
    folderPath, studentName, parentNames, familyNames,
    organisationNames, redactHeaderFooter,
    folderValid,
    setFolderPath, setStudentName, setParentNames, setFamilyNames,
    setOrganisationNames, setRedactHeaderFooter,
    setFolderValid, navigateTo,
  } = useStore();
```

**Step 2: Add organisation names input**

After the closing `</div>` of the grid (line 153, end of `grid grid-cols-2` div), add:

```tsx
        <div className="mt-4">
          <label className="block text-sm text-slate-600 mb-1.5">
            <Users size={14} className="inline mr-1 text-slate-400" />
            Organisation / school names
          </label>
          <input
            type="text"
            value={organisationNames}
            onChange={(e) => setOrganisationNames(e.target.value)}
            placeholder="Springfield Primary, Child Psychology Clinic"
            className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm
                       focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400"
          />
          <p className="text-[11px] text-slate-400 mt-1">Optional, comma-separated — these names will be redacted from documents</p>
        </div>
```

**Step 3: Add header/footer checkbox**

After the new org names input (and before the closing `</motion.section>` of the Student Information section), add:

```tsx
        <div className="mt-4 pt-4 border-t border-slate-100">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={redactHeaderFooter}
              onChange={(e) => setRedactHeaderFooter(e.target.checked)}
              className="w-4 h-4 accent-primary-600 rounded"
            />
            <div>
              <span className="text-sm text-slate-600">Redact headers and footers</span>
              <p className="text-[11px] text-slate-400 mt-0.5">Blanks the top and bottom of every page — removes letterheads, addresses, and logos</p>
            </div>
          </label>
        </div>
```

**Step 4: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors for this file

**Step 5: Commit**

```bash
git add desktop/src/pages/FolderSelection.tsx
git commit -m "feat(desktop): add org names input and header/footer checkbox to FolderSelection"
```

---

### Task 5: ConversionStatus — pass org names + add cancel button

**Files:**
- Modify: `desktop/src/pages/ConversionStatus.tsx:1-62,95-102,180-198`

**Step 1: Add useRef import and store fields**

Change line 1 import to:

```typescript
import { useEffect, useState, useRef, useCallback } from 'react';
```

Add to the store destructure (lines 12-16):

```typescript
  const {
    folderPath, conversionResults, setConversionResults,
    setDetectionResults, studentName, parentNames, familyNames,
    organisationNames,
    navigateTo, setLoading, setError,
  } = useStore();
```

**Step 2: Add AbortController ref**

After the `expanded` state (line 20), add:

```typescript
  const abortRef = useRef<AbortController | null>(null);
```

**Step 3: Update processFolder useEffect to be cancellable**

Replace the processFolder useEffect (lines 28-35) with:

```typescript
  useEffect(() => {
    if (conversionResults || !deps?.can_convert_word) return;
    setProcessing(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    api.processFolder(folderPath, { signal: ctrl.signal })
      .then((r) => setConversionResults(r))
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => setProcessing(false));
    return () => ctrl.abort();
  }, [deps, folderPath, conversionResults, setConversionResults, setError]);
```

Note: `api.processFolder` already spreads `options` into fetch via `request()`, so passing `{ signal }` works.

**Step 4: Update processFolder API call to accept options**

In `desktop/src/api.ts`, update `processFolder` (lines 31-35) to accept options:

```typescript
  processFolder: (folder_path: string, options?: RequestInit) =>
    request<import('./types').ConversionResults>('/api/folder/process', {
      method: 'POST',
      body: JSON.stringify({ folder_path }),
      ...options,
    }),
```

**Step 5: Pass organisation_names to detectPII**

In the `handleContinue` function, update the `api.detectPII` call (around line 48) to:

```typescript
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const detection = await api.detectPII({
        pdf_paths: allPdfs,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
      });
```

**Step 6: Add cancel button**

In the processing spinner section (lines 97-102), replace with:

```tsx
      {processing && (
        <div className="flex items-center justify-between py-4">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <RefreshCw size={16} className="animate-spin text-primary-500" />
            Converting documents...
          </div>
          <button
            onClick={() => {
              if (confirm('Cancel document processing? You can restart from the previous step.')) {
                abortRef.current?.abort();
                setProcessing(false);
                navigateTo('folder_selection');
              }
            }}
            className="px-4 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 transition-colors"
          >
            Cancel
          </button>
        </div>
      )}
```

**Step 7: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 8: Commit**

```bash
git add desktop/src/pages/ConversionStatus.tsx desktop/src/api.ts
git commit -m "feat(desktop): add cancel button and pass org names in ConversionStatus"
```

---

### Task 6: DocumentReview — add Accept All + auto-skip zero-PII docs

**Files:**
- Modify: `desktop/src/pages/DocumentReview.tsx:1-12,30-35,64-67,164-183`

**Step 1: Add CheckCircle2 import**

Change line 3 imports to:

```typescript
import {
  ArrowLeft, ArrowRight, CheckSquare, Square, FileText, CheckCircle2,
} from 'lucide-react';
```

**Step 2: Add Accept All button**

After the progress bar section (after line 51, before the document header div), add:

```tsx
      {/* Accept All shortcut */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end"
      >
        <button
          onClick={() => navigateTo('final_confirmation')}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium
                     bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm hover:shadow transition-all"
        >
          <CheckCircle2 size={16} /> Accept All & Continue to Summary
        </button>
      </motion.div>
```

Since `setDetectionResults` already initialises all selections to `true`, this button just skips straight to the summary — every match is pre-selected.

**Step 3: Add auto-skip for zero-PII docs on forward navigation**

Create a helper function after the destructure block (after line 12):

```typescript
  /** Find the next doc index that has PII matches, starting from `from`. Returns totalDocs if none found. */
  const nextDocWithPII = (from: number): number => {
    for (let i = from; i < detectionResults!.documents.length; i++) {
      if (detectionResults!.documents[i].matches.length > 0) return i;
    }
    return detectionResults!.documents.length;
  };
```

Then replace the "Next Document" button's onClick (line 168):

```typescript
onClick={() => {
  const next = nextDocWithPII(currentDocIndex + 1);
  if (next < totalDocs) {
    setCurrentDocIndex(next);
  } else {
    navigateTo('final_confirmation');
  }
}}
```

And the "Previous" button's onClick needs a backward-skip too. Replace line 151:

```typescript
onClick={() => {
  // Go back to previous doc with PII (or just go back 1 if none)
  for (let i = currentDocIndex - 1; i >= 0; i--) {
    if (detectionResults!.documents[i].matches.length > 0) {
      setCurrentDocIndex(i);
      return;
    }
  }
  setCurrentDocIndex(Math.max(0, currentDocIndex - 1));
}}
```

**Step 4: Auto-advance on mount if current doc has zero PII**

Add a useEffect after the `nextDocWithPII` helper:

```typescript
  // Auto-skip to first doc with PII on mount / when index changes
  useEffect(() => {
    if (!detectionResults) return;
    const doc = detectionResults.documents[currentDocIndex];
    if (doc && doc.matches.length === 0) {
      const next = nextDocWithPII(currentDocIndex + 1);
      if (next < detectionResults.documents.length) {
        setCurrentDocIndex(next);
      }
    }
  }, [currentDocIndex, detectionResults, setCurrentDocIndex]);
```

Add `useEffect` to the React import at line 1:

```typescript
import { useEffect } from 'react';
```

**Step 5: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add desktop/src/pages/DocumentReview.tsx
git commit -m "feat(desktop): add Accept All button and auto-skip zero-PII docs in DocumentReview"
```

---

### Task 7: FinalConfirmation — fix default, add cancel, pass all API fields

**Files:**
- Modify: `desktop/src/pages/FinalConfirmation.tsx:1-61,153-176`

**Step 1: Add useRef import**

Change line 1 to:

```typescript
import { useState, useRef } from 'react';
```

**Step 2: Update store destructure**

Replace lines 8-11 with:

```typescript
  const {
    detectionResults, userSelections, folderPath, studentName,
    parentNames, familyNames, organisationNames, redactHeaderFooter,
    navigateTo, setRedactionResults, setLoading, setError,
  } = useStore();
```

**Step 3: Fix folderAction default**

Change line 13 from:

```typescript
  const [folderAction, setFolderAction] = useState<string | null>(null);
```

to:

```typescript
  const [folderAction, setFolderAction] = useState<string>('new');
```

**Step 4: Add AbortController + redacting state**

After `folderAction` state, add:

```typescript
  const [redacting, setRedacting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
```

**Step 5: Update handleRedact to pass all fields and support cancel**

Replace the `handleRedact` function (lines 31-61) with:

```typescript
  const handleRedact = async () => {
    setLoading(true, 'Redacting documents...');
    setRedacting(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const selectedKeys: string[] = [];
      for (const doc of detectionResults.documents) {
        doc.matches.forEach((_, idx) => {
          const key = `${doc.path}_${idx}`;
          if (userSelections[key]) selectedKeys.push(key);
        });
      }

      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const results = await api.redact({
        folder_path: folderPath,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
        redact_header_footer: redactHeaderFooter,
        documents: detectionResults.documents.map((d) => d.path),
        detected_pii: Object.fromEntries(
          detectionResults.documents.map((d) => [d.path, d.matches])
        ),
        selected_keys: selectedKeys,
        folder_action: folderAction,
      }, { signal: ctrl.signal });

      setRedactionResults(results);
      navigateTo('completion');
    } catch (e: any) {
      if (e.name !== 'AbortError') setError(e.message);
    } finally {
      setLoading(false);
      setRedacting(false);
    }
  };
```

**Step 6: Add cancel button next to the redact button**

Replace the navigation section (lines 153-176) with:

```tsx
      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button
          onClick={() => navigateTo('document_review')}
          disabled={redacting}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-50"
        >
          <ArrowLeft size={16} /> Back to Review
        </button>

        <div className="flex gap-2">
          {redacting && (
            <button
              onClick={() => {
                if (confirm('Cancel redaction? Progress will be lost.')) {
                  abortRef.current?.abort();
                }
              }}
              className="px-4 py-2.5 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 transition-colors"
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleRedact}
            disabled={totalSelected === 0 || redacting}
            className={`
              flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all
              ${totalSelected > 0 && !redacting
                ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow'
                : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }
            `}
          >
            <ShieldCheck size={16} /> Create Redacted Documents
          </button>
        </div>
      </div>
```

**Step 7: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 8: Commit**

```bash
git add desktop/src/pages/FinalConfirmation.tsx
git commit -m "feat(desktop): fix folder default, add cancel, pass all API fields in FinalConfirmation"
```

---

### Task 8: Sidebar — update version + add GitHub link

**Files:**
- Modify: `desktop/src/components/Sidebar.tsx:92-95`

**Step 1: Add ExternalLink import**

Change line 2 to:

```typescript
import { Check, FolderOpen, RefreshCw, Search, ShieldCheck, PartyPopper, ExternalLink } from 'lucide-react';
```

**Step 2: Replace footer section**

Replace lines 92-95 with:

```tsx
      {/* Footer */}
      <div className="px-6 py-4 border-t border-slate-100 space-y-2">
        <p className="text-[10px] text-slate-300 uppercase tracking-widest">v0.1.0</p>
        <button
          onClick={() => window.electronAPI?.openExternal('https://github.com/mrdavearms/student-doc-redactor')}
          className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-primary-500 transition-colors"
        >
          <ExternalLink size={10} />
          Report issues on GitHub
        </button>
      </div>
```

**Step 3: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add desktop/src/components/Sidebar.tsx
git commit -m "feat(desktop): add v0.1.0 version and GitHub link to sidebar footer"
```

---

### Task 9: Completion — add filename audit table

**Files:**
- Modify: `desktop/src/pages/Completion.tsx:95-115`

**Step 1: Add FileOutput icon import**

Change line 3 to:

```typescript
import {
  CheckCircle, AlertTriangle, XCircle, FolderOpen, FileText, RotateCcw,
  ChevronDown, ChevronUp, ArrowRight,
} from 'lucide-react';
```

**Step 2: Add filename audit section**

After the "Output folder" section (after line 115, before the "Redaction log" section), add:

```tsx
      {/* Filename audit */}
      {r.document_results && r.document_results.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-white rounded-xl border border-slate-200 p-5"
        >
          <h3 className="text-sm font-medium text-slate-600 mb-3">Filename Audit</h3>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {r.document_results.map((d, i) => {
              const inputName = d.document_name;
              const outputName = d.output_path ? d.output_path.split('/').pop() : '—';
              const renamed = inputName !== outputName;
              return (
                <div key={i} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-slate-500 truncate flex-1" title={inputName}>{inputName}</span>
                  <ArrowRight size={10} className="text-slate-300 shrink-0" />
                  <span className={`truncate flex-1 ${renamed ? 'text-primary-600 font-medium' : 'text-slate-400'}`} title={outputName || ''}>
                    {outputName}
                  </span>
                  {!d.success && <XCircle size={12} className="text-red-400 shrink-0" />}
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 mt-2">Highlighted filenames had PII removed.</p>
        </motion.section>
      )}
```

**Step 3: Verify TypeScript compiles**

Run: `cd desktop && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add desktop/src/pages/Completion.tsx
git commit -m "feat(desktop): add filename audit table to Completion page"
```

---

### Task 10: Final verification — full build

**Step 1: TypeScript check**

Run: `cd desktop && npx tsc --noEmit`
Expected: 0 errors

**Step 2: Vite production build**

Run: `cd desktop && npm run build`
Expected: Build succeeds (JS + CSS bundles created in dist/)

**Step 3: Commit any remaining fixes**

If either check fails, fix the issue and commit.

**Step 4: Final commit (if no fixes needed)**

No action needed — all individual tasks already committed.
