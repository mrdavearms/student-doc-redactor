import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../src/store';
import { suggestDeidentifiedFilename, suggestRedactedFilename } from '../src/lib/filename';
import { screensFor } from '../src/types';
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

describe('screensFor', () => {
  it('redact mode has five steps', () => {
    const steps = screensFor('redact');
    expect(steps).toHaveLength(5);
    expect(steps.map((s) => s.key)).not.toContain('people_review');
  });

  it('de-identify mode inserts the Who\'s Who step before Confirm', () => {
    const steps = screensFor('deidentify');
    expect(steps).toHaveLength(6);
    const keys = steps.map((s) => s.key);
    expect(keys.indexOf('people_review')).toBe(keys.indexOf('document_review') + 1);
    expect(keys.indexOf('people_review')).toBeLessThan(keys.indexOf('final_confirmation'));
  });

  it('numbers steps consecutively from one in both modes', () => {
    for (const mode of ['redact', 'deidentify'] as const) {
      expect(screensFor(mode).map((s) => s.step))
        .toEqual(screensFor(mode).map((_, i) => i + 1));
    }
  });

  it('screens outside the ladder resolve to -1, not a wrong step', () => {
    // setup and mode_selection are deliberately not steps.
    const keys = screensFor('deidentify').map((s) => s.key);
    expect(keys).not.toContain('setup');
    expect(keys).not.toContain('mode_selection');
  });
});

describe('store: people review answers', () => {
  beforeEach(() => {
    useStore.getState().reset();
  });

  it('records a role for a person', () => {
    useStore.getState().setPersonRole('Sarah Williams', 'teacher');
    expect(useStore.getState().personRoles['Sarah Williams']).toBe('teacher');
  });

  it('a custom label is stored alongside the role', () => {
    useStore.getState().setPersonRole('Sarah Williams', 'health', 'Speech pathologist');
    expect(useStore.getState().personCustomLabels['Sarah Williams']).toBe('Speech pathologist');
  });

  it('choosing a plain role clears any previous custom label', () => {
    useStore.getState().setPersonRole('Sarah Williams', 'health', 'Speech pathologist');
    useStore.getState().setPersonRole('Sarah Williams', 'teacher');
    expect(useStore.getState().personCustomLabels['Sarah Williams']).toBeUndefined();
  });

  it('assigning a role un-ignores that person', () => {
    useStore.getState().setPersonIgnored('Email', true);
    useStore.getState().setPersonRole('Email', 'teacher');
    expect(useStore.getState().ignoredPeople).not.toContain('Email');
  });

  it('accept-all does not overwrite answers already given', () => {
    useStore.getState().setPersonRole('Sarah Williams', 'health');
    useStore.getState().acceptSuggestedRoles({
      'Sarah Williams': 'teacher', 'John Citizen': 'teacher',
    });
    const roles = useStore.getState().personRoles;
    expect(roles['Sarah Williams']).toBe('health');
    expect(roles['John Citizen']).toBe('teacher');
  });
});

describe('store: people answers die with any selection change', () => {
  // Answers are only meaningful for the exact set of people the current
  // selections produce. document_review sits BEFORE the people screen, so the
  // user can always go back and change what's selected.
  beforeEach(() => {
    useStore.getState().reset();
    useStore.setState({
      detectionResults: {
        documents: [{ path: '/tmp/a.pdf', filename: 'a.pdf', matches: [], ocr_pages: [] }],
        total_matches: 0,
      },
    });
    useStore.getState().setPersonRole('Sarah Williams', 'teacher');
    useStore.getState().setPersonIgnored('Email', true);
    useStore.getState().setPeopleReviewed(true);
  });

  const assertCleared = () => {
    const s = useStore.getState();
    expect(s.personRoles).toEqual({});
    expect(s.personCustomLabels).toEqual({});
    expect(s.ignoredPeople).toEqual([]);
    expect(s.peopleReviewed).toBe(false);
  };

  it('cleared by toggling one selection', () => {
    useStore.getState().toggleSelection('/tmp/a.pdf_0');
    assertCleared();
  });

  it('cleared by select all', () => {
    useStore.getState().selectAll('/tmp/a.pdf', 3);
    assertCleared();
  });

  it('cleared by deselect all', () => {
    useStore.getState().deselectAll('/tmp/a.pdf', 3);
    assertCleared();
  });

  it('cleared by adding a manual item', () => {
    useStore.getState().addManualMatch('/tmp/a.pdf', {
      text: 'Someone', category: 'Manual', confidence: 1, confidence_label: 'high',
      page_num: 1, line_num: 0, context: 'Someone', source: 'manual', bbox: null,
    }, 0);
    assertCleared();
  });

  it('cleared by switching pathway', () => {
    useStore.getState().setWorkflowMode('redact');
    assertCleared();
  });

  it('cleared by a fresh detection run', () => {
    useStore.getState().setDetectionResults({ documents: [], total_matches: 0 });
    assertCleared();
  });
});
