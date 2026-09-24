import type { DetectionResults, FailedDocument } from '../types';
import { friendlyDocumentError } from './errorMessage';

/**
 * True when detection read none of the documents it was given. The wizard
 * must not go on to "nothing to redact" in that case — that screen would call
 * an unread folder clean.
 */
export function allDocumentsFailed(results: DetectionResults): boolean {
  return results.documents.length === 0 && results.failed_documents.length > 0;
}

/** One sentence naming every file detection could not read. */
export function failedDocumentsMessage(failed: FailedDocument[]): string {
  const names = failed.map((f) => f.filename).join(', ');
  return failed.length === 1
    ? `${names} could not be scanned: ${friendlyDocumentError(failed[0].reason)}`
    : `None of the documents could be scanned (${names}). Check the files open normally and try again.`;
}
