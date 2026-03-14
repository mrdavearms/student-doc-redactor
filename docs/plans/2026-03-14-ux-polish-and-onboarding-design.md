# UX Polish, Onboarding & Confidence — Design Document

**Date**: 2026-03-14
**Approach**: Full Sweep (all areas in one milestone)
**Audience**: Non-technical teachers, primarily Australian, who need to trust the tool

---

## Design Constraints

- **Stunning, Apple/Notion-native feel** — clean, confident, not cutesy
- **Blue palette retained** — refine usage, not the colours
- **No PII saved to disk** — previews and summaries live in UI memory only, never persisted
- **Technical details hidden** — teachers never see "Tesseract", "LibreOffice", "spaCy", etc.
- **Empowering tone** — the tool is powerful; guidance helps users get the best results

---

## Section 1: Visual Foundation & Typographic Logo

### Typographic Logo
- "Redact" in primary blue-600 weight-700, subtle vertical bar separator, "Tool" in slate-400 weight-300
- Tagline: "Protect student privacy" in slate-400, 10px tracking-wide
- Appears in: sidebar header, About modal header, first-run walkthrough

### Refined Palette Usage
- **Surface hierarchy**: Elevated cards get `shadow-sm` + `ring-1 ring-slate-100` instead of flat borders
- **Primary blue used sparingly**: Reserved for the one primary action per screen. Secondary actions get `slate-100` bg with `slate-600` text
- **Confidence colours**: High = emerald, Medium = amber, Low = rose (softer than red)
- **Typography scale**: Screen titles `text-2xl font-bold tracking-tight`. Subtitles `text-slate-400 text-sm`

### Micro-interactions
- Buttons: `active:scale-[0.98]` press effect via `.btn-press` class
- Interactive cards: `hover:shadow-md transition-shadow`
- Loading: Progress bars where possible (detection, redaction) instead of infinite spinner

---

## Section 2: First-Run Walkthrough

### Trigger & Storage
- Check `localStorage` for `walkthrough_dismissed` key. If absent, show walkthrough as full-screen modal overlay (centred, max-width 560px, backdrop blur)
- "Don't show again" checkbox. Sets `localStorage.walkthrough_dismissed = true`
- "Show walkthrough" button in About modal Tab 2 to re-trigger

### Steps (4 screens, dot navigation)

**Step 1 — "What this app does"**
- Headline: "Protect student privacy in seconds"
- Plain-English explanation of what the tool does. Originals never modified.
- HTML/CSS before/after illustration (not an image file)

**Step 2 — "How it works"**
- Three numbered items with icons: choose folder, review findings, get redacted copies
- Three-click mental model

**Step 3 — "Getting the best results"**
- Headline: "Tips for the best results"
- Empowering tone — the tool is powerful, here's how to help it do its best:
  - Enter all the names you can — the more you provide, the more thorough the detection
  - Unusual name spellings may occasionally be missed — a quick review gives full confidence
  - Scanned and handwritten documents are analysed using OCR, works well on clear scans
  - Recommend a quick review of redacted documents before sharing
- Blue info box: "This tool uses three detection engines working together. It catches the vast majority of PII automatically — these tips help you cover the edge cases."

**Step 4 — "You're ready"**
- "Let's get started" + Start button + "Don't show again" checkbox

### Navigation
- Dot indicators (4 dots, active = blue-600, others = slate-200)
- Next button, Back link (steps 2-4), Skip link (all steps)
- Keyboard: arrow keys and Escape to skip

---

## Section 3: Contextual Tooltips

### Component
Reusable `<HelpTip text="..." />` component. Click `?` icon (14px, slate-300, hover slate-500) to show styled popover (max-width 280px, subtle shadow, click-anywhere to dismiss). Framer Motion fade-in.

### Placements

**Folder Selection:**
- Student full name: "Enter the student's full name as it appears in their documents. First and last name. The tool will also detect variations like first-name-only and surname-only."
- Parent/Guardian names: "Include anyone whose name might appear in the documents — referral letters, consent forms, and reports often mention parents by name."
- Other family members: "Siblings or other family members sometimes appear in assessment reports, especially in background history sections."
- Organisation names: "Schools, clinics, hospitals, therapy centres — any organisation name that could identify the student's location or service providers."
- Redact headers & footers: "Blanks the top and bottom of every page. Useful for removing school letterheads, clinic logos, and addresses that appear in page margins."

**Document Review:**
- Confidence badge (first occurrence, one-time): "High confidence means the tool is very sure this is personal information. Medium means it's likely but worth checking. Items are pre-selected for redaction — uncheck any you want to keep."

**Completion:**
- Verification failures: "The tool re-checks each redacted document to confirm the text was fully removed. A failure here means the original text may still be visible — open the file and check manually."
- Redaction Log: "A detailed record of every item that was redacted, which document it came from, and which detection engine found it. Useful for your own records."

---

## Section 4: Before/After PDF Preview

### Location
Completion screen, between success banner and output folder section. Collapsible, expanded by default.

### UI
- **Document selector**: Horizontal scrollable row of filename tabs. First doc selected by default.
- **Split view**: Left = "Original" (slate border), Right = "Redacted" (emerald border). Page nav at bottom.
- **Skeleton loader** while rendering (pulse animation, not spinner)

### Backend
- New endpoint: `POST /api/preview` — accepts PDF path + page number, renders at 150 DPI via `page.get_pixmap()`, returns base64 PNG
- Two calls per page view (original + redacted)
- Only renders currently viewed page, not whole document

### PII Constraint
Base64 data lives in React component state only. Never saved to disk. Gone when user navigates away.

### Size
- Max height ~500px, images scale to fit
- Collapsible section

---

## Section 5: Completion Summary Cards

### Per-document cards (replaces filename audit)
Each card shows:
- Filename (original → redacted, rename highlighted in blue if PII removed)
- Summary stats: "5 names · 2 phone numbers · 1 email address" — pill badges
- Confidence indicator: all-green if high confidence, amber if medium items included
- Status icon: green check / amber triangle / red circle
- Expandable detail: category + location only (e.g., "Name removed — Page 3, Line 12"), never actual PII text

### Top banner
Refined: "All 8 documents redacted successfully" (confident tone)

### Redaction Log
Stays, collapsed by default (cards provide the better summary)

---

## Section 6: Enriched About Page

### Three tabs within modal

**Tab 1 — "About"** (default)
- Typographic logo, app description (warmer tone), developer credit, GitHub link, version, copyright

**Tab 2 — "How to Use"**
- Full walkthrough content as vertical scrollable guide (all 4 steps)
- "Getting the best results" tips
- "Show welcome walkthrough again" button at bottom

**Tab 3 — "Features & Detection"**
- Features list (cleaned up)
- "Detection engines" section in plain English
- Confidence levels explained in teacher terms

### Implementation
- Tab state toggle, no routing
- Underlined text links across top (Apple Settings style)
- Same AnimatePresence modal pattern

---

## Parallelisation Strategy

**B + C in parallel** (no file overlap):
- Stream B: Walkthrough.tsx (new), AboutModal.tsx, App.tsx
- Stream C: HelpTip.tsx (new), FolderSelection.tsx, DocumentReview.tsx, Completion.tsx (tooltip additions only)

**Then A** (visual refresh across all files, including B+C's new components)

**Then D** (preview endpoint + Completion.tsx cards, depends on A's refreshed layout)
