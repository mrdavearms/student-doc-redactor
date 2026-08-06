/**
 * Suggests the output filename shown in the Save As dialog for a single
 * document.
 *
 * This is a hint only — when the user does NOT choose their own filename the
 * backend generates the real one with strip_pii_from_filename(), which knows
 * about name variations and nicknames this cannot see. Keep them roughly in
 * step, but the backend stays authoritative.
 */

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function suggestDeidentifiedFilename(rawStem: string, names: string[]): string {
  return suggestRedactedFilename(rawStem, names)
    .replace(/_redacted\.pdf$/, '_deidentified.txt');
}

export function suggestRedactedFilename(rawStem: string, names: string[]): string {
  // Underscores → spaces so word boundaries work on "Surname_First_Report"
  let result = rawStem.replace(/_/g, ' ');

  // Full names first, then their individual words, longest first — so
  // "Joe Bloggs" goes before "Joe" and no orphaned fragments are left behind.
  const variations = names
    .flatMap((n) => [n, ...n.split(/\s+/)])
    .map((s) => s.trim())
    .filter((s) => s.length >= 3)
    .sort((a, b) => b.length - a.length);

  for (const variation of variations) {
    result = result.replace(new RegExp(`\\b${escapeRegExp(variation)}\\b`, 'gi'), '');
  }

  result = result
    .replace(/['’]s\b/gi, '')
    .replace(/\(\s*\)/g, '')
    .replace(/\[\s*\]/g, '')
    .replace(/ {2,}/g, ' ')
    .replace(/(\s*-\s*){2,}/g, ' - ')
    .trim()
    .replace(/^[-\s]+|[-\s]+$/g, '');

  if (result.length < 3) result = 'document';

  return `${result}_redacted.pdf`;
}
