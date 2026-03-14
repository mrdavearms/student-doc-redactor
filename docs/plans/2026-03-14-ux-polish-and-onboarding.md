# UX Polish & Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-run walkthrough, contextual tooltips, enriched About page, before/after PDF preview, and per-document completion summary cards to the Redaction Tool desktop app.

**Architecture:** Stream A (visual foundation) is COMPLETE. This plan covers Streams B, C, and D. Streams B and C can run in parallel (no file overlap). Stream D depends on B+C being merged.

**Tech Stack:** React 18, TypeScript, Tailwind v4, Framer Motion, Zustand, FastAPI (Python), PyMuPDF

**Design doc:** `docs/plans/2026-03-14-ux-polish-and-onboarding-design.md`

---

## Parallelisation

```
Stream B (Walkthrough + About)     Stream C (Contextual Tooltips)
──────────────────────────────     ──────────────────────────────
B1: Walkthrough.tsx (new)          C1: HelpTip.tsx (new)
B2: AboutModal.tsx (rewrite)       C2: Add tooltips to pages
B3: App.tsx (add walkthrough)      C3: Commit
B4: Commit
         ↘                     ↙
           Merge B + C on test
                  ↓
         Stream D (Preview + Cards)
         ──────────────────────────
         D1: Backend preview endpoint
         D2: PreviewSection.tsx (new)
         D3: DocumentCard.tsx (new)
         D4: Completion.tsx (rewrite)
         D5: Commit
```

**Files touched per stream:**
- **B**: `Walkthrough.tsx` (create), `AboutModal.tsx` (rewrite), `App.tsx` (modify ~5 lines)
- **C**: `HelpTip.tsx` (create), `FolderSelection.tsx` (modify), `DocumentReview.tsx` (modify), `Completion.tsx` (modify ~3 lines)
- **D**: `backend/main.py` (modify), `backend/schemas.py` (modify), `api.ts` (modify), `types.ts` (modify), `PreviewSection.tsx` (create), `DocumentCard.tsx` (create), `Completion.tsx` (rewrite)

---

## Stream B: Walkthrough + About

### Task B1: Create Walkthrough Component

**Files:**
- Create: `desktop/src/components/Walkthrough.tsx`

**Step 1: Create the walkthrough component**

