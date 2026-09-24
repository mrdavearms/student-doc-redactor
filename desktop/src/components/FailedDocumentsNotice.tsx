import { XCircle } from 'lucide-react';
import type { FailedDocument } from '../types';
import { friendlyDocumentError } from '../lib/errorMessage';

/**
 * Documents detection could not read. They are not in the review list and
 * will not be in the output, so the user is told here rather than finding a
 * file missing from the redacted folder later.
 */
export default function FailedDocumentsNotice({ failed }: { failed: FailedDocument[] }) {
  if (failed.length === 0) return null;
  return (
    <div className="w-full bg-red-50 border border-red-200 rounded-xl p-5 text-left">
      <div className="flex items-center gap-2 text-sm font-medium text-red-700 mb-2">
        <XCircle size={16} />
        {failed.length} document{failed.length === 1 ? '' : 's'} could not be scanned
      </div>
      <p className="text-xs text-red-600 mb-3">
        These files were skipped. They are not in the review below and no output
        will be produced for them — do not share them until they have been checked.
      </p>
      {failed.map((f) => (
        <p key={f.path} className="text-xs text-red-500 py-0.5">
          {f.filename}: {friendlyDocumentError(f.reason)}
        </p>
      ))}
    </div>
  );
}
