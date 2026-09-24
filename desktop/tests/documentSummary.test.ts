import { describe, it, expect } from 'vitest';
import { selectedCountsByPath } from '../src/lib/documentSummary';
import type { DetectionResults, PIIMatch } from '../src/types';

function match(overrides: Partial<PIIMatch> = {}): PIIMatch {
  return {
    text: 'Billy Bob', category: 'Student name', confidence: 0.95,
    confidence_label: 'high', page_num: 1, line_num: 1, context: 'Billy Bob',
    source: 'regex', bbox: null, ...overrides,
  };
}

describe('selectedCountsByPath', () => {
  // Report.docx is converted to <temp>/001/Report.pdf, so it and a native
  // Report.pdf in the same folder share a filename. Keying by filename gave
  // them one completion card between them.
  it('keeps two documents with the same filename apart', () => {
    const results: DetectionResults = {
      documents: [
        { path: '/tmp/conv/001/Report.pdf', filename: 'Report.pdf', ocr_pages: [],
          matches: [match(), match({ category: 'Phone number', confidence_label: 'medium' })] },
        { path: '/Users/dave/reports/Report.pdf', filename: 'Report.pdf', ocr_pages: [],
          matches: [match()] },
      ],
      total_matches: 3,
    };
    const selections = {
      '/tmp/conv/001/Report.pdf_0': true,
      '/tmp/conv/001/Report.pdf_1': true,
      '/Users/dave/reports/Report.pdf_0': true,
    };
    const meta = selectedCountsByPath(results, selections);
    expect(meta.size).toBe(2);
    expect(meta.get('/tmp/conv/001/Report.pdf')).toEqual({
      counts: { 'Student name': 1, 'Phone number': 1 }, hasMedium: true,
    });
    expect(meta.get('/Users/dave/reports/Report.pdf')).toEqual({
      counts: { 'Student name': 1 }, hasMedium: false,
    });
  });

  it('counts only the selected items', () => {
    const results: DetectionResults = {
      documents: [{ path: 'C:\\reports\\a.pdf', filename: 'a.pdf', ocr_pages: [],
        matches: [match(), match({ category: 'Email address' })] }],
      total_matches: 2,
    };
    const meta = selectedCountsByPath(results, { 'C:\\reports\\a.pdf_0': true, 'C:\\reports\\a.pdf_1': false });
    expect(meta.get('C:\\reports\\a.pdf')).toEqual({ counts: { 'Student name': 1 }, hasMedium: false });
  });
});
