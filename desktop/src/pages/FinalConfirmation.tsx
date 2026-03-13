import { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, ShieldCheck, AlertTriangle } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';

export default function FinalConfirmation() {
  const {
    detectionResults, userSelections, folderPath, studentName,
    parentNames, familyNames, organisationNames, redactHeaderFooter,
    navigateTo, setRedactionResults, setLoading, setError,
  } = useStore();

  const [folderAction, setFolderAction] = useState<string>('new');
  const [redacting, setRedacting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  if (!detectionResults) return null;

  // Count selected items by category
  const categoryCounts: Record<string, number> = {};
  let totalSelected = 0;

  for (const doc of detectionResults.documents) {
    doc.matches.forEach((match, idx) => {
      const key = `${doc.path}_${idx}`;
      if (userSelections[key]) {
        totalSelected++;
        categoryCounts[match.category] = (categoryCounts[match.category] || 0) + 1;
      }
    });
  }

  const handleRedact = async () => {
    setLoading(true, 'Redacting documents...');
    setRedacting(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const selectedKeys: string[] = [];
      for (const doc of detectionResults.documents) {
        doc.matches.forEach((_, idx) => {
          const key = `${doc.path}_${idx}`;
          if (userSelections[key]) selectedKeys.push(key);
        });
      }

      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
      const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

      const results = await api.redact({
        folder_path: folderPath,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
        redact_header_footer: redactHeaderFooter,
        documents: detectionResults.documents.map((d) => d.path),
        detected_pii: Object.fromEntries(
          detectionResults.documents.map((d) => [d.path, d.matches])
        ),
        selected_keys: selectedKeys,
        folder_action: folderAction,
      }, { signal: ctrl.signal });

      setRedactionResults(results);
      navigateTo('completion');
    } catch (e: any) {
      if (e.name !== 'AbortError') setError(e.message);
    } finally {
      setLoading(false);
      setRedacting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-800">Final Confirmation</h2>
        <p className="text-slate-500 mt-1">Review your selections before creating redacted documents.</p>
      </div>

      {/* Summary metrics */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="grid grid-cols-2 gap-4"
      >
        <div className="bg-white rounded-xl border border-slate-200 p-5 text-center">
          <p className="text-3xl font-semibold text-primary-600">{totalSelected}</p>
          <p className="text-xs text-slate-400 mt-1 uppercase tracking-wide">Items to Redact</p>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-5 text-center">
          <p className="text-3xl font-semibold text-slate-700">{detectionResults.documents.length}</p>
          <p className="text-xs text-slate-400 mt-1 uppercase tracking-wide">Documents</p>
        </div>
      </motion.div>

      {/* Category breakdown */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <h3 className="text-sm font-medium text-slate-600 mb-3">Breakdown by Category</h3>
        {Object.keys(categoryCounts).length > 0 ? (
          <div className="space-y-2">
            {Object.entries(categoryCounts)
              .sort(([, a], [, b]) => b - a)
              .map(([category, count]) => (
                <div key={category} className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">{category}</span>
                  <span className="text-xs font-medium bg-primary-50 text-primary-600 px-2 py-0.5 rounded-full">
                    {count}
                  </span>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">No items selected for redaction.</p>
        )}
      </motion.section>

      {/* Folder action (if redacted folder exists) */}
      {/* TODO: Check if folder exists via API — for now always show the option */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <h3 className="text-sm font-medium text-slate-600 mb-3">Output Folder</h3>
        <div className="space-y-2">
          {['overwrite', 'new'].map((action) => (
            <label
              key={action}
              className={`
                flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all
                ${folderAction === action ? 'border-primary-300 bg-primary-50/50' : 'border-slate-100 hover:border-slate-200'}
              `}
            >
              <input
                type="radio"
                name="folderAction"
                checked={folderAction === action}
                onChange={() => setFolderAction(action)}
                className="accent-primary-600"
              />
              <span className="text-sm text-slate-600">
                {action === 'overwrite' ? 'Overwrite existing folder' : 'Create new folder (redacted_2, etc.)'}
              </span>
            </label>
          ))}
        </div>
      </motion.section>

      {/* Warning */}
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        <AlertTriangle size={18} className="text-amber-500 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-700">
          This action cannot be undone. Original files will not be modified — redacted copies will be created in a separate folder.
        </p>
      </div>

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button
          onClick={() => navigateTo('document_review')}
          disabled={redacting}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-50"
        >
          <ArrowLeft size={16} /> Back to Review
        </button>

        <div className="flex gap-2">
          {redacting && (
            <button
              onClick={() => {
                if (confirm('Cancel redaction? Progress will be lost.')) {
                  abortRef.current?.abort();
                }
              }}
              className="px-4 py-2.5 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 transition-colors"
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleRedact}
            disabled={totalSelected === 0 || redacting}
            className={`
              flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all
              ${totalSelected > 0 && !redacting
                ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow'
                : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }
            `}
          >
            <ShieldCheck size={16} /> Create Redacted Documents
          </button>
        </div>
      </div>
    </div>
  );
}
