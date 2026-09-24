import { describe, it, expect } from 'vitest';
import { previousDocWithMatches } from '../src/lib/reviewNavigation';

const doc = (n: number) => ({ matches: new Array(n).fill({}) });

describe('previousDocWithMatches', () => {
  it('returns the nearest earlier document that has matches', () => {
    expect(previousDocWithMatches([doc(1), doc(0), doc(2), doc(1)], 3)).toBe(2);
    expect(previousDocWithMatches([doc(1), doc(0), doc(0), doc(1)], 3)).toBe(0);
  });

  it('returns null when every earlier document is empty, so the button is hidden', () => {
    // The old fallback went to index 1 here; the auto-skip then bounced
    // straight back to index 2 and remounted the manual-item form.
    expect(previousDocWithMatches([doc(0), doc(0), doc(1)], 2)).toBeNull();
  });

  it('returns null on the first document', () => {
    expect(previousDocWithMatches([doc(1), doc(1)], 0)).toBeNull();
  });
});
