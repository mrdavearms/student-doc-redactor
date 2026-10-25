import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { appendBounded } from '../electron/errorLog.cjs';

let tmp: string;
beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'el-test-'));
});
afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe('appendBounded', () => {
  it('truncates a long entry', () => {
    const file = path.join(tmp, 'error.log');
    appendBounded(file, 'x'.repeat(100000) + '\n', 8192);
    const size = fs.statSync(file).size;
    expect(size).toBeLessThanOrEqual(8192 + 1);
    expect(fs.readFileSync(file, 'utf8').endsWith('\n')).toBe(true);
  });

  it('rotates past one megabyte, replacing any earlier .1', () => {
    const file = path.join(tmp, 'error.log');
    fs.writeFileSync(file + '.1', 'older');
    fs.writeFileSync(file, 'a'.repeat(1048576 - 10));
    appendBounded(file, 'b'.repeat(100) + '\n');
    expect(fs.readFileSync(file + '.1', 'utf8')).toBe('a'.repeat(1048576 - 10));
    expect(fs.readFileSync(file, 'utf8')).toBe('b'.repeat(100) + '\n');
  });

  it('appends normally under the limit', () => {
    const file = path.join(tmp, 'error.log');
    appendBounded(file, 'one\n');
    appendBounded(file, 'two\n');
    expect(fs.readFileSync(file, 'utf8')).toBe('one\ntwo\n');
    expect(fs.existsSync(file + '.1')).toBe(false);
  });
});
