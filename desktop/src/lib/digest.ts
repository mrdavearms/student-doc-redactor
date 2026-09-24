/**
 * A short, stable digest of a string, for fingerprinting inputs without
 * keeping a copy of them (FNV-1a, 32-bit, plus the length).
 *
 * Not cryptographic — it only has to change when the text changes, so a
 * re-run can be skipped when nothing did. Synchronous on purpose: the
 * fingerprint is built inside a plain function, not an async one.
 */
export function digest(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `${hash.toString(16)}:${text.length}`;
}