Create `desktop/src/components/Walkthrough.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowRight, ArrowLeft, X, FolderOpen, Eye, ShieldCheck, Lightbulb, Sparkles } from 'lucide-react';

const STORAGE_KEY = 'walkthrough_dismissed';

interface WalkthroughProps {
  forceOpen?: boolean;
  onClose?: () => void;
}

export default function Walkthrough({ forceOpen, onClose }: WalkthroughProps) {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);
  const [dontShow, setDontShow] = useState(false);

  useEffect(() => {
    if (forceOpen) {
      setVisible(true);
      setStep(0);
      return;
    }
    const dismissed = localStorage.getItem(STORAGE_KEY);
    if (!dismissed) setVisible(true);
  }, [forceOpen]);

  const close = useCallback(() => {
    if (dontShow) localStorage.setItem(STORAGE_KEY, 'true');
    setVisible(false);
    onClose?.();
  }, [dontShow, onClose]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!visible) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowRight' && step < 3) setStep((s) => s + 1);
    if (e.key === 'ArrowLeft' && step > 0) setStep((s) => s - 1);
  }, [visible, step, close]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const STEPS = [
    {
      title: 'Protect student privacy in seconds',
      content: (
        <div className="space-y-4">
          <p className="text-sm text-slate-500 leading-relaxed">
            This tool finds and removes personally identifiable information (PII) from student
            documents — names, phone numbers, addresses, emails, and more. It creates redacted
            copies. Your originals are never modified.
          </p>
          <p className="text-sm text-slate-500 leading-relaxed">
            Everything runs locally on your computer. No data is sent anywhere.
          </p>
          {/* Before/after illustration */}
          <div className="grid grid-cols-2 gap-3 mt-4">
            <div className="rounded-lg border border-slate-200 p-4 bg-slate-50/50">
              <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-2">Before</p>
              <div className="space-y-1.5 text-xs text-slate-600">
                <p>Student: <span className="bg-amber-100 px-1 rounded">John Smith</span></p>
                <p>Phone: <span className="bg-amber-100 px-1 rounded">0412 345 678</span></p>
                <p>School: <span className="bg-amber-100 px-1 rounded">Sunrise Primary</span></p>
              </div>
            </div>
            <div className="rounded-lg border border-emerald-200 p-4 bg-emerald-50/30">
              <p className="text-[10px] uppercase tracking-widest text-emerald-500 mb-2">After</p>
              <div className="space-y-1.5 text-xs text-slate-600">
                <p>Student: <span className="bg-slate-800 text-slate-800 px-4 rounded">███</span></p>
                <p>Phone: <span className="bg-slate-800 text-slate-800 px-4 rounded">███</span></p>
                <p>School: <span className="bg-slate-800 text-slate-800 px-4 rounded">███</span></p>
              </div>
            </div>
          </div>
        </div>
      ),
      icon: <Sparkles size={20} className="text-primary-500" />,
    },
    {
      title: 'How it works',
      content: (
        <div className="space-y-4">
          {[
            { icon: <FolderOpen size={16} />, label: 'Choose a folder', desc: 'Select a folder containing student documents — PDFs and Word files.' },
            { icon: <Eye size={16} />, label: 'Review what was found', desc: 'The tool scans every document and shows you what it detected. Accept or reject each item.' },
            { icon: <ShieldCheck size={16} />, label: 'Get redacted copies', desc: 'Redacted documents are saved in a new folder. Originals stay untouched.' },
          ].map((item, i) => (
            <div key={i} className="flex gap-3 items-start">
              <div className="w-8 h-8 rounded-full bg-primary-50 text-primary-600 flex items-center justify-center shrink-0 mt-0.5">
                {item.icon}
              </div>
              <div>
                <p className="text-sm font-medium text-slate-700">{item.label}</p>
                <p className="text-sm text-slate-500 leading-relaxed mt-0.5">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      ),
      icon: <Eye size={20} className="text-primary-500" />,
    },
    {
      title: 'Tips for the best results',
      content: (
        <div className="space-y-3">
          {[
            { text: 'Enter all the names you can — student, parents, siblings, schools, clinics. The more you provide upfront, the more thorough the detection.' },
            { text: 'Unusual name spellings may occasionally be missed — a quick review of the output gives you full confidence.' },
            { text: 'Scanned and handwritten documents are analysed using OCR, which works well on clear scans. Low-quality scans may need a glance.' },
            { text: 'We recommend a quick review of your redacted documents before sharing — the tool does the heavy lifting, the final check is yours.' },
          ].map((item, i) => (
            <div key={i} className="flex gap-2.5 items-start">
              <Lightbulb size={14} className="text-primary-400 shrink-0 mt-0.5" />
              <p className="text-sm text-slate-500 leading-relaxed">{item.text}</p>
            </div>
          ))}
          <div className="mt-4 bg-primary-50 border border-primary-100 rounded-lg px-4 py-3">
            <p className="text-xs text-primary-700 leading-relaxed">
              This tool uses three detection engines working together. It catches the vast majority
              of PII automatically — these tips help you cover the edge cases.
            </p>
          </div>
        </div>
      ),
      icon: <Lightbulb size={20} className="text-primary-500" />,
    },
    {
      title: "You're ready",
      content: (
        <div className="space-y-4 text-center">
          <p className="text-sm text-slate-500 leading-relaxed">
            Select a folder, enter the student's details, and let the tool do the rest.
          </p>
          <div className="flex items-center justify-center gap-2 text-emerald-600">
            <ShieldCheck size={24} />
            <span className="text-lg font-semibold">Let's get started</span>
          </div>
        </div>
      ),
      icon: <ShieldCheck size={20} className="text-emerald-500" />,
    },
  ];

  return (
    <AnimatePresence>
      {visible && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] bg-black/30 backdrop-blur-sm"
            onClick={close}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            className="fixed inset-0 z-[60] flex items-center justify-center p-6 pointer-events-none"
          >
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-[560px] pointer-events-auto overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  {STEPS[step].icon}
                  <h2 className="text-lg font-semibold text-slate-800">{STEPS[step].title}</h2>
                </div>
                <button
                  onClick={close}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Content */}
              <div className="px-6 py-5 min-h-[280px]">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={step}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.15 }}
                  >
                    {STEPS[step].content}
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-slate-100">
                {/* Don't show again (only on last step) */}
                {step === 3 && (
                  <label className="flex items-center gap-2 mb-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={dontShow}
                      onChange={(e) => setDontShow(e.target.checked)}
                      className="w-3.5 h-3.5 rounded border-slate-300 text-primary-600 focus:ring-primary-200"
                    />
                    <span className="text-xs text-slate-400">Don't show this again</span>
                  </label>
                )}

                <div className="flex items-center justify-between">
                  {/* Dot indicators */}
                  <div className="flex gap-1.5">
                    {STEPS.map((_, i) => (
                      <button
                        key={i}
                        onClick={() => setStep(i)}
                        className={`w-2 h-2 rounded-full transition-colors ${
                          i === step ? 'bg-primary-600' : 'bg-slate-200 hover:bg-slate-300'
                        }`}
                      />
                    ))}
                  </div>

                  {/* Navigation */}
                  <div className="flex items-center gap-2">
                    {step > 0 && (
                      <button
                        onClick={() => setStep((s) => s - 1)}
                        className="flex items-center gap-1 px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700 transition-colors"
                      >
                        <ArrowLeft size={14} /> Back
                      </button>
                    )}
                    {step < 3 ? (
                      <>
                        <button
                          onClick={close}
                          className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors"
                        >
                          Skip
                        </button>
                        <button
                          onClick={() => setStep((s) => s + 1)}
                          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium
                                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm transition-all btn-press"
                        >
                          Next <ArrowRight size={14} />
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={close}
                        className="flex items-center gap-1.5 px-5 py-2 rounded-lg text-sm font-medium
                                   bg-primary-600 text-white hover:bg-primary-700 shadow-sm transition-all btn-press"
                      >
                        Start <ArrowRight size={14} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export function resetWalkthrough() {
  localStorage.removeItem(STORAGE_KEY);
}
```

**Step 2: Verify the file compiles**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to Walkthrough.tsx

**Step 3: Commit**

```bash
git add desktop/src/components/Walkthrough.tsx
git commit -m "feat: add first-run walkthrough component with 4-step guided intro"
```

---

### Task B2: Rewrite About Modal with Tabs

**Files:**
- Modify: `desktop/src/components/AboutModal.tsx` (full rewrite)

**Step 1: Rewrite AboutModal with three tabs**

