import { describe, it, expect } from 'vitest';
import { sanitiseForReport, recordRawError, buildFaultReportUrl } from '../src/lib/faultReport';

describe('faultReport sanitisation', () => {
  // File paths carry STUDENT NAMES in this app — none may reach the email.
  it('strips mac paths containing a student name', () => {
    const out = sanitiseForReport('File not found: /Users/dave/Documents/Billy Bob.pdf');
    expect(out).not.toContain('Billy');
    expect(out).toContain('[path removed]');
  });

  it('strips windows paths, quoted and bare', () => {
    expect(sanitiseForReport('Cannot open "C:\\Users\\dave\\Billy Bob Report.pdf" now'))
      .not.toContain('Billy');
    expect(sanitiseForReport('at C:\\school\\reports\\file.pdf'))
      .not.toContain('school');
  });

  it('strips UNC network paths', () => {
    expect(sanitiseForReport('save to \\\\server\\share\\Billy.pdf failed'))
      .not.toContain('Billy');
  });

  // Regression: paths with spaces are the NORM here (student filenames,
  // "OneDrive - Department of Education"), and a \\S+ match stopped at the
  // first space — leaving exactly the surname it was meant to remove.
  it('strips the whole path when it contains spaces, surname included', () => {
    const out = sanitiseForReport(
      'File not found: C:\\Users\\dave\\Billy Bob Support Report.pdf',
    );
    expect(out).not.toContain('Billy');
    expect(out).not.toContain('Bob');
    expect(out).not.toContain('Support Report');
  });

  it('strips a onedrive path with spaces on both sides of the student name', () => {
    const out = sanitiseForReport(
      'No cached detection data for C:\\Users\\dave\\OneDrive - Dept\\Jane Citizen NAPLAN.pdf. Run detection first.',
    );
    expect(out).not.toContain('Jane');
    expect(out).not.toContain('Citizen');
  });

  it('strips a mac path with spaces, surname included', () => {
    const out = sanitiseForReport(
      'File not found: /Users/dave/Documents/Billy Bob Support Report.pdf',
    );
    expect(out).not.toContain('Bob');
  });

  it('strips a volume path with spaces in the volume name', () => {
    const out = sanitiseForReport(
      'Cannot open PDF: /Volumes/USB DRIVE/Jane Citizen report.pdf',
    );
    expect(out).not.toContain('Jane');
    expect(out).not.toContain('Citizen');
  });

  it('strips a folder path with spaces and no file extension', () => {
    const out = sanitiseForReport(
      'Folder not found: C:\\Users\\dave\\Desktop\\Billy Bob Term 3',
    );
    expect(out).not.toContain('Billy');
    expect(out).not.toContain('Bob');
  });

  it('strips a bare filename that has no path root in front of it', () => {
    const out = sanitiseForReport('Could not write Billy Bob.pdf');
    expect(out).not.toContain('Billy');
    expect(out).not.toContain('Bob');
    expect(out).toContain('[file removed]');
  });

  it('does not mistake a url for a windows drive letter', () => {
    expect(sanitiseForReport('Backend not reachable at http://127.0.0.1:8765'))
      .toContain('http://127.0.0.1:8765');
  });

  it('leaves ordinary error prose alone', () => {
    expect(sanitiseForReport('Detection failed: model not loaded'))
      .toBe('Detection failed: model not loaded');
  });
});

describe('buildFaultReportUrl', () => {
  it('builds a mailto to the maintainer with sanitised details', () => {
    recordRawError('No cached detection data for /Users/x/Billy Bob.pdf. Run detection first.');
    const url = buildFaultReportUrl({
      appVersion: '1.5.1', screen: 'final_confirmation',
      workflowMode: 'deidentify', friendlyMessage: 'Something went wrong.',
    });
    expect(url.startsWith('mailto:dave@dandsarmstrong.com?')).toBe(true);
    const body = decodeURIComponent(url);
    expect(body).toContain('1.5.1');
    expect(body).toContain('deidentify');
    expect(body).not.toContain('Billy');
    expect(body).toContain('[path removed]');
  });
});
