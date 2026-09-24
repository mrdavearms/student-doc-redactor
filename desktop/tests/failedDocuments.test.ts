import { describe, it, expect } from 'vitest';
import { allDocumentsFailed, failedDocumentsMessage } from '../src/lib/failedDocuments';
import type { DetectionResults } from '../src/types';

const results = (docs: number, failed: string[]): DetectionResults => ({
  documents: new Array(docs).fill(null).map((_, i) => ({
    path: `/r/${i}.pdf`, filename: `${i}.pdf`, matches: [], ocr_pages: [],
  })),
  total_matches: 0,
  failed_documents: failed.map((f) => ({ path: `/r/${f}`, filename: f, reason: 'Error extracting text from PDF: cannot open' })),
});

describe('allDocumentsFailed', () => {
  it('is true only when nothing was scanned and something failed', () => {
    expect(allDocumentsFailed(results(0, ['a.pdf']))).toBe(true);
    // One readable document is enough to review; the failure is shown beside it.
    expect(allDocumentsFailed(results(1, ['a.pdf']))).toBe(false);
    // An empty folder is not a failure.
    expect(allDocumentsFailed(results(0, []))).toBe(false);
  });
});

describe('failedDocumentsMessage', () => {
  it('names the file and gives a friendly reason for one failure', () => {
    const msg = failedDocumentsMessage(results(0, ['Billy Bob report.pdf']).failed_documents);
    expect(msg).toContain('Billy Bob report.pdf could not be scanned');
    expect(msg).not.toContain('Error extracting text');
  });

  it('names every file when several fail', () => {
    const msg = failedDocumentsMessage(results(0, ['a.pdf', 'b.pdf']).failed_documents);
    expect(msg).toContain('a.pdf, b.pdf');
  });
});
