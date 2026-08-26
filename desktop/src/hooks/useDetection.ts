import { useRef } from 'react';
import { useStore } from '../store';
import { friendlyError } from '../lib/errorMessage';
import type { DetectionResults } from '../types';

export interface DetectionSource {
  /** Distinguishes what is being scanned; folded into the fingerprint. */
  fingerprint: Record<string, unknown>;
  /** Performs the detect call. */
  run: (names: {
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, signal: AbortSignal) => Promise<DetectionResults>;
  /** Loading-overlay text. */
  message: string;
}

/**
 * Fingerprint-aware PII detection, extracted verbatim from
 * ConversionStatus.handleContinue so a future pasted-text pathway can reuse
 * it.
 *
 * The fingerprint is what makes it safe to skip re-detection: matching
 * inputs mean the backend cache still holds the same run, so review
 * decisions and manually added items survive (CLAUDE.md rule 41).
 * ConversionStatus keeps its own auto-advance logic and its own
 * AbortController for the conversion (folder/file processing) request —
 * that trap is local to it (rule 38) and this hook does not touch it.
 */
export function useDetection() {
  const abortRef = useRef<AbortController | null>(null);
  const {
    studentName, parentNames, familyNames, organisationNames,
    detectionResults, detectionParamsKey, userSelections,
    setDetectionResults, setDetectionParamsKey,
    setLoading, setError, navigateTo,
  } = useStore();

  // Cancels the in-flight detection request, if any, and clears the loading
  // flag it set. runDetection's own `finally` deliberately never clears
  // loading for an aborted request (see below) — an aborted request can't
  // tell whether it was superseded by a newer one that is still legitimately
  // showing the overlay (React StrictMode's dev-only double-invoke) or
  // whether this was a genuine cancel with nothing to follow it. This
  // function IS always the genuine-cancel case (a Back button or an
  // unmount), so it is the one place that can safely clear loading.
  //
  // Guarded to only clear loading when there was actually something of
  // ours in flight to cancel: `loading` is a single global flag shared by
  // unrelated callers elsewhere in the app (e.g. PreviewSection), so calling
  // this with no controller (detection never started) or an
  // already-aborted one (already cancelled once) must not blindly turn off
  // a loading state that may by now belong to something else entirely.
  const abortDetection = () => {
    const ctrl = abortRef.current;
    if (!ctrl || ctrl.signal.aborted) return;
    ctrl.abort();
    setLoading(false);
  };

  const runDetection = async (source: DetectionSource) => {
    const parentList = parentNames.split(',').map((n) => n.trim()).filter(Boolean);
    const familyList = familyNames.split(',').map((n) => n.trim()).filter(Boolean);
    const orgList = organisationNames.split(',').map((n) => n.trim()).filter(Boolean);

    const paramsKey = JSON.stringify({
      ...source.fingerprint,
      student: studentName.trim(),
      parents: parentList,
      family: familyList,
      orgs: orgList,
    });

    // Same inputs as the last successful run — reuse the existing results so
    // review decisions and manually added items survive. The backend cache is
    // only cleared by a NEW detect call, so redaction will still work.
    if (detectionResults && detectionParamsKey && paramsKey === detectionParamsKey) {
      const totalMatches = detectionResults.documents.reduce(
        (sum, d) => sum + d.matches.length, 0);
      navigateTo(totalMatches === 0 ? 'no_pii_found' : 'document_review');
      return;
    }

    // Inputs changed — re-detection will reset review work. Warn if any exists.
    if (detectionResults) {
      const hasReviewWork =
        Object.values(userSelections).some((v) => v === false) ||
        detectionResults.documents.some((d) =>
          d.matches.some((m) => m.source === 'manual'));
      if (hasReviewWork) {
        const proceed = confirm(
          'Your details have changed, so PII detection needs to run again. ' +
          'This will reset your review choices and remove any manually added items. Continue?'
        );
        if (!proceed) return;
      }
    }

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true, source.message);
    try {
      const detection = await source.run({
        student_name: studentName,
        parent_names: parentList,
        family_names: familyList,
        organisation_names: orgList,
      }, ctrl.signal);

      // If the user navigated away (Back) mid-request, do not force-navigate.
      if (ctrl.signal.aborted) return;

      setDetectionResults(detection);
      setDetectionParamsKey(paramsKey);
      const totalMatches = detection.documents.reduce((sum, d) => sum + d.matches.length, 0);
      if (totalMatches === 0) {
        navigateTo('no_pii_found');
      } else {
        navigateTo('document_review');
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') setError(friendlyError(e));
    } finally {
      // Deliberately skip clearing loading when THIS request was the one
      // aborted: abortDetection() (above) already cleared it for a genuine
      // cancel, and if this request was instead superseded by a newer one
      // (StrictMode's double-invoke), the newer request's own loading state
      // is still live and must not be stomped on here.
      if (!ctrl.signal.aborted) setLoading(false);
    }
  };

  return { runDetection, abortDetection };
}
