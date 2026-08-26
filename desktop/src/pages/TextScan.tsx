import { useEffect, useState } from 'react';
import { RefreshCw, ArrowLeft } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { useDetection } from '../hooks/useDetection';

/**
 * What this screen actually knows happened, independent of the shared
 * `loading`/`error` store fields — those get cleared by any navigateTo(),
 * including a Back button press, so they cannot be trusted to still describe
 * THIS screen's scan by the time it renders. 'running' is the initial value
 * so a scan that is genuinely in progress is never mistaken for a finished
 * one on first paint.
 */
type ScanStatus = 'running' | 'succeeded' | 'declined' | 'no_text' | 'failed';

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
  const [status, setStatus] = useState<ScanStatus>('running');

  useEffect(() => {
    if (!pastedText.trim()) { setStatus('no_text'); return; }
    setStatus('running');
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
    }).then((outcome) => {
      // 'ran'/'reused' navigate this screen away already; 'aborted' means a
      // newer request or an unmount has taken over, so there is nothing of
      // ours left to report. Only 'declined' and 'failed' leave the user
      // sitting on this screen with nothing having happened — those are the
      // two cases this screen must describe truthfully instead of assuming
      // "Scan finished."
      if (outcome === 'declined') setStatus('declined');
      else if (outcome === 'failed') setStatus('failed');
    });
    // Standard AbortController-on-unmount pattern: cancel whatever request
    // this effect started. There is no `started` ref guarding the call above
    // — with one, React StrictMode's dev-only double-invoke (mount → cleanup
    // → mount, same instance) would abort the request the first setup just
    // started and then the guard would block the second setup from starting
    // a replacement, leaving the screen stuck on "Scanning" forever. Without
    // the guard, the first (aborted) call's own `ctrl` sees itself aborted
    // and quietly no-ops (useDetection ignores AbortError and skips clearing
    // loading for a signal that isn't the live one); the second call is the
    // one that actually completes and navigates.
    //
    // The cleanup is not just a StrictMode nicety: `Sidebar.tsx`'s "change
    // pathway" link calls navigateTo() directly whenever a redaction/
    // de-identify run isn't in flight, which is true for the whole span of
    // this screen's detection. Without this cleanup, clicking it while a
    // scan is still running would unmount this screen with nothing to cancel
    // the fetch — when it later resolved, useDetection would still write the
    // results into the store and navigate, yanking the user away from
    // wherever they'd gone in the meantime.
    return abortDetection;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Driven by `status`, not the shared `loading`/`error` store fields — those
  // are cleared by any navigateTo() (including this screen's own Back
  // button), so they cannot reliably describe what THIS mount's scan did.
  // `status` starts at 'running' and is only ever updated from the settled
  // outcome of the detection call this screen itself started (see the effect
  // above), so it can't claim a scan finished when one never ran.
  const subtitle = loading
    ? 'Reading your text and looking for personal information.'
    : status === 'failed'
      ? 'The scan could not finish. See the message above, or go back and try again.'
      : status === 'declined'
        ? "No scan was run — you chose not to re-scan after changing your details. Go back to review them, or try again to re-scan."
        : status === 'no_text'
          ? "There's no text to scan. Go back and paste some text first."
          : 'Scan finished.';

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Scanning your text</h2>
        <p className="text-sm text-slate-400 mt-1">{subtitle}</p>
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
