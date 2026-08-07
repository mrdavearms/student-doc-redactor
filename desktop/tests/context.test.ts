import { describe, it, expect } from 'vitest';
import { splitContext } from '../src/lib/context';

describe('splitContext', () => {
  it('marks the value the regex engine wrapped in **', () => {
    // pii_detector._get_context builds exactly this shape.
    expect(splitContext('...Student: **Billy Bob**...')).toEqual([
      { text: '...Student: ', matched: false },
      { text: 'Billy Bob', matched: true },
      { text: '...', matched: false },
    ]);
  });

  it('leaves unmarked NER context completely alone', () => {
    // pii_orchestrator builds context with no markers at all.
    const plain = "Billy's classroom teacher, Sarah Williams, reports";
    expect(splitContext(plain)).toEqual([{ text: plain, matched: false }]);
  });

  it('never emits a literal asterisk pair for a marked value', () => {
    const segs = splitContext('...**Sunrise** Primary School...');
    expect(segs.map((s) => s.text).join('')).not.toContain('**');
  });

  it('reassembles to the original text minus the markers', () => {
    const segs = splitContext('...**Sunrise Primary School**...');
    expect(segs.map((s) => s.text).join('')).toBe('...Sunrise Primary School...');
  });

  it('handles several marked runs', () => {
    const segs = splitContext('a **b** c **d** e');
    expect(segs.filter((s) => s.matched).map((s) => s.text)).toEqual(['b', 'd']);
  });

  it('returns nothing for empty context', () => {
    expect(splitContext('')).toEqual([]);
  });

  it('treats an unpaired marker as ordinary text', () => {
    expect(splitContext('a ** b')).toEqual([{ text: 'a ** b', matched: false }]);
  });
});
