import { motion } from 'framer-motion';
import { ShieldCheck, RotateCcw, ArrowLeft, ArrowRight, AlertTriangle } from 'lucide-react';
import { useStore } from '../store';

export default function NoPiiFound() {
  const detectionResults = useStore((s) => s.detectionResults);
  const workflowMode = useStore((s) => s.workflowMode);
  const navigateTo = useStore((s) => s.navigateTo);

  if (!detectionResults) return null;

  const docCount = detectionResults.documents.length;
  const isDeidentify = workflowMode === 'deidentify';

  const handleBackToNames = () => {
    navigateTo('folder_selection');
  };

  // reset() already lands on mode_selection — navigating on top of it would
  // undo that and silently keep the previous pathway.
  const handleProcessAnother = () => {
    useStore.getState().reset();
  };

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
