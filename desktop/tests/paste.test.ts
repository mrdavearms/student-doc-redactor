import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';

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
