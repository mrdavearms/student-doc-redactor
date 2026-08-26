import type { CleanTextResult } from '../types';

/**
 * The half of a clean result that carries REAL NAMES: key entries, ambiguity
 * notes, and the NER sweep's leftover warnings.
 *
 * Deliberately module-level rather than Zustand state. CLAUDE.md rule 24
 * establishes the precedent — preview images stay out of the store so they die
 * with the component. These names must never persist across screens, reach
 * disk, or appear in the audit log.
 */
type Sensitive = Pick<
  CleanTextResult, 'key_entries' | 'ambiguity_notes' | 'leftover_name_warnings'
>;

let held: Sensitive | null = null;

export function holdSensitive(r: Sensitive) {
  held = {
    key_entries: r.key_entries,
    ambiguity_notes: r.ambiguity_notes,
    leftover_name_warnings: r.leftover_name_warnings,
  };
}

/** Read without consuming — React may render a component twice in StrictMode. */
export function peekSensitive(): Sensitive {
  return held ?? { key_entries: [], ambiguity_notes: [], leftover_name_warnings: [] };
}

export function clearSensitive() {
  held = null;
}
