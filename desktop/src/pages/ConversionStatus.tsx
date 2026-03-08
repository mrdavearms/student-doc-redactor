import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle, XCircle, AlertTriangle, FileText, ArrowRight, ArrowLeft,
  ChevronDown, ChevronUp, Lock, RefreshCw,
} from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import type { DependencyStatus, ConversionResults } from '../types';

export default function ConversionStatus() {
  const {
    folderPath, conversionResults, setConversionResults,
    setDetectionResults, studentName, parentNames, familyNames,
    navigateTo, setLoading, setError,
  } = useStore();

  const [deps, setDeps] = useState<DependencyStatus | null>(null);
  const [processing, setProcessing] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // Check dependencies on mount
  useEffect(() => {
    api.checkDependencies().then(setDeps).catch((e) => setError(e.message));
  }, [setError]);

  // Process folder on mount (if not already done)
  useEffect(() => {
    if (conversionResults || !deps?.can_convert_word) return;
    setProcessing(true);
    api.processFolder(folderPath)
      .then((r) => setConversionResults(r))
      .catch((e) => setError(e.message))
      .finally(() => setProcessing(false));
  }, [deps, folderPath, conversionResults, setConversionResults, setError]);

  const results = conversionResults;
  const toggle = (key: string) => setExpanded((s) => ({ ...s, [key]: !s[key] }));

  const handleContinue = async () => {
    if (!results) return;
    setLoading(true, 'Extracting text and detecting PII...');
    try {
      const allPdfs = [...results.pdf_files, ...results.converted_files];
      const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
      const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);

      const detection = await api.detectPII({
        pdf_paths: allPdfs,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
      });

      setDetectionResults(detection);
      navigateTo('document_review');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-800">Document Conversion</h2>
        <p className="text-slate-500 mt-1">Checking dependencies and converting Word documents to PDF.</p>
      </div>

      {/* Dependencies */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <h3 className="text-sm font-medium text-slate-600 mb-3">Dependencies</h3>
        {!deps ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw size={14} className="animate-spin" /> Checking...
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <StatusBadge ok={deps.libreoffice_ok} label={`LibreOffice: ${deps.libreoffice_message}`} />
            <StatusBadge ok={deps.tesseract_ok} label={deps.tesseract_ok ? 'Tesseract OCR: Available' : 'Tesseract OCR: Not available'} warn={!deps.tesseract_ok} />
          </div>
        )}

        {deps && !deps.can_convert_word && (
          <div className="mt-3 bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 text-sm text-red-700">
            Cannot proceed without LibreOffice. Please install it first.
          </div>
        )}
      </motion.section>

      {/* Processing */}
      {processing && (
        <div className="flex items-center gap-3 text-sm text-slate-500 py-4">
          <RefreshCw size={16} className="animate-spin text-primary-500" />
          Converting documents...
        </div>
      )}

      {/* Results */}
      {results && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {/* Metrics */}
          <div className="grid grid-cols-4 gap-3">
            <MetricCard label="Total Files" value={results.total_files} />
            <MetricCard label="PDFs Ready" value={results.processable_count} color="emerald" />
            <MetricCard label="Converted" value={results.converted_files.length} color="blue" />
            <MetricCard label="Flagged" value={results.flagged_count} color={results.flagged_count > 0 ? 'amber' : 'slate'} />
          </div>

          {/* File lists */}
          {results.pdf_files.length > 0 && (
            <Expandable
              title={`Original PDFs (${results.pdf_files.length})`}
              expanded={expanded.pdfs}
              toggle={() => toggle('pdfs')}
              icon={<FileText size={14} className="text-blue-400" />}
            >
              {results.pdf_files.map((p) => <FileRow key={p} path={p} />)}
            </Expandable>
          )}

          {results.converted_files.length > 0 && (
            <Expandable
              title={`Converted from Word (${results.converted_files.length})`}
              expanded={expanded.converted}
              toggle={() => toggle('converted')}
              icon={<CheckCircle size={14} className="text-emerald-400" />}
            >
              {results.converted_files.map((p) => <FileRow key={p} path={p} />)}
            </Expandable>
          )}

          {results.password_protected.length > 0 && (
            <Expandable
              title={`Password Protected (${results.password_protected.length})`}
              expanded={expanded.protected ?? true}
              toggle={() => toggle('protected')}
              icon={<Lock size={14} className="text-amber-400" />}
              defaultExpanded
            >
              <p className="text-xs text-amber-600 mb-2">These files will be skipped. Unlock them manually if needed.</p>
              {results.password_protected.map((p) => <FileRow key={p} path={p} />)}
            </Expandable>
          )}

          {results.failed_conversions.length > 0 && (
            <Expandable
              title={`Failed Conversions (${results.failed_conversions.length})`}
              expanded={expanded.failed ?? true}
              toggle={() => toggle('failed')}
              icon={<XCircle size={14} className="text-red-400" />}
              defaultExpanded
            >
              {results.failed_conversions.map((f) => (
                <div key={f.path} className="text-xs text-slate-500 py-1">
                  {fileName(f.path)}: <span className="text-red-500">{f.reason}</span>
                </div>
              ))}
            </Expandable>
          )}
        </motion.section>
      )}

      {/* No files */}
      {results && results.processable_count === 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          No files available for processing. Check your folder and try again.
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button
          onClick={() => navigateTo('folder_selection')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <ArrowLeft size={16} /> Back
        </button>

        {results && results.processable_count > 0 && (
          <button
            onClick={handleContinue}
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                       bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all"
          >
            Continue <ArrowRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

function fileName(path: string) {
  return path.split('/').pop() || path;
}

function StatusBadge({ ok, label, warn }: { ok: boolean; label: string; warn?: boolean }) {
  return (
    <div className={`flex items-center gap-2 text-xs rounded-lg px-3 py-2 ${
      ok ? 'bg-emerald-50 text-emerald-700' : warn ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'
    }`}>
      {ok ? <CheckCircle size={14} /> : warn ? <AlertTriangle size={14} /> : <XCircle size={14} />}
      {label}
    </div>
  );
}

function MetricCard({ label, value, color = 'slate' }: { label: string; value: number; color?: string }) {
  const colors: Record<string, string> = {
    slate: 'text-slate-800',
    emerald: 'text-emerald-600',
    blue: 'text-blue-600',
    amber: 'text-amber-600',
  };
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 text-center">
      <p className={`text-2xl font-semibold ${colors[color] || colors.slate}`}>{value}</p>
      <p className="text-[11px] text-slate-400 mt-1 uppercase tracking-wide">{label}</p>
    </div>
  );
}

function Expandable({
  title, expanded, toggle, icon, children, defaultExpanded,
}: {
  title: string; expanded?: boolean; toggle: () => void;
  icon: React.ReactNode; children: React.ReactNode; defaultExpanded?: boolean;
}) {
  const isOpen = expanded ?? defaultExpanded ?? false;
  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button onClick={toggle} className="w-full flex items-center gap-2 px-4 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors">
        {icon}
        <span className="flex-1 text-left font-medium">{title}</span>
        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function FileRow({ path }: { path: string }) {
  return <p className="text-xs text-slate-500 py-0.5 pl-2">{fileName(path)}</p>;
}
