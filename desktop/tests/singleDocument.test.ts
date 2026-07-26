import { describe, it, expect, beforeEach } from 'vitest';
import { basename, dirname, joinPath, separatorFor, stem } from '../src/lib/paths';
import { suggestRedactedFilename } from '../src/lib/filename';
import { useStore } from '../src/store';

describe('paths', () => {
  it('splits posix paths', () => {
    expect(dirname('/Users/dave/Docs/report.pdf')).toBe('/Users/dave/Docs');
    expect(basename('/Users/dave/Docs/report.pdf')).toBe('report.pdf');
    expect(stem('/Users/dave/Docs/report.pdf')).toBe('report');
  });

  it('splits windows paths', () => {
    expect(dirname('C:\\Users\\dave\\report.pdf')).toBe('C:\\Users\\dave');
    expect(basename('C:\\Users\\dave\\report.pdf')).toBe('report.pdf');
  });

  it('keeps the root slash for a file at the root', () => {
    expect(dirname('/report.pdf')).toBe('/');
  });

  it('returns empty for a bare filename', () => {
    expect(dirname('report.pdf')).toBe('');
  });

  it('keeps dots in the stem of names like report.final.pdf', () => {
    expect(stem('report.final.pdf')).toBe('report.final');
  });

  it('joins using the separator style of the base path', () => {
    expect(joinPath('/Users/dave', 'redacted')).toBe('/Users/dave/redacted');
    expect(joinPath('C:\\Users\\dave', 'redacted')).toBe('C:\\Users\\dave\\redacted');
    expect(separatorFor('C:\\Users\\dave')).toBe('\\');
  });

  it('does not double the separator on a trailing slash', () => {
    expect(joinPath('/Users/dave/', 'redacted')).toBe('/Users/dave/redacted');
  });
});

describe('suggestRedactedFilename', () => {
  it('strips the student name from the suggested Save As name', () => {
    expect(suggestRedactedFilename('Joe Bloggs Vineland Report 2025', ['Joe Bloggs']))
      .toBe('Vineland Report 2025_redacted.pdf');
  });

  it('treats underscores as word separators', () => {
    expect(suggestRedactedFilename('Bloggs_Joe_Assessment', ['Joe Bloggs']))
      .toBe('Assessment_redacted.pdf');
  });

  it('strips parent and organisation names too', () => {
    expect(suggestRedactedFilename(
      'Sunrise Primary Referral for Joe Bloggs',
      ['Joe Bloggs', 'Sunrise Primary'],
    )).toBe('Referral for_redacted.pdf');
  });

  it('is case insensitive and leaves surrounding words intact', () => {
    expect(suggestRedactedFilename('JOE final report', ['Joe Bloggs']))
      .toBe('final report_redacted.pdf');
  });

  it('does not strip a name fragment inside a longer word', () => {
    expect(suggestRedactedFilename('Joel Term Report', ['Joe']))
      .toBe('Joel Term Report_redacted.pdf');
  });

  it('falls back to "document" when nothing meaningful is left', () => {
    expect(suggestRedactedFilename('Joe Bloggs', ['Joe Bloggs']))
      .toBe('document_redacted.pdf');
  });
});

describe('store: single-document mode', () => {
  beforeEach(() => {
    useStore.getState().reset();
  });

  it('defaults to folder mode', () => {
    expect(useStore.getState().inputMode).toBe('folder');
  });

  it('derives the containing folder when a file is chosen', () => {
    useStore.getState().setFilePath('/Users/dave/Docs/report.pdf');
    const state = useStore.getState();
    expect(state.filePath).toBe('/Users/dave/Docs/report.pdf');
    expect(state.folderPath).toBe('/Users/dave/Docs');
  });

  it('stamps conversion results with the file path in file mode', () => {
    useStore.getState().setInputMode('file');
    useStore.getState().setFilePath('/Users/dave/Docs/report.pdf');
    useStore.getState().setConversionResults({
      pdf_files: ['/Users/dave/Docs/report.pdf'],
      converted_files: [],
      failed_conversions: [],
      password_protected: [],
      total_files: 1,
      processable_count: 1,
      flagged_count: 0,
    });

    // Must be the file, not the folder — otherwise switching to another file in
    // the same folder would reuse the previous file's conversion results.
    expect(useStore.getState().conversionFolderPath).toBe('/Users/dave/Docs/report.pdf');
  });

  it('stamps conversion results with the folder path in folder mode', () => {
    useStore.getState().setFolderPath('/Users/dave/Docs');
    useStore.getState().setConversionResults({
      pdf_files: [],
      converted_files: [],
      failed_conversions: [],
      password_protected: [],
      total_files: 0,
      processable_count: 0,
      flagged_count: 0,
    });

    expect(useStore.getState().conversionFolderPath).toBe('/Users/dave/Docs');
  });

  it('reset clears the single-document selection', () => {
    useStore.getState().setInputMode('file');
    useStore.getState().setFilePath('/Users/dave/Docs/report.pdf');
    useStore.getState().setFileValid(true);
    useStore.getState().setAutoAdvancedKey('/Users/dave/Docs/report.pdf');

    useStore.getState().reset();

    const state = useStore.getState();
    expect(state.inputMode).toBe('folder');
    expect(state.filePath).toBe('');
    expect(state.fileValid).toBe(false);
    expect(state.autoAdvancedKey).toBe('');
  });
});
