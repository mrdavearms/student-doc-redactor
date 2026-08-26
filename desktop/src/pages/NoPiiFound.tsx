import { useState } from 'react';
import { motion } from 'framer-motion';
import { ShieldCheck, RotateCcw, ArrowLeft, ArrowRight, AlertTriangle, Copy } from 'lucide-react';
import { useStore } from '../store';

export default function NoPiiFound() {
  const detectionResults = useStore((s) => s.detectionResults);
  const workflowMode = useStore((s) => s.workflowMode);
  const inputMode = useStore((s) => s.inputMode);
  const pastedText = useStore((s) => s.pastedText);
  const navigateTo = useStore((s) => s.navigateTo);
  const [copied, setCopied] = useState(false);

  if (!detectionResults) return null;

  const docCount = detectionResults.documents.length;
  const isDeidentify = workflowMode === 'deidentify';
  const isPaste = inputMode === 'paste';

  const handleBackToNames = () => {
    navigateTo('folder_selection');
  };

  // reset() already lands on mode_selection — navigating on top of it would
  // undo that and silently keep the previous pathway.
  const handleProcessAnother = () => {
    useStore.getState().reset();
  };

  // A document that turns up nothing is fine as-is — the original is still
  // right there. A paste has no original on disk to fall back to, so "nothing
  // found" needs its own way out: the pasted text itself, ready to copy back.
  if (isPaste) {
    const copyText = async () => {
      try {
        await navigator.clipboard.writeText(pastedText);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Clipboard failure is non-critical here — the text is still visible below.
      }
    };

    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-6"
      >
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
            {isDeidentify ? 'Nothing was found to replace' : 'Nothing to redact'}
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            We scanned your pasted text and didn&apos;t find any personal information
            matching the names you gave us. Nothing needed removing, so here it is unchanged.
          </p>
        </div>

        <section>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-slate-600">Your text</h3>
            <button
              onClick={copyText}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-primary-50 text-primary-600 hover:bg-primary-100 transition-colors btn-press"
            >
              <Copy size={12} /> {copied ? 'Copied ✓' : 'Copy text'}
            </button>
          </div>
          <textarea
            readOnly
            value={pastedText}
            rows={12}
            className="w-full text-xs font-mono text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-4
                       resize-y focus:outline-none focus:ring-2 focus:ring-primary-200"
          />
        </section>

        <div className="pt-2">
          <button
            onClick={handleBackToNames}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600
                       hover:bg-slate-100 border border-slate-200 transition-colors btn-press"
          >
            <ArrowLeft size={16} />
            Check the names
          </button>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-16 text-center space-y-6"
    >
      <div
        className={`w-20 h-20 rounded-full flex items-center justify-center ${
          isDeidentify ? 'bg-amber-50' : 'bg-emerald-50'
        }`}
      >
        {isDeidentify
          ? <AlertTriangle size={40} className="text-amber-500" />
          : <ShieldCheck size={40} className="text-emerald-500" />}
      </div>

      <div className="space-y-3 max-w-md">
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
          {isDeidentify ? 'Nothing was found to replace' : 'Nothing to redact'}
        </h2>

        {isDeidentify ? (
          <>
            <p className="text-slate-600 leading-relaxed">
              We scanned {docCount} document{docCount !== 1 ? 's' : ''} and didn&apos;t find
              any personal information matching the names you gave us.
            </p>
            {/*
              Never imply "clean" here. Finding nothing in a student report
              usually means a misspelt name, not an anonymous document — and a
              teacher who reads "clean" may paste it straight into an AI tool.
            */}
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-left">
              That is unusual for a student document, so it is worth checking the
              spelling of the names on the previous step. Finding nothing does
              <span className="font-medium"> not </span>
              mean the document has nothing personal in it.
            </p>
            <p className="text-sm text-slate-400">
              You can still create the text file — but nothing will have been
              replaced, so read it before you share it anywhere.
            </p>
          </>
        ) : (
          <>
            <p className="text-slate-600 leading-relaxed">
              We scanned {docCount} document{docCount !== 1 ? 's' : ''} and didn&apos;t find any personal
              information matching the names you provided. Your folder appears clean.
            </p>
            <p className="text-sm text-slate-400">
              If you expected items to be flagged, double-check the spelling of names on the previous step.
            </p>
          </>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-3 pt-2">
        <button
          onClick={handleBackToNames}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600
                     hover:bg-slate-100 border border-slate-200 transition-colors btn-press"
        >
          <ArrowLeft size={16} />
          Check the names
        </button>

        {isDeidentify && (
          <button
            onClick={() => navigateTo('final_confirmation')}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600
                       hover:bg-slate-100 border border-slate-200 transition-colors btn-press"
          >
            Create the text file anyway
            <ArrowRight size={16} />
          </button>
        )}

        <button
          onClick={handleProcessAnother}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow
                     transition-all btn-press"
        >
          <RotateCcw size={16} />
          Start Again
        </button>
      </div>
    </motion.div>
  );
}
