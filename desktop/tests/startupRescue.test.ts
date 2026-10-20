import { describe, it, expect } from 'vitest';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import {
  startupFailureDialog,
  earlyExitMessage,
  PORT_IN_USE_MESSAGE,
  ENGINE_DAMAGED_MESSAGE,
  RELEASES_URL,
} from '../electron/startupRescue.cjs';

const failure = 'The redaction engine could not be started.';

describe('startupFailureDialog', () => {
  it('offers the download page when a newer version exists', () => {
    const out = startupFailureDialog({
      failureMessage: failure,
      currentVersion: '1.9.4',
      checkResult: { isUpdateAvailable: true, updateInfo: { version: '1.9.5' } },
    });
    expect(out.kind).toBe('update');
    expect(out.url).toBe(RELEASES_URL);
    expect(out.options.message).toContain('1.9.5');
    expect(out.options.detail).toContain('1.9.4');
    expect(out.options.detail).toContain(failure);
    // Button 0 is the download; Escape / closing the box must mean Quit.
    expect(out.options.buttons[0]).toMatch(/download/i);
    expect(out.options.cancelId).toBe(1);
  });

  it('shows the plain error, with the download link, when already up to date', () => {
    const out = startupFailureDialog({
      failureMessage: failure,
      currentVersion: '1.9.5',
      checkResult: { isUpdateAvailable: false, updateInfo: { version: '1.9.5' } },
    });
    expect(out.kind).toBe('error');
    expect(out.message).toContain(failure);
    expect(out.message).toContain(RELEASES_URL);
  });

  it('shows the plain error when the check failed or timed out', () => {
    const out = startupFailureDialog({ failureMessage: failure, currentVersion: '1.9.4', checkResult: null });
    expect(out.kind).toBe('error');
    expect(out.message).toContain(failure);
  });

  it('does not claim an update when the result has no version', () => {
    const out = startupFailureDialog({
      failureMessage: failure,
      currentVersion: '1.9.4',
      checkResult: { isUpdateAvailable: true },
    });
    expect(out.kind).toBe('error');
  });

  it('points at the real GitHub releases page', () => {
    expect(RELEASES_URL).toBe('https://github.com/mrdavearms/student-doc-redactor/releases/latest');
  });
});

// Both stderr samples were captured from the real bundled engine (Oct 2026).
const PORT_CLASH =
  'INFO:     Started server process [38596]\n' +
  "ERROR:    [Errno 48] error while attempting to bind on address ('127.0.0.1', 8799): address already in use\n";
const MISSING_PACKAGE =
  'Traceback (most recent call last):\n' +
  '  File "backend/main.py", line 21, in <module>\n' +
  '    from fastapi import FastAPI, HTTPException, Request\n' +
  "ModuleNotFoundError: No module named 'fastapi'\n";

describe('earlyExitMessage', () => {
  it('keeps the another-copy message for a real port clash', () => {
    expect(earlyExitMessage(PORT_CLASH)).toBe(PORT_IN_USE_MESSAGE);
  });

  it('says the engine is damaged when it crashed on a missing package', () => {
    expect(earlyExitMessage(MISSING_PACKAGE)).toBe(ENGINE_DAMAGED_MESSAGE);
  });

  it('prefers the port message when both appear', () => {
    expect(earlyExitMessage(MISSING_PACKAGE + PORT_CLASH)).toBe(PORT_IN_USE_MESSAGE);
  });

  it('defaults to the port message when nothing was printed (rule #55)', () => {
    expect(earlyExitMessage('')).toBe(PORT_IN_USE_MESSAGE);
    expect(earlyExitMessage(undefined)).toBe(PORT_IN_USE_MESSAGE);
  });
});
