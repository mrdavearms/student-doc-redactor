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
