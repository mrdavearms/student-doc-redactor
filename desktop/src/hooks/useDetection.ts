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

  const abortDetection = () => {
    abortRef.current?.abort();
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
      if (!ctrl.signal.aborted) setLoading(false);
    }
  };

  return { runDetection, abortDetection };
}
