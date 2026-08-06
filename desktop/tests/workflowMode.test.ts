import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';
import { suggestDeidentifiedFilename, suggestRedactedFilename } from '../src/lib/filename';
import { friendlyError } from '../src/lib/errorMessage';
import type { DeidentifyResults, RedactionResults } from '../src/types';

function deidentifyResults(): DeidentifyResults {
  return {
    output_folder: '/tmp/deidentified',
    key_file_path: '/tmp/DO-NOT-UPLOAD-name-key.txt',
    document_results: [],
    log_content: '',
    log_path: null,
    total_documents: 1,
    successfully_deidentified: 1,
    verification_failures: [],
    ocr_warnings: [],
    cancelled: false,
  };
}

function redactionResults(): RedactionResults {
  return {
    redacted_folder: '/tmp/redacted',
    document_results: [],
    log_content: '',
    log_path: null,
    total_documents: 1,
    successfully_redacted: 1,
    verification_failures: [],
    ocr_warnings: [],
    cancelled: false,
  };
}

describe('store: workflowMode', () => {
  beforeEach(() => {
    useStore.getState().reset();
  });

  it('starts on the mode selection screen', () => {
    expect(useStore.getState().currentScreen).toBe('mode_selection');
  });

  it('defaults to the redact pathway', () => {
    expect(useStore.getState().workflowMode).toBe('redact');
  });

  it('switching mode clears any finished run', () => {
    useStore.setState({
      redactionResults: redactionResults(),
      deidentifyResults: deidentifyResults(),
    });

    useStore.getState().setWorkflowMode('deidentify');

    const state = useStore.getState();
    expect(state.workflowMode).toBe('deidentify');
    expect(state.redactionResults).toBeNull();
    expect(state.deidentifyResults).toBeNull();
  });

  it('switching mode does NOT force re-detection', () => {
    // Detection inputs are identical in both modes, so changing your mind after
    // reviewing must not throw the review work away.
    useStore.setState({ detectionParamsKey: 'abc123' });
    useStore.getState().setWorkflowMode('deidentify');
    expect(useStore.getState().detectionParamsKey).toBe('abc123');
  });

  it('a new detection run clears de-identify results too', () => {
    useStore.setState({ deidentifyResults: deidentifyResults() });
    useStore.getState().setDetectionResults({
      documents: [{ path: '/tmp/a.pdf', filename: 'a.pdf', matches: [], ocr_pages: [] }],
      total_matches: 0,
    });
    expect(useStore.getState().deidentifyResults).toBeNull();
  });

  it('losing the backend still clears the detection fingerprint', () => {
    useStore.setState({ detectionParamsKey: 'abc123' });
    useStore.getState().setBackendReachable(false);
    expect(useStore.getState().detectionParamsKey).toBe('');
  });
});

describe('filename suggestions', () => {
  it('de-identified suggestion is a .txt file', () => {
    expect(suggestDeidentifiedFilename('Billy Bob Report', ['Billy Bob']))
      .toMatch(/_deidentified\.txt$/);
  });

  it('de-identified suggestion strips the student name like the redact one', () => {
    const name = suggestDeidentifiedFilename('Billy Bob Report', ['Billy Bob']);
    expect(name.toLowerCase()).not.toContain('billy');
    expect(name.toLowerCase()).not.toContain('bob');
  });

  it('redacted suggestion is unchanged', () => {
    expect(suggestRedactedFilename('Billy Bob Report', ['Billy Bob']))
      .toMatch(/_redacted\.pdf$/);
  });
});

describe('errorMessage: de-identify failures', () => {
  it('maps the de-identification failure', () => {
    expect(friendlyError(new Error('De-identification failed: boom')))
      .toMatch(/de-identifying/i);
  });

  it('maps missing extracted text to a go-back message', () => {
    expect(friendlyError(new Error('No extracted text available for this document.')))
      .toMatch(/go back one step/i);
  });

  it('still maps the cache-miss message both modes rely on', () => {
    expect(friendlyError(new Error('No cached detection data for /tmp/a.pdf.')))
      .toMatch(/go back one step/i);
  });
});
