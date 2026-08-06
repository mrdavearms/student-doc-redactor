import { BackendUnreachableError } from '../api';
import { recordRawError, sanitiseForReport } from './faultReport';

const PATTERNS: Array<[RegExp, string]> = [
  [/folder not found/i, "That folder couldn't be found. Check the path and try again."],
  [/file not found/i, "That file couldn't be opened. It may have been moved, renamed, or deleted."],
  [/no cached detection data/i, "The detection step needs to run again. Please go back one step and try again."],
  [/cannot open pdf/i, "One of the PDFs couldn't be read. It may be corrupted or password-protected."],
  [/manual pii text must be at least 3 characters/i, "That's too short to redact reliably — please enter at least 3 characters."],
  [/does not exist in this document/i, "That document doesn't have that many pages. Check the page number and try again."],
  [/page \d+ out of range/i, "Couldn't load that page from the PDF."],
  [/detection failed/i, "Something went wrong while detecting personal information. Please try that step again."],
  [/folder processing failed/i, "Something went wrong while processing that folder. Please try again."],
  [/file processing failed/i, "Something went wrong while preparing that document. Please try again."],
  [/redaction failed/i, "Something went wrong while redacting the documents. Please try again."],
  [/de-identification failed/i, "Something went wrong while de-identifying the documents. Please try again."],
  [/reading people failed/i, "Something went wrong while working out who's who. Please go back one step and try again."],
  [/label preview failed/i, "Couldn't preview the labels — your choices are still saved."],
  [/no extracted text available/i, "That document's text couldn't be read. Please go back one step and try again."],
  [/api token/i, "The app couldn't authenticate with its redaction engine. Please restart the app."],
  [/permission denied|errno 13|winerror 32|being used by another process/i,
    "The file couldn't be written — it may be open in another program (like Adobe Reader or Word). Close it there and try again."],
  [/too large to preview/i, "This file is too large to preview in the app — open it from the output folder instead."],
  [/outside the output folder|not a de-identified output file/i,
    "That file can't be opened from here. Use the output folder instead."],
];

const FALLBACK = "Something went wrong. Please try again, or restart the app if this keeps happening.";
const BACKEND_DOWN = "The redaction engine isn't responding. Please restart the app.";

/**
 * Per-document error text (shown on completion cards). Service-authored
 * messages are already teacher-friendly, so unmatched strings pass through
 * with paths stripped — unlike friendlyError, which falls back to a generic.
 */
export function friendlyDocumentError(raw: string | null): string {
  if (!raw) return 'Processing did not complete.';
  for (const [re, msg] of PATTERNS) {
    if (re.test(raw)) return msg;
  }
  return sanitiseForReport(raw);
}

export function friendlyError(err: unknown): string {
  if (err instanceof BackendUnreachableError) {
    recordRawError('Backend not reachable');
    return BACKEND_DOWN;
  }
  const raw = err instanceof Error ? err.message : String(err);
  // Recorded for the "Report this problem" email — sanitised before use.
  recordRawError(raw);
  for (const [re, msg] of PATTERNS) {
    if (re.test(raw)) return msg;
  }
  return FALLBACK;
}
