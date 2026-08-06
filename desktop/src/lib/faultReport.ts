/**
 * Fault reporting — "Report this problem" opens the user's own email client
 * with a pre-filled report to the maintainer.
 *
 * mailto: only. No network call, no telemetry — the user sees exactly what
 * would be sent and presses Send themselves, which is the only reporting
 * model consistent with this app's privacy promise.
 *
 * SANITISATION IS LOAD-BEARING: raw backend errors embed file paths, and in
 * this app file paths contain STUDENT NAMES ("File not found:
 * /Users/x/Billy Bob.pdf"). Every path-like token is replaced before the
 * report is built. Never add fields containing document names, folder names,
 * or detected text.
 */

const MAINTAINER_EMAIL = 'dave@dandsarmstrong.com';

// Windows drive paths, UNC paths, and POSIX absolute paths — including ones
// wrapped in quotes. Greedy to the end of the path token (spaces inside
// Windows paths are caught by the quoted variants first).
const PATH_PATTERNS: RegExp[] = [
  /"[A-Za-z]:\\[^"]*"/g,      // "C:\Users\dave\Some Folder\file.pdf"
  /'[A-Za-z]:\\[^']*'/g,
  /[A-Za-z]:\\\S+/g,          // C:\Users\dave\file.pdf
  /\\\\\S+/g,                 // \\server\share\file.pdf
  /"\/[^"]*"/g,               // "/Users/dave/Some Folder/file.pdf"
  /'\/[^']*'/g,
  /\/(?:Users|home|Volumes|private|tmp|var|mnt|media)\/\S+/g,
];

/** Replace every path-like token — they carry student names in this app. */
export function sanitiseForReport(text: string): string {
  let out = text ?? '';
  for (const re of PATH_PATTERNS) {
    out = out.replace(re, '[path removed]');
  }
  return out;
}

let lastRawError: string | null = null;
let lastErrorAt: string | null = null;

/** Called by friendlyError — the single funnel every caught error goes through. */
export function recordRawError(raw: string): void {
  lastRawError = raw;
  lastErrorAt = new Date().toISOString();
}

export interface FaultContext {
  appVersion: string;
  screen: string;
  workflowMode: string;
  friendlyMessage: string;
}

/** The mailto: URL for the user's email client. Everything in it is sanitised. */
export function buildFaultReportUrl(ctx: FaultContext): string {
  const platform =
    typeof navigator !== 'undefined' ? navigator.platform || 'unknown' : 'unknown';

  const body = [
    'Hi Dave,',
    '',
    'The Redaction Tool hit a problem. Details below — please describe what',
    'you were doing when it happened:',
    '',
    '(your description here)',
    '',
    '--- Diagnostic details (no document names or student details included) ---',
    `App version: ${ctx.appVersion || 'unknown'}`,
    `Platform: ${platform}`,
    `Pathway: ${ctx.workflowMode}`,
    `Screen: ${ctx.screen}`,
    `When: ${lastErrorAt ?? new Date().toISOString()}`,
    `Message shown: ${sanitiseForReport(ctx.friendlyMessage)}`,
    `Technical detail: ${sanitiseForReport(lastRawError ?? '(none recorded)')}`,
  ].join('\n');

  const subject = `Redaction Tool fault report (v${ctx.appVersion || '?'})`;
  return `mailto:${MAINTAINER_EMAIL}` +
    `?subject=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`;
}
