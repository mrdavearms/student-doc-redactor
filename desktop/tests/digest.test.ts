import { describe, it, expect } from 'vitest';
import { digest } from '../src/lib/digest';

describe('digest', () => {
  it('is stable for the same text and differs for different text', () => {
    expect(digest('Billy Bob was absent.')).toBe(digest('Billy Bob was absent.'));
    expect(digest('Billy Bob was absent.')).not.toBe(digest('Billy Bob was present.'));
  });

  it('does not contain the text itself', () => {
    const d = digest('Billy Bob was absent.');
    expect(d).not.toContain('Billy');
    expect(d.length).toBeLessThan(20);
  });
});
