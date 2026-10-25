import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { createRoot, removeRoot, sweepStale } from '../electron/tempRoot.cjs';

let tmp: string;
beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-test-'));
});
afterEach(() => {
  try { fs.chmodSync(path.join(tmp, 'locked'), 0o700); } catch { /* none */ }
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe('createRoot', () => {
  it('makes a private directory', () => {
    const root = createRoot(tmp);
    expect(path.dirname(root)).toBe(tmp);
    expect(path.basename(root).startsWith('redaction-tool-')).toBe(true);
    expect(fs.statSync(root).isDirectory()).toBe(true);
    if (process.platform !== 'win32') {
      expect(fs.statSync(root).mode & 0o077).toBe(0);
    }
  });
});

describe('sweepStale', () => {
  it('removes old roots and keeps the current one', () => {
    const old = createRoot(tmp);
    fs.writeFileSync(path.join(old, 'Billy Bob.pdf'), 'x');
    const keep = createRoot(tmp);
    const removed = sweepStale(tmp, keep);
    expect(removed).toEqual([old]);
    expect(fs.existsSync(old)).toBe(false);
    expect(fs.existsSync(keep)).toBe(true);
  });

  it('leaves redaction-tool-py-* folders alone (a manual uvicorn or pytest run)', () => {
    const py = path.join(tmp, 'redaction-tool-py-abc123');
    fs.mkdirSync(py);
    fs.writeFileSync(path.join(py, 'x.pdf'), 'x');
    const old = createRoot(tmp);
    const removed = sweepStale(tmp, undefined);
    expect(removed).toEqual([old]);
    expect(fs.existsSync(py)).toBe(true);
  });

  it('ignores a symlink named redaction-tool-x and leaves its target intact', () => {
    if (process.platform === 'win32') return;
    const target = fs.mkdtempSync(path.join(tmp, 'target-'));
    fs.writeFileSync(path.join(target, 'Joe Bloggs.pdf'), 'x');
    const link = path.join(tmp, 'redaction-tool-x');
    fs.symlinkSync(target, link);
    expect(sweepStale(tmp, '')).toEqual([]);
    expect(fs.existsSync(path.join(target, 'Joe Bloggs.pdf'))).toBe(true);
    expect(fs.lstatSync(link).isSymbolicLink()).toBe(true);
  });

  it('ignores unrelated folders', () => {
    const other = path.join(tmp, 'something-else');
    fs.mkdirSync(other);
    expect(sweepStale(tmp, '')).toEqual([]);
    expect(fs.existsSync(other)).toBe(true);
  });

  it('does not throw when the folder is missing', () => {
    expect(sweepStale(path.join(tmp, 'nope'), '')).toEqual([]);
  });
});

describe('removeRoot', () => {
  it('removes a root and its contents', () => {
    const root = createRoot(tmp);
    fs.writeFileSync(path.join(root, 'a.pdf'), 'x');
    expect(removeRoot(root)).toBe(true);
    expect(fs.existsSync(root)).toBe(false);
  });

  it('returns false and does not throw on an undeletable path', () => {
    if (process.platform === 'win32' || process.getuid?.() === 0) return;
    const locked = path.join(tmp, 'locked');
    const inner = path.join(locked, 'redaction-tool-a');
    fs.mkdirSync(inner, { recursive: true });
    fs.writeFileSync(path.join(inner, 'f'), 'x');
    fs.chmodSync(locked, 0o500);
    expect(removeRoot(inner)).toBe(false);
  });
});
