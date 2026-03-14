import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ExternalLink, ShieldCheck, FolderOpen, Eye, Lightbulb, Zap, RefreshCw } from 'lucide-react';
import { resetWalkthrough } from './Walkthrough';
import type { UpdateState } from '../hooks/useUpdater';

interface AboutModalProps {
  open: boolean;
  onClose: () => void;
  onShowWalkthrough: () => void;
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}

type Tab = 'about' | 'how-to-use' | 'features';

const TABS: { key: Tab; label: string }[] = [
  { key: 'about', label: 'About' },
  { key: 'how-to-use', label: 'How to Use' },
  { key: 'features', label: 'Features & Detection' },
];

export default function AboutModal({ open, onClose, onShowWalkthrough, updateState, onCheckForUpdates }: AboutModalProps) {
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
                    {activeTab === 'about' && (
                      <TabAbout
                        openLink={openLink}
                        updateState={updateState}
                        onCheckForUpdates={onCheckForUpdates}
                      />
                    )}
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

function TabAbout({ openLink, updateState, onCheckForUpdates }: {
  openLink: (url: string) => void;
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}) {
  const [appVersion, setAppVersion] = useState<string>('');

  useEffect(() => {
    window.electronAPI?.getAppVersion().then(setAppVersion).catch(() => {});
  }, []);

  const checkButtonLabel = () => {
    switch (updateState.status) {
      case 'checking':    return 'Checking…';
      case 'up-to-date':  return 'You\'re up to date ✓';
      case 'downloading': return `Downloading… ${updateState.percent > 0 ? updateState.percent + '%' : ''}`;
      case 'ready':       return 'Update ready — see banner above';
      case 'error':       return 'Check failed — try again';
      default:            return 'Check for Updates';
    }
  };

  const checkButtonDisabled =
    updateState.status === 'checking' ||
    updateState.status === 'downloading' ||
    updateState.status === 'ready';

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
      <section className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">
            Version <span className="font-medium text-slate-700">{appVersion || '—'}</span>
          </p>
          <button
            onClick={onCheckForUpdates}
            disabled={checkButtonDisabled}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium
                       bg-primary-600 text-white hover:bg-primary-700 disabled:bg-slate-200
                       disabled:text-slate-400 disabled:cursor-not-allowed shadow-sm transition-all btn-press"
          >
            <RefreshCw size={13} className={updateState.status === 'checking' ? 'animate-spin' : ''} />
            {checkButtonLabel()}
          </button>
        </div>
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
