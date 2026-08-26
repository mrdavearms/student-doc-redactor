import { useEffect, useRef } from 'react';
import { RefreshCw, ArrowLeft } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { useDetection } from '../hooks/useDetection';

/**
 * Step 2 for pasted text — the paste pathway's counterpart to ConversionStatus.
 *
 * There is nothing to convert, but the step is NOT skipped: a skipped step
 * would need a third auto-advance stamp alongside autoAdvancedKey and
 * peopleAutoSkippedKey, which is the forward-bounce trap those two were split
 * apart to avoid. Detection runs on mount and navigates itself — this screen
 * has no auto-advance logic of its own.
 */
export default function TextScan() {
  const { pastedText, navigateTo, loading } = useStore();
  const { runDetection, abortDetection } = useDetection();
  const started = useRef(false);

  useEffect(() => {
    if (started.current || !pastedText.trim()) return;
    started.current = true;
    void runDetection({
      fingerprint: { paste: pastedText },
      // This is the copy shown in Layout's full-screen loading overlay — the
      // only thing visible while this runs, since the overlay blurs the page
      // behind it. The first scan of a session also loads the language model
      // (rule 37, measured ~7s on top of detection itself), and this is the
      // screen where a user will notice that most, so the wait is named here
      // rather than left to look like a freeze.
      message: 'Reading your text and looking for personal information. '
        + "The first scan after opening the app takes about 7 seconds longer "
        + "while the language model loads — that's expected, not a freeze.",
      run: (names, signal) =>
        api.detectText({ text: pastedText, ...names }, { signal }),
    });
    // Deliberately no cleanup / no return of abortDetection here. React
    // StrictMode double-invokes this effect in dev (mount → cleanup →
    // mount) on the SAME component instance, so `started` would already be
    // true on the simulated remount. A cleanup that aborts would cancel the
    // real request kicked off a moment earlier, and the `started` guard
    // would then block the remount's setup from starting it again — leaving
    // this screen stuck on "Scanning" until a manual reload. The Back button
    // below is the only real way to leave this screen, and it already calls
    // abortDetection() itself before navigating.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Scanning your text</h2>
        <p className="text-sm text-slate-400 mt-1">
          {loading
            ? 'Reading your text and looking for personal information.'
            : 'Scan finished.'}
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-3 text-sm text-slate-500 bg-white rounded-xl border border-slate-200 p-5">
          <RefreshCw size={16} className="animate-spin text-primary-500" />
          Scanning…
        </div>
      )}

      <div className="pt-2">
        <button
          onClick={() => { abortDetection(); navigateTo('folder_selection'); }}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <ArrowLeft size={16} /> Back
        </button>
      </div>
    </div>
  );
}
