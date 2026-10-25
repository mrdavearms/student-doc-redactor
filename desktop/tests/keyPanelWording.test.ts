import { describe, it, expect } from 'vitest';
import { keyPanelWording } from '../src/lib/keyPanelWording';

describe('keyPanelWording', () => {
  it('warns when the output folder holds the originals, failures or not', () => {
    expect(keyPanelWording(true, false)).toBe('holds-originals');
    expect(keyPanelWording(true, true)).toBe('holds-originals');
  });
  it('does not reassure when something needs review', () => {
    expect(keyPanelWording(false, true)).toBe('review-first');
  });
  it('reassures only when clean and separate', () => {
    expect(keyPanelWording(false, false)).toBe('safe');
  });
});
