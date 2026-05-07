import { motion } from 'framer-motion';
import { ShieldCheck, RotateCcw, ArrowLeft } from 'lucide-react';
import { useStore } from '../store';

export default function NoPiiFound() {
  const detectionResults = useStore((s) => s.detectionResults);
  const navigateTo = useStore((s) => s.navigateTo);

  if (!detectionResults) return null;

  const docCount = detectionResults.documents.length;

  const handleBackToNames = () => {
    navigateTo('folder_selection');
  };

  const handleProcessAnother = () => {
    useStore.getState().reset();
    navigateTo('folder_selection');
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-16 text-center space-y-6"
    >
      {/* Icon */}
      <div className="w-20 h-20 rounded-full bg-emerald-50 flex items-center justify-center">
        <ShieldCheck size={40} className="text-emerald-500" />
      </div>

      {/* Heading */}
      <div className="space-y-3 max-w-md">
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Nothing to redact</h2>
        <p className="text-slate-600 leading-relaxed">
          We scanned {docCount} document{docCount !== 1 ? 's' : ''} and didn&apos;t find any personal
          information matching the names you provided. Your folder appears clean.
        </p>
        <p className="text-sm text-slate-400">
          If you expected items to be flagged, double-check the spelling of names on the previous step.
        </p>
      </div>

      {/* Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 pt-2">
        <button
          onClick={handleBackToNames}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600
                     hover:bg-slate-100 border border-slate-200 transition-colors btn-press"
        >
          <ArrowLeft size={16} />
          Back to Names
        </button>
        <button
          onClick={handleProcessAnother}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow
                     transition-all btn-press"
        >
          <RotateCcw size={16} />
          Process Another Folder
        </button>
      </div>
    </motion.div>
  );
}
