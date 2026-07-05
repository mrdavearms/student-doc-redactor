import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';
import type { PIIMatch } from '../src/types';

function manualMatch(overrides: Partial<PIIMatch> = {}): PIIMatch {
  return {
    text: 'Sarnh Jones',
    category: 'Manual',
    confidence: 1.0,
    confidence_label: 'high',
    page_num: 2,
    line_num: 0,
    context: 'Sarnh Jones',
    source: 'manual',
    bbox: null,
    ...overrides,
  };
}

describe('store: addManualMatch', () => {
  beforeEach(() => {
    useStore.setState({
      detectionResults: {
        documents: [
          { path: '/tmp/a.pdf', filename: 'a.pdf', matches: [], ocr_pages: [] },
          { path: '/tmp/b.pdf', filename: 'b.pdf', matches: [], ocr_pages: [] },
        ],
        total_matches: 0,
      },
      userSelections: {},
    });
  });

  it('appends the match to the matching document only', () => {
    const match = manualMatch();
    useStore.getState().addManualMatch('/tmp/a.pdf', match, 0);

    const state = useStore.getState();
    expect(state.detectionResults?.documents[0].matches).toEqual([match]);
    expect(state.detectionResults?.documents[1].matches).toEqual([]);
  });

  it('marks the new match selected by its index-derived key', () => {
    const match = manualMatch();
    useStore.getState().addManualMatch('/tmp/a.pdf', match, 0);

    expect(useStore.getState().userSelections['/tmp/a.pdf_0']).toBe(true);
  });

  it('appends after existing matches without disturbing their selections', () => {
    useStore.setState((s) => ({
      detectionResults: {
        ...s.detectionResults!,
        documents: s.detectionResults!.documents.map((d) =>
          d.path === '/tmp/a.pdf' ? { ...d, matches: [manualMatch({ text: 'Existing' })] } : d
        ),
      },
      userSelections: { '/tmp/a.pdf_0': false },
    }));

    const newMatch = manualMatch({ text: 'New One' });
    useStore.getState().addManualMatch('/tmp/a.pdf', newMatch, 1);

    const state = useStore.getState();
    expect(state.detectionResults?.documents[0].matches.map((m) => m.text)).toEqual(['Existing', 'New One']);
    expect(state.userSelections['/tmp/a.pdf_0']).toBe(false);
    expect(state.userSelections['/tmp/a.pdf_1']).toBe(true);
  });
});