Replace the entire contents of `desktop/src/components/AboutModal.tsx` with:

```tsx
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ExternalLink, ShieldCheck, FolderOpen, Eye, Lightbulb, Zap } from 'lucide-react';
import { resetWalkthrough } from './Walkthrough';

interface AboutModalProps {
  open: boolean;
  onClose: () => void;
  onShowWalkthrough: () => void;
}

type Tab = 'about' | 'how-to-use' | 'features';

const TABS: { key: Tab; label: string }[] = [
  { key: 'about', label: 'About' },
  { key: 'how-to-use', label: 'How to Use' },
  { key: 'features', label: 'Features & Detection' },
];

export default function AboutModal({ open, onClose, onShowWalkthrough }: AboutModalProps) {
  const [activeTab, setActiveTab] = useState<Tab>('about');

  const openLink = (url: string) => {
    window.electronAPI?.openExternal(url);
  };

  const handleShowWalkthrough = () => {
    resetWalkthrough();
    onClose();
    onShowWalkthrough();
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-6 pointer-events-none"
          >
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-hidden pointer-events-auto flex flex-col">
              {/* Header with typographic logo */}
              <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100 shrink-0">
                <div>
                  <h2 className="text-lg tracking-tight">
                    <span className="font-bold text-primary-600">Redact</span>
                    <span className="text-slate-300 mx-1.5 font-light">|</span>
                    <span className="font-light text-slate-400">Tool</span>
                  </h2>
                  <p className="text-[10px] text-slate-400 mt-0.5 tracking-widest uppercase">
                    Protect student privacy
                  </p>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Tabs */}
              <div className="flex gap-6 px-6 pt-4 border-b border-slate-100 shrink-0">
                {TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`pb-3 text-sm transition-colors relative ${
                      activeTab === tab.key
                        ? 'text-primary-600 font-medium'
                        : 'text-slate-400 hover:text-slate-600'
                    }`}
                  >
                    {tab.label}
                    {activeTab === tab.key && (
                      <motion.div
                        layoutId="aboutTab"
                        className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary-600 rounded-full"
                      />
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-y-auto px-6 py-5">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.12 }}
                  >
                    {activeTab === 'about' && <TabAbout openLink={openLink} />}
                    {activeTab === 'how-to-use' && <TabHowToUse onShowWalkthrough={handleShowWalkthrough} />}
                    {activeTab === 'features' && <TabFeatures />}
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-slate-100 text-center shrink-0">
                <p className="text-[10px] text-slate-300">
                  © 2026 David Armstrong · Built for Australian educators
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ── Tab Content ──────────────────────────────────────────────────── */

function TabAbout({ openLink }: { openLink: (url: string) => void }) {
  return (
    <div className="space-y-5">
      <section>
        <p className="text-sm text-slate-600">
          Developed by <span className="font-medium text-slate-800">David Armstrong</span>
        </p>
        <button
          onClick={() => openLink('https://github.com/mrdavearms/student-doc-redactor')}
          className="flex items-center gap-1.5 mt-1.5 text-xs text-primary-500 hover:text-primary-600 transition-colors"
        >
          <ExternalLink size={11} /> View on GitHub
        </button>
      </section>
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">What This App Does</h3>
        <p className="text-sm text-slate-500 leading-relaxed">
          Finds and removes personally identifiable information from student assessment
          documents — names, phone numbers, emails, addresses, and more. Built for teachers
          and school psychologists who need to share reports while protecting student privacy.
          All processing happens locally on your computer.
        </p>
      </section>
      <section>
        <p className="text-[10px] text-slate-400 uppercase tracking-widest">v0.1.0</p>
      </section>
    </div>
  );
}

function TabHowToUse({ onShowWalkthrough }: { onShowWalkthrough: () => void }) {
  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Getting Started</h3>
        <div className="space-y-3">
          {[
            { icon: <FolderOpen size={14} />, step: '1', text: 'Select a folder containing student documents (PDFs and Word files) and enter the student\'s name.' },
            { icon: <Eye size={14} />, step: '2', text: 'Enter parent, family, and organisation names — the more you provide, the more thorough the detection.' },
            { icon: <ShieldCheck size={14} />, step: '3', text: 'Review detected PII, accept or reject each item, then create redacted copies in a new folder.' },
          ].map((item) => (
            <div key={item.step} className="flex gap-3 items-start">
              <div className="w-6 h-6 rounded-full bg-primary-50 text-primary-600 flex items-center justify-center text-xs font-semibold shrink-0 mt-0.5">
                {item.step}
              </div>
              <p className="text-sm text-slate-500 leading-relaxed">{item.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-3 flex items-center gap-1.5">
          <Lightbulb size={14} className="text-primary-500" />
          Tips for the Best Results
        </h3>
        <div className="space-y-2">
          {[
            'Enter all the names you can — student, parents, siblings, schools, clinics.',
            'Unusual name spellings may occasionally be missed — a quick review of the output gives you full confidence.',
            'Scanned and handwritten documents are analysed, though low-quality scans may need a glance.',
            'We recommend a quick review of your redacted documents before sharing.',
          ].map((tip, i) => (
            <div key={i} className="flex gap-2 items-start">
              <Lightbulb size={12} className="text-primary-400 shrink-0 mt-0.5" />
              <p className="text-sm text-slate-500 leading-relaxed">{tip}</p>
            </div>
          ))}
        </div>
      </section>

      <button
        onClick={onShowWalkthrough}
        className="text-xs text-primary-500 hover:text-primary-600 transition-colors"
      >
        Show welcome walkthrough again
      </button>
    </div>
  );
}

function TabFeatures() {
  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">Features</h3>
        <ul className="space-y-1.5 text-sm text-slate-500">
          {[
            'Detects names, phone numbers, emails, addresses, Medicare numbers, dates of birth, student IDs, and more',
            'Redacts both text-layer and scanned/OCR pages in PDFs',
            'Automatic Word to PDF conversion',
            'Header/footer zone blanking for school letterheads',
            'Signature image detection and removal',
            'PII removed from output filenames',
            'Full audit log of every redaction',
            '100% local processing — no data leaves your machine',
          ].map((f, i) => (
            <li key={i} className="flex gap-2 items-start">
              <span className="text-emerald-500 mt-1 shrink-0">•</span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-1.5">
          <Zap size={14} className="text-primary-500" />
          Detection Engines
        </h3>
        <p className="text-sm text-slate-500 leading-relaxed">
          This tool uses three detection methods working together — pattern matching for
          structured data like phone numbers and emails, named entity recognition for names
          and addresses, and zero-shot AI detection for unusual PII formats. Each item is
          checked by multiple engines for reliability.
        </p>
      </section>

      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">Confidence Levels</h3>
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
            <span className="text-slate-500"><span className="font-medium text-slate-700">High</span> — the tool is very confident this is personal information</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
            <span className="text-slate-500"><span className="font-medium text-slate-700">Medium</span> — likely PII, but worth a quick check</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-rose-500 shrink-0" />
            <span className="text-slate-500"><span className="font-medium text-slate-700">Low</span> — possible match, review recommended</span>
          </div>
        </div>
      </section>
    </div>
  );
}
```

