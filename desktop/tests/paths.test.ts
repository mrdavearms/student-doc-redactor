import { describe, it, expect } from 'vitest';
import { dirname, basename } from '../src/lib/paths';
import { friendlyDocumentError } from '../src/lib/errorMessage';

describe('paths on Windows-style input', () => {
  it('basename splits backslash paths', () => {
    expect(basename('C:\\Users\\dave\\Report_redacted.pdf')).toBe('Report_redacted.pdf');
  });

  it('dirname keeps the separator on a drive root', () => {
    // "D:" alone is drive-RELATIVE on Windows, not the drive root.
    expect(dirname('D:\\report.pdf')).toBe('D:\\');
  });

  it('dirname of a normal windows path drops the filename only', () => {
    expect(dirname('C:\\Users\\dave\\report.pdf')).toBe('C:\\Users\\dave');
  });

  it('dirname of a posix root file returns /', () => {
    expect(dirname('/report.pdf')).toBe('/');
  });
});

describe('friendlyDocumentError', () => {
  it('maps a Windows file-lock error to plain advice', () => {
    const out = friendlyDocumentError(
      "Error during redaction: [Errno 13] Permission denied: 'C:\\\\x\\\\Report_redacted.pdf'");
    expect(out).toMatch(/open in another program/i);
    expect(out).not.toContain('Errno');
  });

  it('passes service-authored friendly messages through untouched', () => {
    const msg = 'Cannot save the redacted copy over the original document. ' +
                'Choose a different filename or folder.';
    expect(friendlyDocumentError(msg)).toBe(msg);
  });

  it('strips paths from unrecognised raw errors', () => {
    const out = friendlyDocumentError('mystery failure at /Users/x/Billy Bob.pdf');
    expect(out).not.toContain('Billy');
  });

  it('null becomes a generic line', () => {
    expect(friendlyDocumentError(null)).toMatch(/did not complete/i);
  });
});
