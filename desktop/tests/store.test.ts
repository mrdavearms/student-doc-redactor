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

describe('store: detectionParamsKey', () => {
  beforeEach(() => {
    useStore.getState().reset();
  });

  it('stores the key and clears it on reset', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    expect(useStore.getState().detectionParamsKey).toBe('fingerprint-1');
    useStore.getState().reset();
    expect(useStore.getState().detectionParamsKey).toBe('');
  });

  it('clears the key when the backend becomes unreachable', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    useStore.getState().setBackendReachable(false);
    expect(useStore.getState().detectionParamsKey).toBe('');
  });

  it('keeps the key when the backend is reachable again', () => {
    useStore.getState().setDetectionParamsKey('fingerprint-1');
    useStore.getState().setBackendReachable(true);
    expect(useStore.getState().detectionParamsKey).toBe('fingerprint-1');
  });
});

describe('store: conversionFolderPath', () => {
  const conversion = {
    pdf_files: [], converted_files: [], failed_conversions: [],
    password_protected: [], total_files: 1, processable_count: 1, flagged_count: 0,
  };

  beforeEach(() => {
    useStore.getState().reset();
  });

  it('records the folder that produced the conversion results', () => {
    useStore.getState().setFolderPath('/folder-a');
    useStore.getState().setConversionResults(conversion);
    expect(useStore.getState().conversionFolderPath).toBe('/folder-a');
  });

  it('leaves conversion results intact when the path is edited (no keystroke data loss)', () => {
    useStore.getState().setFolderPath('/folder-a');
    useStore.getState().setConversionResults(conversion);
    useStore.setState({ detectionResults: { documents: [], total_matches: 0 } });

    useStore.getState().setFolderPath('/folder-b');

    // Nothing destroyed — the mismatch is what triggers reprocessing.
    expect(useStore.getState().conversionResults).toBe(conversion);
    expect(useStore.getState().detectionResults).not.toBeNull();
    expect(useStore.getState().conversionFolderPath).toBe('/folder-a');
    expect(useStore.getState().folderPath).toBe('/folder-b');
  });

  it('clears stale redaction results when a new detection run lands', () => {
    useStore.setState({
      redactionResults: {
        redacted_folder: '/old', document_results: [], log_content: '', log_path: null,
        total_documents: 0, successfully_redacted: 0, verification_failures: [],
        ocr_warnings: [], cancelled: false,
      },
    });
    useStore.getState().setDetectionResults({ documents: [], total_matches: 0 });
    expect(useStore.getState().redactionResults).toBeNull();
  });
});
