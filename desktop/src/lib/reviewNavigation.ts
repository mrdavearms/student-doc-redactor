/**
 * Which document the review screen's Previous / Next buttons should go to.
 *
 * Documents with no matches are skipped in both directions. Previous used to
 * fall back to "one step back" when no earlier document had matches; the
 * mount effect then auto-skipped forward again, so the button bounced back
 * to the same document — and the remount wiped the "Add a missed item" form.
 * Returning null lets the screen hide the button instead.
 */
export function previousDocWithMatches(
  documents: { matches: unknown[] }[],
  from: number,
): number | null {
  for (let i = from - 1; i >= 0; i--) {
    if (documents[i].matches.length > 0) return i;
  }
  return null;
}
