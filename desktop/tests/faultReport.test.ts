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
