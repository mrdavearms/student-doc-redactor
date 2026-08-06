/**
 * Category policy for the review screen.
 *
 * "Select everything" is right for redaction — over-removal costs a black box —
 * and wrong for de-identification, where over-removal silently destroys the
 * content the AI needs, for zero privacy gain. The proof case: spaCy tags
 * "Working Memory" as ORGANIZATION, and default-selecting it turned a WISC
 * table into "[organisation]".
 *
 * A category is pre-unticked ONLY when a false positive is likelier than a
 * true one AND removal costs meaning.
 */

import type { DetectionResults, WorkflowMode } from '../types';

// Auto-discovered NER classes that must STAY pre-selected in both modes.
const NER_KEEP_SELECTED = new Set([
  'Person name (NER)',
  'Person name (NER variation)',
  // Unreachable today (PRESIDIO_SKIP_TYPES discards LOCATION upstream) but a
  // suburb IS identifying — keep the safe default in case that filter changes.
  'Location (NER)',
]);

export function isPreselected(category: string, mode: WorkflowMode): boolean {
  if (mode !== 'deidentify') return true;
  if (NER_KEEP_SELECTED.has(category)) return true;
  // ORGANIZATION (NER), NRP (NER), and any future auto-discovered fallback
  // class: low precision, high meaning-cost. The user opts IN to removing.
  return !/\(NER\)$/.test(category);
}

/**
 * Selection defaults for a detection run. Writes an explicit true OR false for
 * EVERY key — DocumentReview renders `userSelections[key] ?? true`, so an
 * omitted key would DISPLAY as ticked while submitting as unticked.
 */
export function buildDefaultSelections(
  results: DetectionResults,
  mode: WorkflowMode,
): Record<string, boolean> {
  const selections: Record<string, boolean> = {};
  for (const doc of results.documents) {
    doc.matches.forEach((match, idx) => {
      selections[`${doc.path}_${idx}`] = isPreselected(match.category, mode);
    });
  }
  return selections;
}

const FRIENDLY: Record<string, string> = {
  'ORGANIZATION (NER)': 'Possible organisation (auto-detected)',
  'NRP (NER)': 'Possible group or profession (auto-detected)',
  'Date/Time (NER)': 'Date or time (auto-detected)',
  'Location (NER)': 'Possible place name (auto-detected)',
  'Person name (NER)': 'Name (found automatically)',
  'Person name (NER variation)': 'Name variation (found automatically)',
};

/** Engine jargon → words a teacher can judge. Unknown categories pass through. */
export function friendlyCategory(category: string): string {
  return FRIENDLY[category] ?? category;
}
