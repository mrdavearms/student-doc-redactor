import { BackendUnreachableError } from '../api';

const PATTERNS: Array<[RegExp, string]> = [
  [/folder not found/i, "That folder couldn't be found. Check the path and try again."],
  [/file not found/i, "One of the files couldn't be opened. It may have been moved or deleted since the folder was scanned."],
  [/no cached detection data/i, "The detection step needs to run again. Please go back one step and try again."],
  [/cannot open pdf/i, "One of the PDFs couldn't be read. It may be corrupted or password-protected."],
  [/page \d+ out of range/i, "Couldn't load that page from the PDF."],
];

const FALLBACK = "Something went wrong. Please try again, or restart the app if this keeps happening.";
const BACKEND_DOWN = "The redaction engine isn't responding. Please restart the app.";

export function friendlyError(err: unknown): string {
  if (err instanceof BackendUnreachableError) return BACKEND_DOWN;
  const raw = err instanceof Error ? err.message : String(err);
  for (const [re, msg] of PATTERNS) {
    if (re.test(raw)) return msg;
  }
  return FALLBACK;
}
