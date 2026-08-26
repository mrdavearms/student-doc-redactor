import { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, ShieldCheck, Bot, FolderOpen, FileText, Search, Trash2, AlertTriangle } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { friendlyError } from '../lib/errorMessage';
import { basename, dirname, isSamePath, joinPath, stem } from '../lib/paths';
import { suggestRedactedFilename, suggestDeidentifiedFilename } from '../lib/filename';
import { friendlyCategory } from '../lib/categories';
import { holdSensitive } from '../lib/pasteResult';
import HelpTip from '../components/HelpTip';
import RedactionProgress from '../components/RedactionProgress';

export default function FinalConfirmation() {
  const {
    detectionResults, userSelections, folderPath, studentName,
    parentNames, familyNames, organisationNames, redactHeaderFooter,
    inputMode, filePath, pastedText, workflowMode,
    personRoles, personCustomLabels, ignoredPeople, peopleAutoSkippedKey,
    navigateTo, setRedactionResults, setDeidentifyResults, setError,
    lastOutputPath, setLastOutputPath, setIsProcessing, setLoading, setPasteOutput,
  } = useStore();

  const isDeidentify = workflowMode === 'deidentify';
  const outputSubfolder = isDeidentify ? 'deidentified' : 'redacted';
  // Three input modes, not two — see CLAUDE.md rule about FinalConfirmation's
  // branching. isFileMode/isPaste are checked explicitly wherever the choice
  // matters, rather than inferring "folder" from "!isFileMode".
  const isPaste = inputMode === 'paste';

  const [outputMode, setOutputMode] = useState<'default' | 'custom'>('default');
  const [customPath, setCustomPath] = useState('');
  // Single-document mode: the full path chosen in the Save As dialog, or null
  // while the default (a 'redacted' subfolder, backend-generated name) applies.
  const [savePath, setSavePath] = useState<string | null>(null);
  const [redacting, setRedacting] = useState(false);
  const cancelRequestedRef = useRef(false);
  const [cancelPending, setCancelPending] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [partialFiles, setPartialFiles] = useState<string[] | null>(null);
  const [cleaningUp, setCleaningUp] = useState(false);
  const [cleanupDone, setCleanupDone] = useState(false);

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

  const isFileMode = inputMode === 'file';

  const handleSaveAs = useCallback(async () => {
    const names = [
      studentName,
      ...parentNames.split(','),
      ...familyNames.split(','),
      ...organisationNames.split(','),
    ].map((n) => n.trim()).filter(Boolean);
    const suggestedName = isDeidentify
      ? suggestDeidentifiedFilename(stem(filePath), names)
      : suggestRedactedFilename(stem(filePath), names);
    const selected = await window.electronAPI?.saveFileAs?.(
      joinPath(folderPath, suggestedName),
      isDeidentify ? 'txt' : 'pdf',
    );
    if (!selected) return;
    // The dialog opens in the source document's own folder, so the original is
    // right there to be picked. Writing over it would destroy the only
    // unredacted copy, so refuse here rather than let the run fail.
    if (isSamePath(selected, filePath)) {
      setError(
        "That's the original document. Choose a different name or folder so " +
        'your unredacted copy is kept.'
      );
      return;
    }
    setSavePath(selected);
  }, [filePath, folderPath, studentName, parentNames, familyNames,
      organisationNames, isDeidentify, setError]);

  if (!detectionResults) return null;

  // A word count is the paste-appropriate stand-in for the document-count
  // tile below — "1 document" is meaningless for a single pasted slab.
  const pastedWordCount = pastedText.trim() ? pastedText.trim().split(/\s+/).length : 0;

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
  const defaultOutputDisplay = joinPath(folderPath, outputSubfolder);

  // A custom folder was chosen in folder mode but no path picked yet. Folder
  // mode only — paste has no output-folder UI at all (see isPaste below), so
  // this must not fall through to it via a bare `!isFileMode`.
  const outputIncomplete = !isFileMode && !isPaste && outputMode === 'custom' && !customPath;

  // De-identify can legitimately run with nothing selected: the user came from
  // the "nothing found" screen and still wants the plain-text conversion.
  // Redaction with nothing selected would just copy the file, so stays blocked.
  const nothingSelected = totalSelected === 0;
  const canProceed = (isDeidentify || !nothingSelected) && !outputIncomplete;

  // Back is three-way. Nothing detected at all -> the "nothing found" screen,
  // never an empty review list. Otherwise de-identify came via "Who's who?"
  // and should return there, not skip back over it.
  const totalMatches = detectionResults.documents.reduce(
    (sum, d) => sum + d.matches.length, 0,
  );
  // If the people screen auto-skipped (nobody to classify), going Back to it
  // would land on an empty screen — go to the review instead.
  const peopleSkipped =
    peopleAutoSkippedKey === `people:${folderPath}:${studentName}`;
  const backTarget = totalMatches === 0
    ? 'no_pii_found'
    : isDeidentify && !peopleSkipped ? 'people_review' : 'document_review';

  // Only navigate if the user is still here. The pathway-change link can unmount
  // this screen mid-request; the pending promise still resolves, and without
  // this guard it would yank them to completion from wherever they had gone.
  const goToCompletionIfStillHere = () => {
    if (useStore.getState().currentScreen === 'final_confirmation') {
      navigateTo('completion');
    }
  };

  const handleRedact = async () => {
    // Paste has no documents, no cancel endpoint, and no output folder — it
    // takes its own short-lived path entirely separate from the
    // redacting/isProcessing/cancel scaffolding the document pathways need.
    if (isPaste) {
      // Same hazard as the document paths below: the Sidebar's pathway-change
      // link is a sibling of the loading overlay (which only covers <main>),
      // so it stays clickable during this request unless isProcessing hides
      // it outright. And if it's clicked anyway, a bare navigateTo('completion')
      // would drag the user back here once the request resolves, wherever
      // they'd gone in the meantime — goToCompletionIfStillHere guards that.
      setIsProcessing(true);
      setLoading(true, isDeidentify ? 'De-identifying your text…' : 'Blacking out your text…');
      try {
        const result = await api.cleanText({
          mode: workflowMode,
          student_name: studentName,
          selected_keys: Object.entries(userSelections)
            .filter(([, on]) => on).map(([k]) => k),
          parent_names: parentNames.split(',').map((n) => n.trim()).filter(Boolean),
          family_names: familyNames.split(',').map((n) => n.trim()).filter(Boolean),
          organisation_names: organisationNames.split(',').map((n) => n.trim()).filter(Boolean),
          person_roles: personRoles,
          person_custom_labels: personCustomLabels,
          ignored_people: ignoredPeople,
        });
        holdSensitive(result);
        setPasteOutput({
          text: result.text,
          replacements: result.replacements,
          leftovers: result.leftovers,
        });
        goToCompletionIfStillHere();
      } catch (e) {
        setError(friendlyError(e));
      } finally {
        setLoading(false);
        setIsProcessing(false);
      }
      return;
    }

    setRedacting(true);
    setIsProcessing(true);
    cancelRequestedRef.current = false;
    setCancelPending(false);
    // Single-document mode uses the Save As choice (folder + filename);
    // folder mode uses the radio buttons (folder only).
    const chosenFolder = isFileMode
      ? (savePath ? dirname(savePath) : null)
      : (outputMode === 'custom' && customPath ? customPath : null);
    const chosenFilename = isFileMode && savePath ? basename(savePath) : null;
    const resolvedOutputPath = chosenFolder ?? joinPath(folderPath, outputSubfolder);
    setLastOutputPath(resolvedOutputPath);
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

      const common = {
        folder_path: folderPath,
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
        redact_header_footer: redactHeaderFooter,
        documents: detectionResults.documents.map((d) => d.path),
        selected_keys: selectedKeys,
        folder_action: null,
        custom_output_path: chosenFolder,
        custom_output_filename: chosenFilename,
      };

      if (isDeidentify) {
        const results = await api.deidentify({
          ...common,
          person_roles: personRoles,
          person_custom_labels: personCustomLabels,
          ignored_people: ignoredPeople,
        });
        if (results.cancelled) {
          setPartialFiles(
            results.document_results
              .map((d) => d.output_path || d.quarantine_path)
              .filter((p): p is string => Boolean(p))
          );
          setDeidentifyResults(results);
          setCancelled(true);
          return;
        }
        setDeidentifyResults(results);
        goToCompletionIfStillHere();
        return;
      }

      const results = await api.redact({
        ...common,
        detected_pii: Object.fromEntries(
          detectionResults.documents.map((d) => [d.path, d.matches])
        ),
      });

      // Trust the backend's authoritative signal, NOT whether Cancel was
      // clicked: if the run finished before the flag was seen (or the cancel
      // POST failed), results.cancelled is false and every document completed —
      // those are valid, complete redactions, so fall through to completion
      // rather than mislabelling them as partial output the user should delete.
      if (results.cancelled) {
        // The backend stopped between documents, so its results ARE the
        // accurate partial-output list — no directory guessing needed.
        // Quarantined (.UNVERIFIED.pdf) files have no output_path, so include
        // quarantine_path or they'd be invisible to "Delete partial output".
        setPartialFiles(
          results.document_results
            .map((d) => d.output_path || d.quarantine_path)
            .filter((p): p is string => Boolean(p))
        );
        setRedactionResults(results);
        setCancelled(true);
        return;
      }

      setRedactionResults(results);
      goToCompletionIfStillHere();
    } catch (e: any) {
      if (cancelRequestedRef.current) {
        // Cancel was requested but the request itself failed — fall back to
        // listing whatever redaction outputs exist on disk.
        try {
          const list = await api.cleanupList(resolvedOutputPath);
          setPartialFiles(list.files);
        } catch {
          setPartialFiles([]);
        }
        setCancelled(true);
      } else {
        if (/no cached detection data/i.test(e?.message ?? '')) {
          // Server-side cache is gone — force a fresh detection run next time
          // (see Task 6; without this the wizard can loop forever).
          useStore.getState().setDetectionParamsKey('');
        }
        setError(friendlyError(e));
      }
    } finally {
      setRedacting(false);
      setIsProcessing(false);
    }
  };

  if (cancelled) {
    const isLoading = partialFiles === null;
    const fileCount = partialFiles?.length ?? 0;
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Cancelled</h2>
          <p className="text-sm text-slate-400 mt-1">
            {isLoading
              ? "Checking what was written..."
              : fileCount === 0
              ? `${isDeidentify ? 'De-identification' : 'Redaction'} was cancelled before any files were written.`
              : `${fileCount} file${fileCount === 1 ? '' : 's'} ${fileCount === 1 ? 'was' : 'were'} ${isDeidentify ? 'de-identified' : 'redacted'} before stopping.`}
          </p>
        </div>

        {!isLoading && fileCount > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-2">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Partial output</p>
            <ul className="text-xs text-slate-500 space-y-0.5 max-h-48 overflow-y-auto">
              {partialFiles.map((f) => <li key={f}>{basename(f)}</li>)}
            </ul>
          </div>
        )}

        {cleanupDone && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2.5 text-sm text-emerald-700">
            Partial output deleted.
          </div>
        )}

        <div className="flex flex-wrap gap-2 pt-2">
          <button
            onClick={async () => {
              try { await api.openFolder(lastOutputPath); }
              catch (e) { setError(friendlyError(e)); }
            }}
            disabled={fileCount === 0}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors btn-press"
          >
            <FolderOpen size={14} /> Open output folder
          </button>

          <button
            onClick={async () => {
              setCleaningUp(true);
              try {
                await api.cleanup(lastOutputPath, partialFiles!);
                setPartialFiles([]);
                setCleanupDone(true);
              } catch (e: any) {
                setError(friendlyError(e));
              } finally {
                setCleaningUp(false);
              }
            }}
            disabled={fileCount === 0 || cleaningUp}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors btn-press"
          >
            <Trash2 size={14} /> {cleaningUp ? 'Deleting...' : 'Delete partial output'}
          </button>

          <button
            onClick={() => {
              setCancelled(false);
              setPartialFiles(null);
              setCleanupDone(false);
              navigateTo('document_review');
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors btn-press ml-auto"
          >
            Done
          </button>
        </div>
      </div>
    );
  }

  // Show dedicated redaction progress screen with witty comments
  if (redacting) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <RedactionProgress totalDocuments={detectionResults.documents.length} isDeidentify={isDeidentify} />
        <div className="mt-8">
          <button
            onClick={async () => {
              if (cancelPending) return;
              if (!confirm(`Stop after the current document finishes? Documents already ${isDeidentify ? 'de-identified' : 'redacted'} will remain in the output folder.`)) {
                return;
              }
              cancelRequestedRef.current = true;
              setCancelPending(true);
              try {
                await api.cancelRedaction();
              } catch {
                // The backend may have already finished — the in-flight redact
                // response will resolve normally and we handle it there.
              }
            }}
            disabled={cancelPending}
            className="px-4 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors btn-press"
          >
            {cancelPending ? 'Stopping after current document…' : 'Cancel'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Final Confirmation</h2>
        <p className="text-sm text-slate-400 mt-1">
          {isPaste
            ? (isDeidentify
                ? 'Review your selections before de-identifying your text.'
                : 'Review your selections before blacking out your text.')
            : isDeidentify
            ? 'Review your selections before creating the de-identified text files.'
            : 'Review your selections before creating redacted documents.'}
        </p>
      </div>

      {/* Summary metrics */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="grid grid-cols-2 gap-4"
      >
        <div className="bg-white rounded-xl border border-slate-200 p-5 text-center">
          <p className="text-3xl font-semibold text-primary-600">{totalSelected}</p>
          <p className="text-xs text-slate-400 mt-1 uppercase tracking-wide">
            {isDeidentify ? 'Items to Replace' : 'Items to Redact'}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-5 text-center">
          <p className="text-3xl font-semibold text-slate-700">
            {isPaste ? pastedWordCount : detectionResults.documents.length}
          </p>
          <p className="text-xs text-slate-400 mt-1 uppercase tracking-wide">
            {isPaste ? 'Words' : 'Documents'}
          </p>
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
                  <span className="text-slate-600">{friendlyCategory(category)}</span>
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

      {/* Output Folder — a paste has no output folder and nothing is written
          until the user chooses to save it on the completion screen. */}
      {!isPaste && (
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-white rounded-xl border border-slate-200 p-5"
      >
        <div className="flex items-center gap-2 mb-4">
          {isFileMode
            ? <FileText size={16} className="text-primary-500" />
            : <FolderOpen size={16} className="text-primary-500" />}
          <h3 className="text-sm font-medium text-slate-600">
            {isDeidentify
              ? (isFileMode ? 'Save De-identified Text As' : 'Save De-identified Files To')
              : (isFileMode ? 'Save Redacted Document As' : 'Save Redacted Files To')}
          </h3>
          <HelpTip
            text={isDeidentify
              ? "De-identified text files are saved separately — your original files are never modified. By default they go in a 'deidentified' folder inside your source folder."
              : "Redacted copies are saved separately — your original files are never modified. By default they go in a 'redacted' folder inside your source folder."}
          />
        </div>

        {isFileMode ? (
          <div className="space-y-3">
            <div className="flex items-start gap-3 p-3.5 rounded-lg border border-slate-100 bg-slate-50/60">
              <div className="flex-1 min-w-0">
                {savePath ? (
                  <>
                    <span className="text-sm text-slate-700 font-medium">Saving to your chosen location</span>
                    <code className="text-[11px] text-slate-500 mt-1.5 block break-all">{savePath}</code>
                  </>
                ) : (
                  <>
                    <span className="text-sm text-slate-700 font-medium">Default location</span>
                    <p className="text-xs text-slate-400 mt-0.5">
                      A <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-500">{outputSubfolder}</code> folder
                      inside the document's own folder. The filename has the student's details stripped out automatically.
                    </p>
                    <code className="text-[11px] text-slate-400 mt-1.5 block break-all">
                      {joinPath(folderPath, outputSubfolder)}
                    </code>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveAs}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-slate-200 bg-slate-50
                           text-sm text-slate-600 font-medium hover:bg-slate-100 hover:border-slate-300
                           transition-colors btn-press"
              >
                <Search size={14} />
                {savePath ? 'Change location or name' : 'Choose where to save...'}
              </button>
              {savePath && (
                <button
                  type="button"
                  onClick={() => setSavePath(null)}
                  className="text-xs text-slate-400 hover:text-slate-600 underline"
                >
                  Use the default instead
                </button>
              )}
            </div>
          </div>
        ) : (
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
                A <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-500">{outputSubfolder}</code> subfolder
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
                Save the {isDeidentify ? 'de-identified' : 'redacted'} files to any folder on your computer
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
        )}
      </motion.section>
      )}

      {/* Warning */}
      <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
        <ShieldCheck size={18} className="text-emerald-500 shrink-0 mt-0.5" />
        <p className="text-sm text-emerald-700">
          {isPaste ? (
            <>Nothing is saved automatically. On the next screen you can copy your
            cleaned text, or save it to a file yourself.</>
          ) : (
            <>Your original files will <span className="font-medium">not</span> be modified.{' '}
            {isDeidentify ? 'De-identified text files' : 'Redacted copies'} will be created in the output folder above.</>
          )}
        </p>
      </div>

      {isDeidentify && nothingSelected && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertTriangle size={18} className="text-red-500 shrink-0 mt-0.5" />
          <p className="text-sm text-red-700">
            Nothing is selected, so <span className="font-medium">nothing will be replaced</span>.
            You will get the document&apos;s text exactly as it is. Read it before
            sharing it or pasting it into an AI tool.
          </p>
        </div>
      )}

      {isDeidentify && (
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          <Bot size={18} className="text-amber-500 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-700">
            {isPaste ? (
              <>A name key will also be shown on the next screen, so you can turn
              the labels back into names later. Keep it private — never paste it
              into an AI tool.</>
            ) : (
              <>A private key file will also be saved <span className="font-medium">with your originals</span>,
              so you can turn the labels back into names later. It is kept out of the output
              folder on purpose — never upload it.</>
            )}
          </p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button
          onClick={() => navigateTo(backTarget)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors btn-press"
        >
          <ArrowLeft size={16} /> Back
        </button>

        <div className="flex gap-2">
          <button
            onClick={handleRedact}
            disabled={!canProceed}
            className={`
              flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all
              ${canProceed
                ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow btn-press'
                : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }
            `}
          >
            {isDeidentify ? <Bot size={16} /> : <ShieldCheck size={16} />}
            {isPaste
              ? (isDeidentify ? 'De-identify My Text' : 'Black Out My Text')
              : isDeidentify
              ? `Create De-identified ${isFileMode ? 'File' : 'Files'}`
              : `Create Redacted ${isFileMode ? 'Document' : 'Documents'}`}
          </button>
        </div>
      </div>
    </div>
  );
}
