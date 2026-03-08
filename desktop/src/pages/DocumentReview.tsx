import { motion } from 'framer-motion';
import {
  ArrowLeft, ArrowRight, CheckSquare, Square, FileText,
} from 'lucide-react';
import { useStore } from '../store';

export default function DocumentReview() {
  const {
    detectionResults, currentDocIndex, userSelections,
    setCurrentDocIndex, toggleSelection, selectAll, deselectAll,
    navigateTo,
  } = useStore();

  if (!detectionResults || detectionResults.documents.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        No documents to review.
      </div>
    );
  }

  const totalDocs = detectionResults.documents.length;
  const doc = detectionResults.documents[currentDocIndex];
  const matches = doc.matches;

  const selectedCount = matches.filter(
    (_, idx) => userSelections[`${doc.path}_${idx}`]
  ).length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-800">Review Detected PII</h2>
        <p className="text-slate-500 mt-1">Review and select which items to redact from each document.</p>
      </div>

      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs text-slate-400">
          <span>Document {currentDocIndex + 1} of {totalDocs}</span>
          <span>{Math.round(((currentDocIndex + 1) / totalDocs) * 100)}%</span>
        </div>
        <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary-500 rounded-full"
            initial={false}
            animate={{ width: `${((currentDocIndex + 1) / totalDocs) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      {/* Document header */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-primary-500" />
            <h3 className="font-medium text-slate-700">{doc.filename}</h3>
          </div>
          <span className="text-xs text-slate-400">
            {selectedCount}/{matches.length} selected
          </span>
        </div>

        {matches.length === 0 ? (
          <p className="text-sm text-slate-400 mt-3">No PII detected in this document.</p>
        ) : (
          <>
            {/* Select/Deselect all */}
            <div className="flex gap-2 mt-4">
              <button
                onClick={() => selectAll(doc.path, matches.length)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
              >
                <CheckSquare size={12} /> Select All
              </button>
              <button
                onClick={() => deselectAll(doc.path, matches.length)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
              >
                <Square size={12} /> Deselect All
              </button>
            </div>

            {/* Match list */}
            <div className="mt-4 space-y-2 max-h-[50vh] overflow-y-auto pr-1">
              {matches.map((match, idx) => {
                const key = `${doc.path}_${idx}`;
                const selected = userSelections[key] ?? true;
                const confColor = {
                  high: 'bg-emerald-100 text-emerald-700',
                  medium: 'bg-amber-100 text-amber-700',
                  low: 'bg-red-100 text-red-700',
                }[match.confidence_label] || 'bg-slate-100 text-slate-600';

                return (
                  <motion.div
                    key={key}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.02 }}
                    onClick={() => toggleSelection(key)}
                    className={`
                      flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all
                      ${selected
                        ? 'border-primary-200 bg-primary-50/40'
                        : 'border-slate-100 bg-white hover:border-slate-200'
                      }
                    `}
                  >
                    {/* Checkbox */}
                    <div className={`
                      mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors
                      ${selected ? 'bg-primary-600 border-primary-600' : 'border-slate-300'}
                    `}>
                      {selected && (
                        <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                          <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs text-slate-400">
                          Page {match.page_num}, Line {match.line_num}
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${confColor}`}>
                          {match.confidence_label}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">
                          {match.category}
                        </span>
                      </div>
                      <p className="text-sm text-slate-600 mt-1 leading-relaxed">{match.context}</p>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <div className="flex gap-2">
          {currentDocIndex > 0 && (
            <button
              onClick={() => setCurrentDocIndex(currentDocIndex - 1)}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
            >
              <ArrowLeft size={16} /> Previous
            </button>
          )}
          <button
            onClick={() => navigateTo('conversion_status')}
            className="px-4 py-2.5 rounded-lg text-sm text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            Cancel
          </button>
        </div>

        <div>
          {currentDocIndex < totalDocs - 1 ? (
            <button
              onClick={() => setCurrentDocIndex(currentDocIndex + 1)}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                         bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all"
            >
              Next Document <ArrowRight size={16} />
            </button>
          ) : (
            <button
              onClick={() => navigateTo('final_confirmation')}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                         bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all"
            >
              Review Summary <ArrowRight size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
