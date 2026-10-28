import { describe, it, expect } from 'vitest';
import { ocrWarningLine } from '../src/lib/ocrWarningLine';

describe('ocrWarningLine', () => {
  it('states the number of items on scanned pages', () => {
    expect(ocrWarningLine('report.pdf', 3)).toBe('report.pdf: 3 item(s) on image-only pages');
  });
  it('never says "0 item(s)" for a scanned-page warning with no item on it', () => {
    expect(ocrWarningLine('report.pdf', 0)).toBe('report.pdf: has scanned pages to check');
  });
});
