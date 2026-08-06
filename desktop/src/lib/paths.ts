/**
 * Small cross-platform path helpers for the renderer.
 *
 * Node's `path` is not available here and the app runs on both macOS and
 * Windows, so these treat "/" and "\" as separators interchangeably and
 * preserve whichever one the incoming path used.
 */

const SEP_RE = /[\\/]/;

/** The separator used by a path — backslash only if it has no forward slashes. */
export function separatorFor(path: string): string {
  return path.includes('/') || !path.includes('\\') ? '/' : '\\';
}

/** Last segment of a path ("/a/b/c.pdf" → "c.pdf"). */
export function basename(path: string): string {
  const parts = path.split(SEP_RE);
  return parts[parts.length - 1] || path;
}

/** Everything before the last segment ("/a/b/c.pdf" → "/a/b"). */
export function dirname(path: string): string {
  const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  if (idx < 0) return '';
  // Keep the root slash for paths like "/file.pdf"
  if (idx === 0) return path.slice(0, 1);
  const head = path.slice(0, idx);
  // "D:\report.pdf" must yield "D:\", not "D:" — a bare drive letter is a
  // drive-RELATIVE reference on Windows (whatever that drive's cwd happens to
  // be), not the drive root.
  if (/^[A-Za-z]:$/.test(head)) return path.slice(0, idx + 1);
  return head;
}

/** Filename without its extension ("report.pdf" → "report"). */
export function stem(filename: string): string {
  const name = basename(filename);
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

/**
 * True when two paths point at the same file.
 *
 * Separator style is normalised and the comparison is case-insensitive,
 * because this app ships on macOS and Windows — both of which have
 * case-insensitive filesystems by default, so "Report.pdf" and "report.pdf"
 * in the same folder are the same file. This is a UI-level check only; the
 * backend enforces the same rule authoritatively with os.path.samefile.
 */
export function isSamePath(a: string, b: string): boolean {
  const normalise = (p: string) =>
    p.replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLowerCase();
  return Boolean(a) && Boolean(b) && normalise(a) === normalise(b);
}

/** Join segments using the separator style of the first one. */
export function joinPath(base: string, ...segments: string[]): string {
  const sep = separatorFor(base);
  const trimmed = base.replace(/[\\/]+$/, '');
  return [trimmed, ...segments].join(sep);
}
