/**
 * Splitting a detection context into plain and matched segments.
 *
 * The regex engine wraps the matched value in markdown bold
 * (`pii_detector._get_context`) — a leftover from the Streamlit UI, which
 * rendered markdown. React renders text verbatim, so that shipped literal
 * asterisks to the user ("...Student: **Billy Bob**...").
 *
 * The NER path (`pii_orchestrator`) builds its context with no markers at all,
 * so the same list carries BOTH formats. This must therefore leave unmarked
 * text completely alone rather than assume every context is marked up.
 */

export interface ContextSegment {
  text: string;
  /** True when this segment is the detected value itself. */
  matched: boolean;
}

const MARKED = /\*\*([\s\S]+?)\*\*/g;

/**
 * Break `context` into segments, marking the parts the detector wrapped in
 * `**`. Returns a single unmatched segment when there are no markers.
 */
export function splitContext(context: string): ContextSegment[] {
  if (!context) return [];

  const segments: ContextSegment[] = [];
  let cursor = 0;

  for (const m of context.matchAll(MARKED)) {
    const start = m.index ?? 0;
    if (start > cursor) {
      segments.push({ text: context.slice(cursor, start), matched: false });
    }
    segments.push({ text: m[1], matched: true });
    cursor = start + m[0].length;
  }

  if (cursor < context.length) {
    segments.push({ text: context.slice(cursor), matched: false });
  }

  return segments;
}
