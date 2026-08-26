import { describe, it, expect } from 'vitest';
import { friendlyError } from '../src/lib/errorMessage';
import { BackendUnreachableError } from '../src/api';

describe('friendlyError', () => {
  it('maps BackendUnreachableError to the engine-down message', () => {
    expect(friendlyError(new BackendUnreachableError()))
      .toMatch(/redaction engine isn't responding/i);
  });

  it('maps "Folder not found" to a friendly message', () => {
    expect(friendlyError(new Error('Folder not found: /tmp/x')))
      .toMatch(/folder couldn't be found/i);
  });

  it('maps "File not found" to a file-moved message', () => {
    expect(friendlyError(new Error('File not found: /tmp/x.pdf')))
      .toMatch(/couldn't be opened/i);
  });

  it('maps "File processing failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('File processing failed: disk error')))
      .toMatch(/preparing that document/i);
  });

  it('maps "No cached detection data" to a re-run-detection message', () => {
    expect(friendlyError(new Error('No cached detection data for /tmp/x.pdf. Run detection first.')))
      .toMatch(/detection step needs to run again/i);
  });

  it('maps "A newer scan has already started" to a superseded-scan message', () => {
    expect(friendlyError(new Error('A newer scan has already started. These results are out of date.')))
      .toMatch(/another scan started after this one/i);
  });

  it('maps "Cannot open PDF" to a corrupted-PDF message', () => {
    expect(friendlyError(new Error('Cannot open PDF: cannot find xref')))
      .toMatch(/PDFs couldn't be read/i);
  });

  it('maps "Page N out of range" to a page-load message', () => {
    expect(friendlyError(new Error('Page 5 out of range (0-3)')))
      .toMatch(/couldn't load that page/i);
  });

  it('maps manual-PII text-too-short to a friendly message', () => {
    expect(friendlyError(new Error('Manual PII text must be at least 3 characters.')))
      .toMatch(/at least 3 characters/i);
  });

  it('maps manual-PII out-of-range page to a friendly message', () => {
    expect(friendlyError(new Error('Page 5 does not exist in this document (it has 2 pages).')))
      .toMatch(/doesn't have that many pages/i);
  });

  it('returns the fallback for an unknown error', () => {
    expect(friendlyError(new Error('Unrecognised exception')))
      .toMatch(/something went wrong/i);
  });

  it('returns the fallback for non-Error inputs', () => {
    expect(friendlyError('plain string')).toMatch(/something went wrong/i);
    expect(friendlyError(null)).toMatch(/something went wrong/i);
    expect(friendlyError(undefined)).toMatch(/something went wrong/i);
  });

  it('does not confuse "Folder not found" with the file-not-found pattern', () => {
    expect(friendlyError(new Error('Folder not found: /tmp/x')))
      .toMatch(/folder couldn't be found/i);
    expect(friendlyError(new Error('Folder not found: /tmp/x')))
      .not.toMatch(/files couldn't be opened/i);
  });

  it('maps "Detection failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Detection failed: spaCy exploded')))
      .toMatch(/detecting/i);
  });
  it('maps "Folder processing failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Folder processing failed: disk error')))
      .toMatch(/folder/i);
  });
  it('maps "Redaction failed" to a friendly retry message', () => {
    expect(friendlyError(new Error('Redaction failed: boom')))
      .toMatch(/redact/i);
  });

  it('maps the API token 401 detail', () => {
    expect(friendlyError(new Error('Invalid or missing API token')))
      .toMatch(/couldn't authenticate/i);
  });
});

describe('paste pathway errors', () => {
  it('explains an empty paste', () => {
    expect(friendlyError(new Error('No text was provided.')))
      .toMatch(/paste some text/i);
  });

  it('explains an oversize paste and points at documents', () => {
    expect(friendlyError(new Error(
      'That text is 60,000 characters, over the 50,000 limit. Save it as a ' +
      'document and use the document pathway instead.')))
      .toMatch(/document/i);
  });

  it('handles a clean failure', () => {
    expect(friendlyError(new Error('Cleaning text failed: boom')))
      .toMatch(/cleaning your text/i);
  });

  it('handles a save failure', () => {
    expect(friendlyError(new Error('Saving failed: disk full')))
      .toMatch(/save/i);
  });

  it('handles an unsupported file type', () => {
    expect(friendlyError(new Error('Unsupported file type.')))
      .toMatch(/PDF or a text file/i);
  });

  it('explains an unreadable character from corrupted clipboard data', () => {
    expect(friendlyError(new Error(
      "That text has a character that can't be read properly — this can "
      + "happen with text copied from certain sources. Try copying it again, "
      + "or paste a different section.")))
      .toMatch(/character/i);
  });
});
