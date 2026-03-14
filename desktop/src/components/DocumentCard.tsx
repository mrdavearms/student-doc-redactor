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
