import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  CheckCircle, AlertTriangle, XCircle, FolderOpen, FileText, RotateCcw,
  ChevronDown, ChevronUp, KeyRound, ImageOff, Trash2, Copy, Eye, EyeOff,
} from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { friendlyError, friendlyDocumentError } from '../lib/errorMessage';
import HelpTip from '../components/HelpTip';
import { basename, dirname } from '../lib/paths';

export default function DeidentifyCompletion() {
  const { deidentifyResults, reset, setError } = useStore();
  const [logExpanded, setLogExpanded] = useState(false);
  const [deletingFlagged, setDeletingFlagged] = useState(false);
  const [flaggedDeleted, setFlaggedDeleted] = useState(false);
  // Output text lives in COMPONENT state only (rule 24's principle): it is
  // de-identified, but the store should not accumulate document bodies.
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [openPreview, setOpenPreview] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);

  if (!deidentifyResults) {
    return (
      <div className="text-center py-12 text-slate-500">
        Processing not complete.
      </div>
    );
  }

  const r = deidentifyResults;
  const erroredDocs = r.document_results.filter(
    (d) => !d.success && d.verification_failures.length === 0
  );
  const hasVerificationFailures = r.verification_failures.length > 0;
  const hasFailures = hasVerificationFailures || erroredDocs.length > 0;
  const imageWarnings = r.document_results.filter((d) => d.image_warnings.length > 0);
  const quarantined = r.document_results
    .map((d) => d.quarantine_path)
    .filter((p): p is string => Boolean(p));
  const ocrWarnings = r.document_results.filter((d) => d.ocr_warnings.length > 0);
  const nameWarnings = r.document_results.filter(
    (d) => (d.leftover_name_warnings?.length ?? 0) > 0);
  const allClear = !hasFailures && nameWarnings.length === 0;

  const fetchText = async (path: string) => {
    if (previews[path]) return previews[path];
    const res = await api.readOutput(r.output_folder, path);
    setPreviews((prev) => ({ ...prev, [path]: res.content }));
    return res.content;
  };

  const copyText = async (path: string) => {
    try {
      const content = await fetchText(path);
      await navigator.clipboard.writeText(content);
      setCopied(path);
      setTimeout(() => setCopied((c) => (c === path ? null : c)), 2000);
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
          De-identification Complete
        </h2>
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
            ? `${r.successfully_deidentified} of ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} de-identified — review the issues below`
            : `All ${r.total_documents} document${r.total_documents === 1 ? '' : 's'} de-identified successfully`}
        </h3>
        <p className="text-sm mt-1 text-slate-500">
          {hasFailures
            ? 'Do not upload anything listed as needing review.'
            : allClear
            ? 'These text files are ready to paste into an AI tool.'
            : 'Check the warnings below before sharing.'}
        </p>
      </motion.div>

      {/* The key file — the one thing that must never be uploaded */}
      {r.key_file_path && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <KeyRound size={16} />
            Keep this file private
          </div>
          <p className="text-xs text-red-600 mb-3 leading-relaxed">
            A file named <span className="font-semibold">{basename(r.key_file_path)}</span> was
            saved with your original documents. It turns the labels back into real names, so
            never upload it or paste it into an AI tool.{' '}
            {r.output_folder_holds_originals ? (
              <>
                <span className="font-semibold">
                  You chose to save the text files into that same folder
                </span>
                , so it also holds your original documents and this key. Don&apos;t
                share the folder itself — send the individual text files.
              </>
            ) : (
              <>It is deliberately kept out of the folder below, so everything
              you are about to share stays safe.</>
            )}
          </p>
          <div className="flex items-center gap-3">
            <code className="text-xs bg-white/70 px-3 py-2 rounded-lg text-red-600 flex-1 overflow-x-auto">
              {r.key_file_path}
            </code>
            <button
              onClick={async () => {
                try { await api.openFolder(dirname(r.key_file_path!)); }
                catch (e) { setError(friendlyError(e)); }
              }}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm bg-red-100 text-red-700 hover:bg-red-200 transition-colors shrink-0 btn-press"
            >
              <FolderOpen size={14} /> Show me
            </button>
          </div>
        </motion.section>
      )}

      {/* Verification failures */}
      {hasVerificationFailures && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <XCircle size={16} />
            {r.verification_failures.length} file(s) need checking before you share them
            <HelpTip text="After replacing the text, the tool re-reads it to confirm nothing was missed. These files were saved with an UNVERIFIED name so they can't be shared by mistake. Open them and check before using." />
          </div>
          <p className="text-xs text-red-600 mb-3">
            A name may still be readable in these files — often a scanned page the OCR
            misread. Open them and check before pasting anything into an AI tool.
          </p>
          {r.verification_failures.map((f, i) => (
            <p key={i} className="text-xs text-red-500 py-0.5">
              {f.filename}: {f.message}
            </p>
          ))}

          {/* These files hold text that was NOT fully de-identified, sitting in
              the folder the user is about to share. Make removing them one
              click, rather than relying on them reading the warning. */}
          {quarantined.length > 0 && !flaggedDeleted && (
            <button
              onClick={async () => {
                setDeletingFlagged(true);
                try {
                  await api.cleanup(r.output_folder, quarantined);
                  setFlaggedDeleted(true);
                } catch (e) {
                  setError(friendlyError(e));
                } finally {
                  setDeletingFlagged(false);
                }
              }}
              disabled={deletingFlagged}
              className="mt-3 flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-red-100 text-red-700
                         hover:bg-red-200 disabled:opacity-50 transition-colors btn-press"
            >
              <Trash2 size={14} />
              {deletingFlagged
                ? 'Deleting…'
                : `Delete ${quarantined.length === 1 ? 'this file' : 'these files'}`}
            </button>
          )}
          {flaggedDeleted && (
            <p className="mt-3 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
              Deleted. The remaining files in the output folder passed checking.
            </p>
          )}
        </motion.div>
      )}

      {/* Documents that errored outright */}
      {erroredDocs.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <XCircle size={16} />
            {erroredDocs.length} document{erroredDocs.length === 1 ? '' : 's'} could not be de-identified
          </div>
          {erroredDocs.map((d, i) => (
            <p key={i} className="text-xs text-red-500 py-0.5">
              {d.document_name}: {friendlyDocumentError(d.error_message)}
            </p>
          ))}
        </motion.div>
      )}

      {/* Scanned pages */}
      {ocrWarnings.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-amber-50 border border-amber-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-700 mb-2">
            <AlertTriangle size={16} />
            Scanned pages — worth a read-through
          </div>
          {ocrWarnings.map((d, i) => (
            <div key={i} className="py-0.5">
              {d.ocr_warnings.map((w, j) => (
                <p key={j} className="text-xs text-amber-600">{d.document_name}: {w}</p>
              ))}
            </div>
          ))}
        </motion.div>
      )}

      {/* Images left out */}
      {imageWarnings.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-slate-50 border border-slate-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-slate-600 mb-2">
            <ImageOff size={16} className="text-slate-400" />
            Pictures were not included
            <HelpTip text="A text file can only hold text. Anything inside a picture — a screenshot of an email, a chart — is simply absent from the output. Nothing from those pictures has leaked, but the AI won't see them either." />
          </div>
          {imageWarnings.map((d, i) => (
            <div key={i} className="py-0.5">
              {d.image_warnings.map((w, j) => (
                <p key={j} className="text-xs text-slate-500">{d.document_name}: {w}</p>
              ))}
            </div>
          ))}
        </motion.div>
      )}

      {/* Names the sweep still sees */}
      {nameWarnings.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-amber-50 border border-amber-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-700 mb-2">
            <AlertTriangle size={16} />
            These may still contain a name
            <HelpTip text="After replacing everything you selected, the tool re-reads the output looking for anything that still resembles a person's name — usually someone the detection step missed. Open the file and check before sharing." />
          </div>
          {nameWarnings.map((d, i) => (
            <p key={i} className="text-xs text-amber-700 py-0.5">
              {d.document_name}: still contains{' '}
              {d.leftover_name_warnings.map((n) => `"${n}"`).join(', ')}
            </p>
          ))}
        </motion.div>
      )}

      {/* Per-document summary */}
      {r.document_results.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="bg-white rounded-xl border border-slate-200 p-5"
        >
          <h3 className="text-sm font-medium text-slate-600 mb-3">Document Summary</h3>
          <div className="space-y-2">
            {r.document_results.map((d, i) => (
              <div key={i} className="flex items-center justify-between text-sm gap-3">
                <span className="text-slate-600 truncate flex-1 min-w-0">
                  {d.output_path ? basename(d.output_path)
                    : d.quarantine_path ? basename(d.quarantine_path)
                    : d.document_name}
                </span>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${
                    d.success
                      ? 'bg-emerald-50 text-emerald-600'
                      : 'bg-red-50 text-red-600'
                  }`}
                >
                  {d.success ? `${d.items_replaced} replaced` : 'needs review'}
                </span>
                {d.success && d.output_path && (
                  <span className="flex gap-1 shrink-0">
                    <button
                      onClick={() => copyText(d.output_path!)}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs bg-primary-50 text-primary-600 hover:bg-primary-100 transition-colors btn-press"
                    >
                      <Copy size={12} />
                      {copied === d.output_path ? 'Copied ✓' : 'Copy text'}
                    </button>
                    <button
                      onClick={async () => {
                        const open = !openPreview[d.output_path!];
                        if (open) await fetchText(d.output_path!).catch((e) => setError(friendlyError(e)));
                        setOpenPreview((prev) => ({ ...prev, [d.output_path!]: open }));
                      }}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs bg-slate-100 text-slate-500 hover:bg-slate-200 transition-colors btn-press"
                    >
                      {openPreview[d.output_path] ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                  </span>
                )}
              </div>
            ))}
            {r.document_results.map((d) =>
              d.output_path && openPreview[d.output_path] && previews[d.output_path] ? (
                <pre
                  key={`prev-${d.output_path}`}
                  className="text-[11px] text-slate-500 bg-slate-50 rounded-lg p-3 overflow-x-auto max-h-56 overflow-y-auto whitespace-pre-wrap leading-relaxed"
                >
                  {previews[d.output_path]}
                </pre>
              ) : null
            )}
          </div>
        </motion.section>
      )}

      {/* Output folder */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <h3 className="text-sm font-medium text-slate-600 mb-2">De-identified Documents</h3>
        <div className="flex items-center gap-3">
          <code className="text-xs bg-slate-50 px-3 py-2 rounded-lg text-slate-500 flex-1 overflow-x-auto">
            {r.output_folder}
          </code>
          <button
            onClick={async () => {
              try { await api.openFolder(r.output_folder); }
              catch (e) { setError(friendlyError(e)); }
            }}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors shrink-0 btn-press"
          >
            <FolderOpen size={14} /> Open Folder
          </button>
        </div>
      </motion.section>

      {/* Log */}
      <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <button
          onClick={() => setLogExpanded(!logExpanded)}
          className="w-full flex items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
        >
          <FileText size={14} className="text-slate-400" />
          <span className="flex-1 text-left font-medium flex items-center gap-1.5">
            De-identification Log
            <HelpTip text="A record of what was replaced and where. It lists the labels only — never the real names — so it is safe to keep alongside your documents." />
          </span>
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

      <div className="flex justify-center pt-4">
        <button
          onClick={reset}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <RotateCcw size={16} /> Start Again
        </button>
      </div>
    </div>
  );
}
