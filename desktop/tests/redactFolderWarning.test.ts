import { describe, it, expect } from 'vitest';
import { showFolderHoldsOriginals } from '../src/lib/redactFolderWarning';

describe('showFolderHoldsOriginals', () => {
  it('warns when the output folder holds the originals', () => {
    expect(showFolderHoldsOriginals(true)).toBe(true);
  });
  it('stays quiet only for an explicit false', () => {
    expect(showFolderHoldsOriginals(false)).toBe(false);
  });
  it('warns when the field is missing', () => {
    expect(showFolderHoldsOriginals(undefined)).toBe(true);
  });
});
