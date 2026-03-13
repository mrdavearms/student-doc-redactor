import { motion, AnimatePresence } from 'framer-motion';
import { X, ExternalLink, ShieldCheck, FileText, Eye, AlertTriangle } from 'lucide-react';

interface AboutModalProps {
  open: boolean;
  onClose: () => void;
}

export default function AboutModal({ open, onClose }: AboutModalProps) {
  const openLink = (url: string) => {
    window.electronAPI?.openExternal(url);
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-6 pointer-events-none"
          >
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-y-auto pointer-events-auto">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
                <div>
                  <h2 className="text-lg font-semibold text-slate-800">Redaction Tool</h2>
                  <p className="text-xs text-slate-400 mt-0.5">v0.1.0</p>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Content */}
              <div className="px-6 py-5 space-y-5">

                {/* Developer */}
                <section>
                  <p className="text-sm text-slate-600">
                    Developed by <span className="font-medium text-slate-800">David Armstrong</span>
                  </p>
                  <button
                    onClick={() => openLink('https://github.com/mrdavearms/student-doc-redactor')}
                    className="flex items-center gap-1.5 mt-1.5 text-xs text-primary-500 hover:text-primary-600 transition-colors"
                  >
                    <ExternalLink size={11} />
                    View on GitHub
                  </button>
                </section>

                {/* What it does */}
                <section>
                  <h3 className="text-sm font-medium text-slate-700 mb-2">What This App Does</h3>
                  <p className="text-sm text-slate-500 leading-relaxed">
                    Bulk-redacts personally identifiable information (PII) from student assessment
                    PDFs and Word documents. Built for Australian teachers and school psychologists
                    who need to share reports while protecting student privacy.
                  </p>
                </section>

                {/* How to use */}
                <section>
                  <h3 className="text-sm font-medium text-slate-700 mb-2">How to Use</h3>
                  <div className="space-y-2">
                    {[
                      { icon: <FileText size={14} />, step: '1', text: 'Select a folder containing student documents (PDFs and Word files).' },
                      { icon: <Eye size={14} />, step: '2', text: 'Enter the student name and any parent, family, or organisation names to detect.' },
                      { icon: <ShieldCheck size={14} />, step: '3', text: 'Review detected PII, accept or reject each item, then create redacted copies.' },
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

                {/* Features */}
                <section>
                  <h3 className="text-sm font-medium text-slate-700 mb-2">Features</h3>
                  <ul className="space-y-1.5 text-sm text-slate-500">
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Multi-engine PII detection (regex, Presidio NER, GLiNER zero-shot NER)</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Detects names, phone numbers, emails, addresses, Medicare numbers, dates of birth, student IDs, and more</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Redacts both text-layer and scanned/OCR pages in PDFs</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Automatic Word to PDF conversion via LibreOffice</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Header/footer zone blanking for school letterheads</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Signature image detection and removal</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>PII removed from output filenames</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>Full audit log of every redaction</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-emerald-500 mt-1 shrink-0">•</span>
                      <span>100% local processing — no data leaves your machine</span>
                    </li>
                  </ul>
                </section>

                {/* Limitations */}
                <section>
                  <h3 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-1.5">
                    <AlertTriangle size={14} className="text-amber-500" />
                    Limitations
                  </h3>
                  <ul className="space-y-1.5 text-sm text-slate-500">
                    <li className="flex gap-2 items-start">
                      <span className="text-amber-500 mt-1 shrink-0">•</span>
                      <span>OCR accuracy depends on scan quality — low-DPI or blurry scans may miss words</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-amber-500 mt-1 shrink-0">•</span>
                      <span>No fuzzy name matching yet — misspelled names may not be detected</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-amber-500 mt-1 shrink-0">•</span>
                      <span>Requires LibreOffice and Tesseract OCR installed separately</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-amber-500 mt-1 shrink-0">•</span>
                      <span>macOS only (Apple Silicon) in this version</span>
                    </li>
                    <li className="flex gap-2 items-start">
                      <span className="text-amber-500 mt-1 shrink-0">•</span>
                      <span>Always manually review redacted documents before sharing</span>
                    </li>
                  </ul>
                </section>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-slate-100 text-center">
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
