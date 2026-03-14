import { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, ShieldCheck, FolderOpen, Search } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import HelpTip from '../components/HelpTip';
import RedactionProgress from '../components/RedactionProgress';

export default function FinalConfirmation() {
  const {
    detectionResults, userSelections, folderPath, studentName,
    parentNames, familyNames, organisationNames, redactHeaderFooter,
    navigateTo, setRedactionResults, setError,
  } = useStore();

  const [outputMode, setOutputMode] = useState<'default' | 'custom'>('default');
  const [customPath, setCustomPath] = useState('');
  const [redacting, setRedacting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Clear any stale errors when this screen mounts
  useEffect(() => {
    setError(null);
  }, [setError]);

  const handleBrowseOutput = useCallback(async () => {
    const selected = await window.electronAPI?.selectFolder();
    if (selected) {
      setCustomPath(selected);
      setOutputMode('custom');
    }
  }, []);

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

  // Derive the default output path for display
  const defaultOutputDisplay = `${folderPath}/redacted/`;

  const handleRedact = async () => {
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
        folder_action: outputMode === 'default' ? null : null,
        custom_output_path: outputMode === 'custom' ? customPath : null,
      }, { signal: ctrl.signal });

      setRedactionResults(results);
      navigateTo('completion');
    } catch (e: any) {
      if (e.name !== 'AbortError') setError(e.message);
    } finally {
      setRedacting(false);
    }
  };

  // Show dedicated redaction progress screen with witty comments
  if (redacting) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <RedactionProgress totalDocuments={detectionResults.documents.length} />
        <div className="mt-8">
          <button
            onClick={() => {
              if (confirm('Cancel redaction? Progress will be lost.')) {
                abortRef.current?.abort();
              }
            }}
            className="px-4 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 transition-colors btn-press"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Final Confirmation</h2>
        <p className="text-sm text-slate-400 mt-1">Review your selections before creating redacted documents.</p>
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

      {/* Output Folder */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <div className="flex items-center gap-2 mb-4">
          <FolderOpen size={16} className="text-primary-500" />
          <h3 className="text-sm font-medium text-slate-600">Save Redacted Files To</h3>
          <HelpTip text="Redacted copies are saved separately — your original files are never modified. By default they go in a 'redacted' folder inside your source folder." />
        </div>

        <div className="space-y-2.5">
          {/* Default option */}
          <label
            className={`
              flex items-start gap-3 p-3.5 rounded-lg border cursor-pointer transition-all
              ${outputMode === 'default' ? 'border-primary-300 bg-primary-50/50' : 'border-slate-100 hover:border-slate-200'}
            `}
          >
            <input
              type="radio"
              name="outputMode"
              checked={outputMode === 'default'}
              onChange={() => setOutputMode('default')}
              className="accent-primary-600 mt-0.5"
            />
            <div className="flex-1 min-w-0">
              <span className="text-sm text-slate-700 font-medium">Inside the source folder</span>
              <p className="text-xs text-slate-400 mt-0.5">
                A <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-500">redacted</code> subfolder
                will be created alongside your original files
              </p>
              <code className="text-[11px] text-slate-400 mt-1.5 block truncate">
                {defaultOutputDisplay}
              </code>
            </div>
          </label>

          {/* Custom location */}
          <label
            className={`
              flex items-start gap-3 p-3.5 rounded-lg border cursor-pointer transition-all
              ${outputMode === 'custom' ? 'border-primary-300 bg-primary-50/50' : 'border-slate-100 hover:border-slate-200'}
            `}
          >
            <input
              type="radio"
              name="outputMode"
              checked={outputMode === 'custom'}
              onChange={() => setOutputMode('custom')}
              className="accent-primary-600 mt-0.5"
            />
            <div className="flex-1 min-w-0">
              <span className="text-sm text-slate-700 font-medium">Choose a different location</span>
              <p className="text-xs text-slate-400 mt-0.5">
                Save the redacted files to any folder on your computer
              </p>
              {outputMode === 'custom' && (
                <div className="flex gap-2 mt-2.5">
                  <code className="flex-1 text-[11px] bg-slate-50 px-3 py-2 rounded-lg text-slate-500 overflow-x-auto min-h-[32px] flex items-center">
                    {customPath || 'No folder selected...'}
                  </code>
                  <button
                    type="button"
                    onClick={handleBrowseOutput}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50
                               text-xs text-slate-600 font-medium hover:bg-slate-100 hover:border-slate-300
                               transition-colors shrink-0 btn-press"
                  >
                    <Search size={12} />
                    Browse
                  </button>
                </div>
              )}
            </div>
          </label>
        </div>
      </motion.section>

      {/* Warning */}
      <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
        <ShieldCheck size={18} className="text-emerald-500 shrink-0 mt-0.5" />
        <p className="text-sm text-emerald-700">
          Your original files will <span className="font-medium">not</span> be modified. Redacted copies will be created in the output folder above.
        </p>
      </div>

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button
          onClick={() => navigateTo('document_review')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors btn-press"
        >
          <ArrowLeft size={16} /> Back to Review
        </button>

        <div className="flex gap-2">
          <button
            onClick={handleRedact}
            disabled={totalSelected === 0 || (outputMode === 'custom' && !customPath)}
            className={`
              flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all
              ${totalSelected > 0 && !(outputMode === 'custom' && !customPath)
                ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow btn-press'
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
