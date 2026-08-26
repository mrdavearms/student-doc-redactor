import { useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Copy, Save, RotateCcw, KeyRound } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { friendlyError } from '../lib/errorMessage';
import { peekSensitive, clearSensitive } from '../lib/pasteResult';

/**
 * Completion screen for the paste pathway. There is no output folder and no
 * originals on disk, so unlike Completion/DeidentifyCompletion the cleaned
 * result lives here rather than in a folder the user is pointed at.
 *
 * De-identify mode shows both the safe text AND the re-identifying key on the
 * same screen — the one place they ever coexist. A careless select-all-copy
 * would put the key on the clipboard alongside the very text about to be
 * pasted into an AI tool, so the two live in SEPARATE boxes with SEPARATE
 * Copy buttons, and the key sits behind a collapsed <details>.
 */
export default function PasteCompletion() {
  const {
    pasteOutput, workflowMode, clearPastedText, setPasteOutput, navigateTo, setError,
  } = useStore();
  const [copied, setCopied] = useState(false);
  const [keyCopied, setKeyCopied] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  // Only known after a PDF save actually runs (backend/main.py's response),
  // so it can't live in pasteOutput -- it's about the saved FILE, not the
  // text shown on screen.
  const [unsupportedChars, setUnsupportedChars] = useState<string[]>([]);
  // Snapshot taken once at mount, deliberately NOT re-read from the store on
  // every render. "Clean another" clears pasteOutput and navigates away, but
  // Layout's AnimatePresence keeps this component mounted for its ~1s exit
  // animation — without this snapshot it re-renders mid-fade with
  // pasteOutput already null and flashes "Processing not complete." at
  // someone who just succeeded. The store itself is still cleared
  // immediately (nothing here delays that); this copy lives only in this
  // about-to-unmount component and is garbage collected with it, the same
  // precedent CLAUDE.md rule 24 sets for other sensitive on-screen state.
  const [display] = useState(() => pasteOutput);

  const isDeidentify = workflowMode === 'deidentify';
  // Real names — read from the module-level holder, never the store
  // (CLAUDE.md rule 24's precedent). Read without consuming: React may
  // render this component twice under StrictMode.
  const { key_entries, ambiguity_notes, leftover_name_warnings } = peekSensitive();

  if (!display) {
    return (
      <div className="text-center py-12 text-slate-500">
        Processing not complete.
      </div>
    );
  }

  const { text, replacements, leftovers } = display;

  const copyMain = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  const copyKey = async () => {
    try {
      const lines = [
        ...key_entries.map((k) => `${k.label} = ${k.real_name}`),
        ...ambiguity_notes,
      ];
      await navigator.clipboard.writeText(lines.join('\n'));
      setKeyCopied(true);
      setTimeout(() => setKeyCopied(false), 2000);
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  const handleSave = async () => {
    const kind = isDeidentify ? 'txt' : 'pdf';
    const suggested = isDeidentify
      ? (leftovers.length ? 'cleaned-text.UNVERIFIED.txt' : 'cleaned-text.txt')
      : 'redacted-text.pdf';
    const path = await window.electronAPI?.saveFileAs?.(suggested, kind);
    if (!path) return;                       // user cancelled — stay put
    try {
      const result = await api.saveText(text, path, kind);
      setUnsupportedChars(result.unsupported_characters ?? []);
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  const handleCleanAnother = async () => {
    setCleaning(true);
    clearPastedText();
    clearSensitive();
    setPasteOutput(null);
    try {
      await api.discardText();
    } catch {
      // Best-effort — the backend overwrites this cache entry on the next run.
    } finally {
      setCleaning(false);
    }
    navigateTo('folder_selection');
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
          {isDeidentify ? 'Your de-identified text is ready' : 'Your text is ready'}
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          {replacements} item{replacements === 1 ? '' : 's'} {isDeidentify ? 'replaced' : 'blacked out'}.
        </p>
      </div>

      {leftovers.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50 border border-red-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
            <AlertTriangle size={16} />
            Some items may still be visible
          </div>
          <p className="text-xs text-red-600 mb-2">
            These could not be confirmed as fully removed. Read the text below before sharing it
            {isDeidentify
              ? ' — the Save button below now suggests an UNVERIFIED filename as a reminder.'
              : '.'}
          </p>
          <ul className="text-xs text-red-500 space-y-0.5">
            {leftovers.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </motion.div>
      )}

      {leftover_name_warnings.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-amber-50 border border-amber-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-700 mb-2">
            <AlertTriangle size={16} />
            These still look like names — check before you share
          </div>
          <p className="text-xs text-amber-600">
            {leftover_name_warnings.map((n) => `"${n}"`).join(', ')}
          </p>
        </motion.div>
      )}

      {/* The cleaned text — its own box, its own Copy button. Never share a
          scroll area with the name key below. */}
      <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-600">
            {isDeidentify ? 'De-identified text' : 'Redacted text'}
          </h3>
          <button
            onClick={copyMain}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-primary-50 text-primary-600 hover:bg-primary-100 transition-colors btn-press"
          >
            <Copy size={12} /> {copied ? 'Copied ✓' : 'Copy text'}
          </button>
        </div>
        <textarea
          readOnly
          value={text}
          rows={14}
          className="w-full text-xs font-mono text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-4
                     resize-y focus:outline-none focus:ring-2 focus:ring-primary-200"
        />
      </motion.section>

      <div className="flex justify-center">
        <button
          onClick={handleSave}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <Save size={16} /> {isDeidentify ? 'Save as .txt' : 'Save as PDF'}
        </button>
      </div>

      {unsupportedChars.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-amber-50 border border-amber-200 rounded-xl p-5"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-700 mb-2">
            <AlertTriangle size={16} />
            Some characters couldn't be shown in the saved PDF
          </div>
          <p className="text-xs text-amber-600">
            The PDF's text style can't display these characters, so they appear as a question
            mark (?) instead: {unsupportedChars.map((c) => `"${c}"`).join(', ')}. This can
            happen with emoji or characters from some non-English scripts. Copying the text
            above instead keeps everything exactly as written.
          </p>
        </motion.div>
      )}

      {isDeidentify && (key_entries.length > 0 || ambiguity_notes.length > 0) && (
        <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <details>
            <summary
              className="cursor-pointer list-none flex items-center gap-2 px-5 py-3 text-sm
                         text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <KeyRound size={14} className="text-slate-400" />
              <span className="flex-1 text-left font-medium">Name key — keep this private</span>
            </summary>
            <div className="px-5 pb-4 space-y-3">
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                This turns the labels above back into real names. Never paste it into an
                AI tool, and never share it alongside the text above.
              </p>
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-medium text-slate-500">Keep this for your own records only</h4>
                <button
                  onClick={copyKey}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors btn-press"
                >
                  <Copy size={12} /> {keyCopied ? 'Copied ✓' : 'Copy key'}
                </button>
              </div>
              <textarea
                readOnly
                rows={Math.min(12, Math.max(4, key_entries.length + ambiguity_notes.length))}
                value={[
                  ...key_entries.map((k) => `${k.label} = ${k.real_name}`),
                  ...(ambiguity_notes.length ? ['', ...ambiguity_notes] : []),
                ].join('\n')}
                className="w-full text-xs font-mono text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-4
                           resize-y focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            </div>
          </details>
        </section>
      )}

      <div className="flex justify-center pt-2">
        <button
          onClick={handleCleanAnother}
          disabled={cleaning}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium text-slate-600
                     hover:bg-slate-100 border border-slate-200 transition-colors btn-press disabled:opacity-50"
        >
          <RotateCcw size={16} /> Clean another
        </button>
      </div>
    </div>
  );
}
