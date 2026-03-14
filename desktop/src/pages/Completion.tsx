import { motion } from 'framer-motion';
import {
  CheckCircle, AlertTriangle, XCircle, FolderOpen, FileText, RotateCcw,
  ChevronDown, ChevronUp, ArrowRight,
} from 'lucide-react';
import { useState } from 'react';
import { useStore } from '../store';
import { api } from '../api';

export default function Completion() {
  const { redactionResults, reset } = useStore();
  const [logExpanded, setLogExpanded] = useState(true);

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
            Items on scanned pages — manual review required
          </div>
          {r.ocr_warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-600 py-0.5">
              {w.filename}: {w.count} item(s) on image-only pages
            </p>
          ))}
        </motion.div>
      )}

      {/* Output folder */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
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

      {/* Filename audit */}
      {r.document_results && r.document_results.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-white rounded-xl border border-slate-200 p-5"
        >
          <h3 className="text-sm font-medium text-slate-600 mb-3">Filename Audit</h3>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {r.document_results.map((d, i) => {
              const inputName = d.document_name;
              const outputName = d.output_path ? d.output_path.split('/').pop() : '—';
              const renamed = inputName !== outputName;
              return (
                <div key={i} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-slate-500 truncate flex-1" title={inputName}>{inputName}</span>
                  <ArrowRight size={10} className="text-slate-300 shrink-0" />
                  <span className={`truncate flex-1 ${renamed ? 'text-primary-600 font-medium' : 'text-slate-400'}`} title={outputName || ''}>
                    {outputName}
                  </span>
                  {!d.success && <XCircle size={12} className="text-red-400 shrink-0" />}
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 mt-2">Highlighted filenames had PII removed.</p>
        </motion.section>
      )}

      {/* Redaction log */}
      <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <button
          onClick={() => setLogExpanded(!logExpanded)}
          className="w-full flex items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
        >
          <FileText size={14} className="text-slate-400" />
          <span className="flex-1 text-left font-medium">Redaction Log</span>
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
