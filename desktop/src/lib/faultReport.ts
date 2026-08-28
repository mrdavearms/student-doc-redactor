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

// Paths in this app carry STUDENT NAMES, and real ones are full of spaces
// ("C:\Users\dave\OneDrive - Dept\Billy Bob Report.pdf"). A token-bounded
// match (\S+) stops at the first space and so leaves the surname behind —
// which defeats the whole purpose of this file. Once a path ROOT is seen,
// therefore, the rest of the LINE goes with it. That costs a little trailing
// diagnostic prose; the mapped explanation is reported separately as
// "Message shown", so nothing the maintainer needs is actually lost.
//
// Quoted forms come first so their closing quote bounds the match and any
// prose after it survives.
const PATH_PATTERNS: RegExp[] = [
  /"[A-Za-z]:[\\/][^"\n]*"/g,   // "C:\Users\dave\Some Folder\file.pdf"
  /'[A-Za-z]:[\\/][^'\n]*'/g,
  /"\/[^"\n]*"/g,               // "/Users/dave/Some Folder/file.pdf"
  /'\/[^'\n]*'/g,
  /\\\\[^\n]*/g,               // \\server\share\file.pdf
  // The lookbehind stops "http://host" being read as a drive letter.
  /(?<![A-Za-z])[A-Za-z]:[\\/][^\n]*/g,
  /\/(?:Users|home|Volumes|private|tmp|var|mnt|media)\/[^\n]*/g,
  /~[\\/][^\n]*/g,              // ~/Documents/Billy Bob.pdf
];

// Backstop for a filename with no path root in front of it. Space-tolerant on
// purpose: "Billy Bob.pdf" is the shape that matters, and a token-bounded
// match would keep the given name. It can swallow a few words of surrounding
// prose, which is the safe direction to err in.
const DOCUMENT_FILE_PATTERN =
  /(?:[^\s\\/:*?"<>|]+ )*[^\s\\/:*?"<>|]+\.(?:pdf|docx?|txt|rtf|odt)\b/gi;

/** Replace every path-like token — they carry student names in this app. */
export function sanitiseForReport(text: string): string {
  let out = text ?? '';
  for (const re of PATH_PATTERNS) {
    out = out.replace(re, '[path removed]');
  }
  return out.replace(DOCUMENT_FILE_PATTERN, '[file removed]');
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
