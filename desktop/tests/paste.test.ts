import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';
import { screensFor } from '../src/types';

describe('store: pastedText', () => {
  beforeEach(() => {
    useStore.setState({ inputMode: 'paste', pastedText: 'Billy Bob was absent.' });
  });

  it('holds the slab while the user is in the paste pathway', () => {
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('is dropped when the user switches away from paste', () => {
    useStore.getState().setInputMode('folder');
    expect(useStore.getState().pastedText).toBe('');
  });

  it('is kept when switching to paste from elsewhere', () => {
    useStore.getState().setInputMode('paste');
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('SURVIVES a backend blip', () => {
    // detectionParamsKey is cleared so detection re-runs; the user's typed
    // text must not be collateral damage.
    useStore.setState({ detectionParamsKey: 'abc' });
    useStore.getState().setBackendReachable(false);
    expect(useStore.getState().detectionParamsKey).toBe('');
    expect(useStore.getState().pastedText).toBe('Billy Bob was absent.');
  });

  it('clearPastedText empties it for "Clean another"', () => {
    useStore.getState().clearPastedText();
    expect(useStore.getState().pastedText).toBe('');
  });
});

describe('screensFor with paste', () => {
  it('swaps the conversion step for a scan step', () => {
    const keys = screensFor('redact', 'paste').map((s) => s.key);
    expect(keys).toEqual([
      'folder_selection', 'text_scan', 'document_review',
      'final_confirmation', 'completion',
    ]);
  });

  it('keeps Who\'s Who in de-identify mode', () => {
    const keys = screensFor('deidentify', 'paste').map((s) => s.key);
    expect(keys).toContain('people_review');
    expect(keys).toContain('text_scan');
    expect(keys).not.toContain('conversion_status');
  });

  it('relabels step 1 and step 2 for paste', () => {
    const steps = screensFor('redact', 'paste');
    expect(steps[0].label).toBe('Enter Text');
    expect(steps[1].label).toBe('Scan Text');
  });

  it('is unchanged for documents', () => {
    expect(screensFor('redact', 'folder').map((s) => s.key))
      .toEqual(screensFor('redact').map((s) => s.key));
    expect(screensFor('redact').map((s) => s.key)).toContain('conversion_status');
  });

  it('numbers steps consecutively in every combination', () => {
    for (const mode of ['redact', 'deidentify'] as const) {
      for (const input of ['folder', 'file', 'paste'] as const) {
        const steps = screensFor(mode, input);
        expect(steps.map((s) => s.step)).toEqual(steps.map((_, i) => i + 1));
      }
    }
  });
});