**Step 2: Verify compilation**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to AboutModal.tsx

**Step 3: Commit**

```bash
git add desktop/src/components/AboutModal.tsx
git commit -m "feat: rewrite About modal with three tabs (About, How to Use, Features)"
```

---

### Task B3: Wire Walkthrough into App + Update Sidebar Props

**Files:**
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/components/Sidebar.tsx`

**Step 1: Update Sidebar to pass `onShowWalkthrough` to AboutModal**

In `desktop/src/components/Sidebar.tsx`, add a `walkthroughOpen` state and pass `onShowWalkthrough` to AboutModal:

At line 19, add:
```tsx
const [walkthroughOpen, setWalkthroughOpen] = useState(false);
```

Replace the `AboutModal` render at line 118:
```tsx
<AboutModal
  open={aboutOpen}
  onClose={() => setAboutOpen(false)}
  onShowWalkthrough={() => {
    setAboutOpen(false);
    setWalkthroughOpen(true);
  }}
/>
```

Add after the AboutModal (before closing `</aside>`):
```tsx
{walkthroughOpen && (
  <Walkthrough forceOpen onClose={() => setWalkthroughOpen(false)} />
)}
```

Add the import at the top:
```tsx
import Walkthrough from './Walkthrough';
```

**Step 2: Add Walkthrough to App.tsx for first-run**

In `desktop/src/App.tsx`, add the Walkthrough import and render it inside the Layout, before the error toast:

Add import:
```tsx
import Walkthrough from './components/Walkthrough';
```

Add before the `{error && (` block:
```tsx
<Walkthrough />
```

**Step 3: Verify compilation and test**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 4: Commit**

```bash
git add desktop/src/App.tsx desktop/src/components/Sidebar.tsx
git commit -m "feat: wire walkthrough into App (first-run) and Sidebar (re-show from About)"
```

---

## Stream C: Contextual Tooltips

### Task C1: Create HelpTip Component

**Files:**
- Create: `desktop/src/components/HelpTip.tsx`

**Step 1: Create the HelpTip component**

Create `desktop/src/components/HelpTip.tsx`:

```tsx
import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle } from 'lucide-react';

interface HelpTipProps {
  text: string;
  className?: string;
}

export default function HelpTip({ text, className = '' }: HelpTipProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-0.5 rounded-full text-slate-300 hover:text-slate-500 transition-colors"
        aria-label="Help"
      >
        <HelpCircle size={14} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 top-full mt-1.5 z-40 w-[280px] bg-white rounded-lg shadow-lg
                       border border-slate-200 px-3.5 py-3"
          >
            <p className="text-xs text-slate-500 leading-relaxed">{text}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

**Step 2: Verify compilation**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add desktop/src/components/HelpTip.tsx
git commit -m "feat: add reusable HelpTip popover component for contextual help"
```

---

### Task C2: Add Tooltips to Page Components

**Files:**
- Modify: `desktop/src/pages/FolderSelection.tsx`
- Modify: `desktop/src/pages/DocumentReview.tsx`
- Modify: `desktop/src/pages/Completion.tsx`

**Step 1: Add tooltips to FolderSelection.tsx**

Add import at top:
```tsx
import HelpTip from '../components/HelpTip';
```

Add HelpTip next to each label. For each label line, add a `<HelpTip>` inline. The pattern for each field:

After the label text `Student full name <span...>*</span>`, on line 109, change the label to:
```tsx
<label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
  Student full name <span className="text-red-400">*</span>
  <HelpTip text="Enter the student's full name as it appears in their documents. First and last name. The tool will also detect variations like first-name-only and surname-only." />
</label>
```

For Parent/Guardian names label (line 123-125):
```tsx
<label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
  <Users size={14} className="text-slate-400" />
  Parent/Guardian names
  <HelpTip text="Include anyone whose name might appear in the documents — referral letters, consent forms, and reports often mention parents by name." />
</label>
```

For Other family members label (line 139-141):
```tsx
<label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
  <Users size={14} className="text-slate-400" />
  Other family members
  <HelpTip text="Siblings or other family members sometimes appear in assessment reports, especially in background history sections." />
</label>
```

For Organisation names label (line 156-158):
```tsx
<label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
  <Building size={14} className="text-slate-400" />
  Organisation names
  <HelpTip text="Schools, clinics, hospitals, therapy centres — any organisation name that could identify the student's location or service providers." />
</label>
```

For Redact headers & footers checkbox label (line 179-181):
```tsx
<span className="text-sm text-slate-600 flex items-center gap-1.5">
  Redact headers & footers (blanks top/bottom of every page — removes letterheads and addresses)
  <HelpTip text="Blanks the top and bottom of every page. Useful for removing school letterheads, clinic logos, and addresses that appear in page margins." />
</span>
```

**Step 2: Add tooltip to DocumentReview confidence badge**

Add import at top of `DocumentReview.tsx`:
```tsx
import HelpTip from '../components/HelpTip';
```

After the `{selectedCount}/{matches.length} selected` span (line 97), add:
```tsx
<HelpTip text="High confidence means the tool is very sure this is personal information. Medium means it's likely but worth checking. Items are pre-selected for redaction — uncheck any you want to keep." />
```

**Step 3: Add tooltips to Completion.tsx**

Add import at top of `Completion.tsx`:
```tsx
import HelpTip from '../components/HelpTip';
```

After the verification failures heading (line 64-66), change to:
```tsx
<div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
  <XCircle size={16} />
  {r.verification_failures.length} verification failure(s)
  <HelpTip text="The tool re-checks each redacted document to confirm the text was fully removed. A failure here means the original text may still be visible — open the file and check manually." />
</div>
```

After the Redaction Log button text (line 156), change to:
```tsx
<span className="flex-1 text-left font-medium flex items-center gap-1.5">
  Redaction Log
  <HelpTip text="A detailed record of every item that was redacted, which document it came from, and which detection engine found it. Useful for your own records." />
</span>
```

**Step 4: Verify compilation**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 5: Commit**

```bash
git add desktop/src/components/HelpTip.tsx desktop/src/pages/FolderSelection.tsx desktop/src/pages/DocumentReview.tsx desktop/src/pages/Completion.tsx
git commit -m "feat: add contextual help tooltips to Folder Selection, Document Review, and Completion screens"
```

---

## Stream D: Before/After Preview + Summary Cards

> **Depends on:** Streams B + C merged into `test`

### Task D1: Backend Preview Endpoint

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/schemas.py`

**Step 1: Add schema for preview**

Add to `backend/schemas.py` before the `OpenFolderRequest` class:

```python
class PreviewRequest(BaseModel):
    pdf_path: str
    page_num: int  # 0-indexed


class PreviewResponse(BaseModel):
    image_base64: str
    total_pages: int
    page_num: int
```

**Step 2: Add preview endpoint to backend/main.py**

Add these imports at the top of `backend/main.py`:
```python
import base64
```

Add the PreviewRequest/PreviewResponse imports to the schema import block:
```python
from backend.schemas import (
    ...,
    PreviewRequest,
    PreviewResponse,
)
```

Add endpoint before the Utility section:

```python
# ── Preview ──────────────────────────────────────────────────────────────

@app.post("/api/preview", response_model=PreviewResponse)
def preview_page(req: PreviewRequest):
    """Render a single PDF page at 150 DPI and return as base64 PNG."""
    import fitz

    pdf_path = Path(req.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {req.pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot open PDF: {e}")

    if req.page_num < 0 or req.page_num >= len(doc):
        doc.close()
        raise HTTPException(
            status_code=400,
            detail=f"Page {req.page_num} out of range (0-{len(doc) - 1})",
        )

    page = doc[req.page_num]
    # 150 DPI: multiply by 150/72
    mat = fitz.Matrix(150 / 72, 150 / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    total = len(doc)
    doc.close()

    return PreviewResponse(
        image_base64=base64.b64encode(img_bytes).decode("ascii"),
        total_pages=total,
        page_num=req.page_num,
    )
```

**Step 3: Verify backend starts**

Run: `cd "/Users/davidarmstrong/Antigravity/redaction tool" && source venv/bin/activate && python -c "from backend.main import app; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add backend/main.py backend/schemas.py
git commit -m "feat: add /api/preview endpoint for rendering PDF pages at 150 DPI"
```

---

### Task D2: Frontend API + Types for Preview

**Files:**
- Modify: `desktop/src/types.ts`
- Modify: `desktop/src/api.ts`

**Step 1: Add preview types**

Add to `desktop/src/types.ts`:

```ts
export interface PreviewResponse {
  image_base64: string;
  total_pages: number;
  page_num: number;
}
```

**Step 2: Add preview API method**

Add to `desktop/src/api.ts` inside the `api` object:

```ts
previewPage: (pdf_path: string, page_num: number) =>
  request<import('./types').PreviewResponse>('/api/preview', {
    method: 'POST',
    body: JSON.stringify({ pdf_path, page_num }),
  }),
```

**Step 3: Commit**

```bash
git add desktop/src/types.ts desktop/src/api.ts
git commit -m "feat: add preview API client and types"
```

---

### Task D3: Create PreviewSection Component

**Files:**
- Create: `desktop/src/components/PreviewSection.tsx`

**Step 1: Create the preview component**

Create `desktop/src/components/PreviewSection.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Eye } from 'lucide-react';
import { api } from '../api';

interface PreviewSectionProps {
  /** Array of { originalPath, redactedPath, filename } */
  documents: { originalPath: string; redactedPath: string; filename: string }[];
}

export default function PreviewSection({ documents }: PreviewSectionProps) {
  const [expanded, setExpanded] = useState(true);
  const [docIndex, setDocIndex] = useState(0);
  const [pageNum, setPageNum] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [originalImg, setOriginalImg] = useState<string | null>(null);
  const [redactedImg, setRedactedImg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const doc = documents[docIndex];

  const loadPage = useCallback(async (dIdx: number, pNum: number) => {
    const d = documents[dIdx];
    if (!d) return;
    setLoading(true);
    setOriginalImg(null);
    setRedactedImg(null);
    try {
      const [orig, redacted] = await Promise.all([
        api.previewPage(d.originalPath, pNum),
        api.previewPage(d.redactedPath, pNum),
      ]);
      setOriginalImg(`data:image/png;base64,${orig.image_base64}`);
      setRedactedImg(`data:image/png;base64,${redacted.image_base64}`);
      setTotalPages(orig.total_pages);
    } catch {
      // Preview failed — not critical
    } finally {
      setLoading(false);
    }
  }, [documents]);

  useEffect(() => {
    if (expanded && documents.length > 0) {
      loadPage(docIndex, pageNum);
    }
  }, [expanded, docIndex, pageNum, loadPage, documents.length]);

  if (documents.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
      >
        <Eye size={14} className="text-primary-500" />
        <span className="flex-1 text-left font-medium">Before & After Preview</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 space-y-4">
              {/* Document tabs */}
              <div className="flex gap-1 overflow-x-auto pb-1">
                {documents.map((d, i) => (
                  <button
                    key={d.filename}
                    onClick={() => { setDocIndex(i); setPageNum(0); }}
                    className={`px-3 py-1.5 text-xs rounded-md whitespace-nowrap shrink-0 transition-colors ${
                      i === docIndex
                        ? 'bg-primary-50 text-primary-700 font-medium'
                        : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {d.filename}
                  </button>
                ))}
              </div>

              {/* Split view */}
              <div className="grid grid-cols-2 gap-3" style={{ maxHeight: '500px' }}>
                <div className="border border-slate-200 rounded-lg overflow-hidden">
                  <div className="bg-slate-50 px-3 py-1.5 text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-200">
                    Original
                  </div>
                  <div className="p-2 flex items-center justify-center min-h-[200px]">
                    {loading ? (
                      <div className="skeleton w-full h-48" />
                    ) : originalImg ? (
                      <img src={originalImg} alt="Original page" className="max-w-full max-h-[440px] object-contain" />
                    ) : (
                      <p className="text-xs text-slate-300">No preview</p>
                    )}
                  </div>
                </div>
                <div className="border border-emerald-200 rounded-lg overflow-hidden">
                  <div className="bg-emerald-50/50 px-3 py-1.5 text-[10px] uppercase tracking-widest text-emerald-500 border-b border-emerald-200">
                    Redacted
                  </div>
                  <div className="p-2 flex items-center justify-center min-h-[200px]">
                    {loading ? (
                      <div className="skeleton w-full h-48" />
                    ) : redactedImg ? (
                      <img src={redactedImg} alt="Redacted page" className="max-w-full max-h-[440px] object-contain" />
                    ) : (
                      <p className="text-xs text-slate-300">No preview</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Page navigation */}
              {totalPages > 0 && (
                <div className="flex items-center justify-center gap-3">
                  <button
                    onClick={() => setPageNum((p) => Math.max(0, p - 1))}
                    disabled={pageNum === 0}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 disabled:opacity-30 transition-colors"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-xs text-slate-500">
                    Page {pageNum + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPageNum((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={pageNum >= totalPages - 1}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 disabled:opacity-30 transition-colors"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
```

**Step 2: Commit**

```bash
git add desktop/src/components/PreviewSection.tsx
git commit -m "feat: add before/after PDF preview component with split view"
```

---

### Task D4: Create DocumentCard Component

**Files:**
- Create: `desktop/src/components/DocumentCard.tsx`

**Step 1: Create the document summary card**

Create `desktop/src/components/DocumentCard.tsx`:

```tsx
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle, AlertTriangle, XCircle, ArrowRight, ChevronDown, ChevronUp,
} from 'lucide-react';
import type { DocumentResult } from '../types';

interface DocumentCardProps {
  result: DocumentResult;
  /** Category counts for this document: { "Student name": 3, "Phone": 2 } */
  categoryCounts: Record<string, number>;
  /** Whether any medium-confidence items were included */
  hasMediumConfidence: boolean;
}

export default function DocumentCard({ result, categoryCounts, hasMediumConfidence }: DocumentCardProps) {
  const [expanded, setExpanded] = useState(false);

  const inputName = result.document_name;
  const outputName = result.output_path ? result.output_path.split('/').pop() || '' : '';
  const renamed = inputName !== outputName;
  const hasWarnings = result.ocr_warnings.length > 0;
  const hasFails = result.verification_failures.length > 0;

  const StatusIcon = hasFails
    ? () => <XCircle size={16} className="text-rose-500" />
    : hasWarnings
    ? () => <AlertTriangle size={16} className="text-amber-500" />
    : () => <CheckCircle size={16} className="text-emerald-500" />;

  const categoryEntries = Object.entries(categoryCounts).sort(([, a], [, b]) => b - a);

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-slate-50/50 transition-colors"
      >
        <StatusIcon />

        <div className="flex-1 min-w-0">
          {/* Filename */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-600 truncate">{inputName}</span>
            {renamed && (
              <>
                <ArrowRight size={10} className="text-slate-300 shrink-0" />
                <span className="text-primary-600 font-medium truncate">{outputName}</span>
              </>
            )}
          </div>

          {/* Category pills */}
          {categoryEntries.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {categoryEntries.map(([cat, count]) => (
                <span
                  key={cat}
                  className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500"
                >
                  {count} {cat.toLowerCase()}{count > 1 ? 's' : ''}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Confidence dot */}
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
          hasFails ? 'bg-rose-500' : hasMediumConfidence ? 'bg-amber-500' : 'bg-emerald-500'
        }`} />

        {expanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-4 border-t border-slate-100 pt-3">
              {/* Per-item breakdown — category + location only, never actual PII text */}
              <p className="text-[10px] text-slate-400 uppercase tracking-widest mb-2">
                {result.items_redacted} item{result.items_redacted !== 1 ? 's' : ''} redacted
              </p>

              {categoryEntries.length > 0 ? (
                <div className="space-y-1">
                  {categoryEntries.map(([cat, count]) => (
                    <div key={cat} className="flex justify-between text-xs">
                      <span className="text-slate-500">{cat}</span>
                      <span className="text-slate-400">{count} removed</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400">No items redacted from this document.</p>
              )}

              {hasFails && (
                <div className="mt-3 bg-rose-50 rounded-lg px-3 py-2">
                  <p className="text-xs text-rose-600">Verification failed — review this document manually.</p>
                </div>
              )}

              {hasWarnings && !hasFails && (
                <div className="mt-3 bg-amber-50 rounded-lg px-3 py-2">
                  <p className="text-xs text-amber-600">Contains scanned pages — a quick manual check is recommended.</p>
                </div>
              )}

              {renamed && (
                <p className="text-[10px] text-primary-500 mt-2">
                  Filename was renamed to remove PII.
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add desktop/src/components/DocumentCard.tsx
git commit -m "feat: add per-document summary card component for completion screen"
```

---

### Task D5: Rewrite Completion Screen

**Files:**
- Modify: `desktop/src/pages/Completion.tsx` (full rewrite)

**Step 1: Rewrite Completion.tsx**

Replace the entire contents of `desktop/src/pages/Completion.tsx` with the new version that uses DocumentCard + PreviewSection. The key changes:

1. Replace the "Filename audit" section with DocumentCard components
2. Add PreviewSection between the success banner and output folder
3. Collapse the redaction log by default
4. Build `categoryCounts` per document from `detectionResults` + `userSelections` in the store
5. Need to access `detectionResults` and `userSelections` from the store (currently Completion only uses `redactionResults`)

The rewrite needs to:
- Import `DocumentCard` and `PreviewSection`
- Import `HelpTip` (from Stream C — must be merged first)
- Pull `detectionResults` and `userSelections` from the store to compute per-doc category counts
- Build preview document list from `document_results` (matching original path to redacted output_path)
- Replace the filename audit section with mapped `DocumentCard` components

**Important:** The `detectionResults` are still in the Zustand store at this point (user hasn't reset yet). Use them to compute per-document category breakdowns by cross-referencing `userSelections` and `document_results`.

Replace entire file with:

```tsx
import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  CheckCircle, AlertTriangle, XCircle, FolderOpen, FileText, RotateCcw,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import HelpTip from '../components/HelpTip';
import DocumentCard from '../components/DocumentCard';
import PreviewSection from '../components/PreviewSection';

export default function Completion() {
  const { redactionResults, detectionResults, userSelections, reset } = useStore();
  const [logExpanded, setLogExpanded] = useState(false);

  // Build per-document category counts from detection results
  const docMeta = useMemo(() => {
    if (!redactionResults || !detectionResults) return new Map<string, { counts: Record<string, number>; hasMedium: boolean }>();

    const meta = new Map<string, { counts: Record<string, number>; hasMedium: boolean }>();

    for (const doc of detectionResults.documents) {
      const counts: Record<string, number> = {};
      let hasMedium = false;
      doc.matches.forEach((match, idx) => {
        const key = `${doc.path}_${idx}`;
        if (userSelections[key]) {
          counts[match.category] = (counts[match.category] || 0) + 1;
          if (match.confidence_label === 'medium' || match.confidence_label === 'low') {
            hasMedium = true;
          }
        }
      });
      // Map by filename to match against document_results
      const filename = doc.path.split('/').pop() || doc.path;
      meta.set(filename, { counts, hasMedium });
    }
    return meta;
  }, [redactionResults, detectionResults, userSelections]);

  // Build preview document list
  const previewDocs = useMemo(() => {
    if (!redactionResults) return [];
    return redactionResults.document_results
      .filter((d) => d.success && d.output_path)
      .map((d) => {
        // Find original path from detection results
        const origDoc = detectionResults?.documents.find(
          (det) => det.filename === d.document_name || det.path.endsWith(d.document_name)
        );
        return {
          originalPath: origDoc?.path || '',
          redactedPath: d.output_path!,
          filename: d.document_name,
        };
      })
      .filter((d) => d.originalPath);
  }, [redactionResults, detectionResults]);

  if (!redactionResults) {
    return (
      <div className="text-center py-12 text-slate-500">
        Processing not complete.
      </div>
    );
  }

  const r = redactionResults;
  const hasFailures = r.verification_failures.length > 0;
  const hasOcrWarnings = r.ocr_warnings.length > 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Processing Complete</h2>
      </div>

      {/* Success banner */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: 'spring', stiffness: 300, damping: 25 }}
        className={`
          rounded-xl p-6 text-center
          ${hasFailures ? 'bg-amber-50 border border-amber-200' : 'bg-emerald-50 border border-emerald-200'}
        `}
      >
        {hasFailures ? (
          <AlertTriangle size={40} className="mx-auto text-amber-500 mb-2" />
        ) : (
          <CheckCircle size={40} className="mx-auto text-emerald-500 mb-2" />
        )}
        <h3 className={`text-lg font-semibold ${hasFailures ? 'text-amber-800' : 'text-emerald-800'}`}>
          {hasFailures
            ? 'Completed with warnings'
            : `All ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} redacted successfully`}
        </h3>
        <p className="text-sm mt-1 text-slate-500">
          {r.successfully_redacted} of {r.total_documents} documents redacted
        </p>
      </motion.div>

      {/* Verification failures */}
      {hasFailures && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <XCircle size={16} />
            {r.verification_failures.length} verification failure(s)
            <HelpTip text="The tool re-checks each redacted document to confirm the text was fully removed. A failure here means the original text may still be visible — open the file and check manually." />
          </div>
          <p className="text-xs text-red-600 mb-3">
            The original text may still be present in these files. Review the log and check manually.
          </p>
          {r.verification_failures.map((f, i) => (
            <p key={i} className="text-xs text-red-500 py-0.5">
              {f.filename}: {f.message}
            </p>
          ))}
        </motion.div>
      )}

      {/* OCR warnings */}
      {hasOcrWarnings && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-amber-50 border border-amber-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-700 mb-2">
            <AlertTriangle size={16} />
            Items on scanned pages — manual review recommended
          </div>
          {r.ocr_warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-600 py-0.5">
              {w.filename}: {w.count} item(s) on image-only pages
            </p>
          ))}
        </motion.div>
      )}

      {/* Per-document summary cards */}
      {r.document_results && r.document_results.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="space-y-2"
        >
          <h3 className="text-sm font-medium text-slate-600 mb-1">Document Summary</h3>
          {r.document_results.map((d, i) => {
            const meta = docMeta.get(d.document_name) || { counts: {}, hasMedium: false };
            return (
              <DocumentCard
                key={i}
                result={d}
                categoryCounts={meta.counts}
                hasMediumConfidence={meta.hasMedium}
              />
            );
          })}
        </motion.section>
      )}

      {/* Before/After Preview */}
      {previewDocs.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <PreviewSection documents={previewDocs} />
        </motion.div>
      )}

      {/* Output folder */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <h3 className="text-sm font-medium text-slate-600 mb-2">Redacted Documents</h3>
        <div className="flex items-center gap-3">
          <code className="text-xs bg-slate-50 px-3 py-2 rounded-lg text-slate-500 flex-1 overflow-x-auto">
            {r.redacted_folder}
          </code>
          <button
            onClick={() => api.openFolder(r.redacted_folder)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors shrink-0 btn-press"
          >
            <FolderOpen size={14} /> Open Folder
          </button>
        </div>
      </motion.section>

      {/* Redaction log (collapsed by default) */}
      <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <button
          onClick={() => setLogExpanded(!logExpanded)}
          className="w-full flex items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
        >
          <FileText size={14} className="text-slate-400" />
          <span className="flex-1 text-left font-medium flex items-center gap-1.5">
            Redaction Log
            <HelpTip text="A detailed record of every item that was redacted, which document it came from, and which detection engine found it. Useful for your own records." />
          </span>
          {logExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {logExpanded && (
          <div className="px-5 pb-4">
            <pre className="text-[11px] text-slate-500 bg-slate-50 rounded-lg p-4 overflow-x-auto max-h-64 overflow-y-auto leading-relaxed whitespace-pre-wrap">
              {r.log_content}
            </pre>
          </div>
        )}
      </section>

      {/* Process another */}
      <div className="flex justify-center pt-4">
        <button
          onClick={reset}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <RotateCcw size={16} /> Process Another Folder
        </button>
      </div>
    </div>
  );
}
```

**Step 2: Verify compilation**

Run: `cd desktop && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Build check**

Run: `cd desktop && npx vite build 2>&1 | tail -5`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add desktop/src/pages/Completion.tsx desktop/src/components/PreviewSection.tsx desktop/src/components/DocumentCard.tsx
git commit -m "feat: rewrite Completion screen with summary cards and before/after preview"
```

---

## Execution Order Summary

1. **Stream B** (Tasks B1–B3): Walkthrough + About — can start immediately
2. **Stream C** (Tasks C1–C2): Tooltips — can start immediately, runs in parallel with B
3. **Merge B + C** on `test` branch, resolve any conflicts
4. **Stream D** (Tasks D1–D5): Preview + Cards — start after B+C merge
5. **Final verification**: `cd desktop && npx tsc --noEmit && npx vite build`
