import type { DetectionResults } from '../types';

export interface DocumentSummaryMeta {
  counts: Record<string, number>;
  hasMedium: boolean;
}

/**
 * Per-document category counts of the SELECTED items, keyed by document path.
 *
 * Keyed by path, never by filename: Report.docx (converted to Report.pdf) and
 * Report.pdf in one folder share a filename, and keying on it merged their
 * completion cards into one. The redaction results carry `source_path` for
 * exactly this lookup.
 */
export function selectedCountsByPath(
  detectionResults: DetectionResults,
  userSelections: Record<string, boolean>,
): Map<string, DocumentSummaryMeta> {
  const meta = new Map<string, DocumentSummaryMeta>();
  for (const doc of detectionResults.documents) {
    const counts: Record<string, number> = {};
    let hasMedium = false;
    doc.matches.forEach((match, idx) => {
      if (userSelections[`${doc.path}_${idx}`]) {
        counts[match.category] = (counts[match.category] || 0) + 1;
        if (match.confidence_label === 'medium' || match.confidence_label === 'low') {
          hasMedium = true;
        }
      }
    });
    meta.set(doc.path, { counts, hasMedium });
  }
  return meta;
}
