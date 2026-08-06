/**
 * Zustand store — single source of truth for application state.
 * Mirrors the session_state keys from the Streamlit version.
 */

import { create } from 'zustand';
import { dirname } from './lib/paths';
import { buildDefaultSelections } from './lib/categories';
import type {
  Screen,
  InputMode,
  WorkflowMode,
  ConversionResults,
  DetectionResults,
  RedactionResults,
  DeidentifyResults,
} from './types';

interface AppState {
  // Navigation
  currentScreen: Screen;
  navigateTo: (screen: Screen) => void;

  // Step 0: Which pathway — black out, or replace with labels for AI
  workflowMode: WorkflowMode;
  setWorkflowMode: (mode: WorkflowMode) => void;

  // Step 1: What to redact — one document or a whole folder
  inputMode: InputMode;
  filePath: string;
  fileValid: boolean;
  setInputMode: (mode: InputMode) => void;
  setFilePath: (path: string) => void;
  setFileValid: (valid: boolean) => void;

  // Step 1: Folder & student info
  folderPath: string;
  studentName: string;
  parentNames: string;
  familyNames: string;
  organisationNames: string;
  redactHeaderFooter: boolean;
  folderValid: boolean;
  setFolderPath: (path: string) => void;
  setStudentName: (name: string) => void;
  setParentNames: (names: string) => void;
  setFamilyNames: (names: string) => void;
  setOrganisationNames: (names: string) => void;
  setRedactHeaderFooter: (val: boolean) => void;
  setFolderValid: (valid: boolean) => void;

  // Step 2: Conversion
  conversionResults: ConversionResults | null;
  setConversionResults: (results: ConversionResults) => void;

  // Which input produced conversionResults (the folder, or the single file) —
  // lets ConversionStatus detect a change and reprocess, without destroying
  // state on every keystroke.
  conversionFolderPath: string;

  // Input key that has already auto-advanced past the conversion screen in
  // single-document mode. Without it, pressing Back from the review screen
  // would immediately auto-advance again and trap the user.
  autoAdvancedKey: string;
  setAutoAdvancedKey: (key: string) => void;

  // Same guard pattern, separate field: PeopleReview's zero-people auto-skip.
  // Sharing autoAdvancedKey would erase ConversionStatus's stamp and re-arm
  // the forward-bounce trap rule #38 fixed.
  peopleAutoSkippedKey: string;
  setPeopleAutoSkippedKey: (key: string) => void;

  // Step 3: Detection & Review
  detectionResults: DetectionResults | null;
  currentDocIndex: number;
  userSelections: Record<string, boolean>;  // "docPath_matchIdx" -> true/false
  setDetectionResults: (results: DetectionResults) => void;
  setCurrentDocIndex: (idx: number) => void;
  toggleSelection: (key: string) => void;
  selectAll: (docPath: string, count: number) => void;
  deselectAll: (docPath: string, count: number) => void;
  addManualMatch: (docPath: string, match: import('./types').PIIMatch, index: number) => void;

  // Fingerprint of the inputs used for the last successful detection run.
  // Lets the wizard skip re-detection (preserving review work and the backend
  // cache) when nothing has changed. MUST be cleared whenever the backend
  // cache might be gone, or the wizard can loop with no way forward.
  detectionParamsKey: string;
  setDetectionParamsKey: (key: string) => void;

  // Step 3b (de-identify only): who each discovered person is. Roles are
  // PROPOSED by the tool and confirmed by the user — a wrong role is worse
  // than a vague one, so anything unanswered stays [Other person].
  personRoles: Record<string, string>;
  personCustomLabels: Record<string, string>;
  ignoredPeople: string[];
  setPersonRole: (fullName: string, role: string, customLabel?: string) => void;
  setPersonIgnored: (fullName: string, ignored: boolean) => void;
  acceptSuggestedRoles: (roles: Record<string, string>) => void;

  // Step 4 & 5: Redaction
  redactionResults: RedactionResults | null;
  setRedactionResults: (results: RedactionResults) => void;
  deidentifyResults: DeidentifyResults | null;
  setDeidentifyResults: (results: DeidentifyResults) => void;
  lastOutputPath: string;
  setLastOutputPath: (path: string) => void;

  // True while a redact/de-identify request is in flight. The Sidebar hides the
  // pathway-change link while set: that link unmounts FinalConfirmation without
  // aborting the request, which then navigates the user to completion from
  // wherever they had moved to.
  isProcessing: boolean;
  setIsProcessing: (busy: boolean) => void;

  // Loading state
  loading: boolean;
  loadingMessage: string;
  setLoading: (loading: boolean, message?: string) => void;

  // Error state
  error: string | null;
  setError: (error: string | null) => void;

  // Backend reachability (false ⇒ show banner, start polling)
  backendReachable: boolean;
  setBackendReachable: (reachable: boolean) => void;

  // Reset
  reset: () => void;
}

const initialState = {
  currentScreen: 'mode_selection' as Screen,
  workflowMode: 'redact' as WorkflowMode,
  inputMode: 'folder' as InputMode,
  filePath: '',
  fileValid: false,
  folderPath: '',
  studentName: '',
  parentNames: '',
  familyNames: '',
  organisationNames: '',
  redactHeaderFooter: false,
  folderValid: false,
  conversionResults: null,
  conversionFolderPath: '',
  detectionResults: null,
  currentDocIndex: 0,
  userSelections: {} as Record<string, boolean>,
  redactionResults: null,
  deidentifyResults: null,
  personRoles: {} as Record<string, string>,
  personCustomLabels: {} as Record<string, string>,
  ignoredPeople: [] as string[],
  lastOutputPath: '',
  isProcessing: false,
  loading: false,
  loadingMessage: '',
  error: null,
  backendReachable: true,
  detectionParamsKey: '',
  autoAdvancedKey: '',
  peopleAutoSkippedKey: '',
};

// Answers from the "Who's who?" screen are only meaningful for the exact set of
// people the current selections produce. Changing what's selected can remove a
// person entirely or introduce a new one, so the answers die with the change.
const CLEARED_PEOPLE_STATE = {
  personRoles: {} as Record<string, string>,
  personCustomLabels: {} as Record<string, string>,
  ignoredPeople: [] as string[],
  // The zero-people auto-skip stamp must die too: changed selections can
  // change whether there is anyone to classify.
  peopleAutoSkippedKey: '',
};

export const useStore = create<AppState>((set) => ({
  ...initialState,

  navigateTo: (screen) => set({ currentScreen: screen, error: null }),

  // Switching pathway invalidates any finished run, but deliberately NOT
  // detectionParamsKey: detection inputs are identical in both modes, so a user
  // who changes their mind after reviewing should not have to detect again.
  setWorkflowMode: (mode) =>
    set((state) => ({
      workflowMode: mode,
      redactionResults: null,
      deidentifyResults: null,
      // Selections were initialised under the OLD mode's safety assumptions.
      // Re-derive for the new mode (detection itself is NOT re-run — rule 41's
      // fingerprint stays). Discards hand-toggles; safer than carrying over
      // defaults computed under the wrong mode.
      ...(state.detectionResults && state.workflowMode !== mode
        ? { userSelections: buildDefaultSelections(state.detectionResults, mode) }
        : {}),
      ...CLEARED_PEOPLE_STATE,
    })),

  setInputMode: (mode) => set({ inputMode: mode }),

  // The redaction run still works in folders (audit log, default output
  // location), so a chosen file also sets folderPath to its containing folder.
  //
  // That silently moves folderPath out from under folderValid, which was only
  // ever true for a folder the user picked themselves — so clear it. Otherwise
  // switching back to folder mode shows a green "Folder found" for a folder
  // that was never validated, and Start Processing would redact everything in
  // it. FolderSelection re-validates on the way back.
  setFilePath: (path) =>
    set({ filePath: path, folderPath: dirname(path), folderValid: false }),

  setFileValid: (valid) => set({ fileValid: valid }),

  setFolderPath: (path) => set({ folderPath: path }),
  setStudentName: (name) => set({ studentName: name }),
  setParentNames: (names) => set({ parentNames: names }),
  setFamilyNames: (names) => set({ familyNames: names }),
  setOrganisationNames: (names) => set({ organisationNames: names }),
  setRedactHeaderFooter: (val) => set({ redactHeaderFooter: val }),
  setFolderValid: (valid) => set({ folderValid: valid }),

  setConversionResults: (results) =>
    set((state) => ({
      conversionResults: results,
      conversionFolderPath:
        state.inputMode === 'file' ? state.filePath : state.folderPath,
    })),

  setAutoAdvancedKey: (key) => set({ autoAdvancedKey: key }),

  setPeopleAutoSkippedKey: (key) => set({ peopleAutoSkippedKey: key }),

  setDetectionResults: (results) =>
    set((state) => ({
      detectionResults: results,
      // Mode-aware defaults: everything in redact mode; low-precision NER
      // discoveries pre-unticked in de-identify mode (see lib/categories.ts).
      userSelections: buildDefaultSelections(results, state.workflowMode),
      currentDocIndex: 0,
      redactionResults: null,
      deidentifyResults: null,
      ...CLEARED_PEOPLE_STATE,
    })),

  setCurrentDocIndex: (idx) => set({ currentDocIndex: idx }),

  toggleSelection: (key) =>
    set((state) => ({
      userSelections: {
        ...state.userSelections,
        [key]: !state.userSelections[key],
      },
      ...CLEARED_PEOPLE_STATE,
    })),

  selectAll: (docPath, count) =>
    set((state) => {
      const selections = { ...state.userSelections };
      for (let i = 0; i < count; i++) selections[`${docPath}_${i}`] = true;
      return { userSelections: selections, ...CLEARED_PEOPLE_STATE };
    }),

  deselectAll: (docPath, count) =>
    set((state) => {
      const selections = { ...state.userSelections };
      for (let i = 0; i < count; i++) selections[`${docPath}_${i}`] = false;
      return { userSelections: selections, ...CLEARED_PEOPLE_STATE };
    }),

  addManualMatch: (docPath, match, index) =>
    set((state) => {
      if (!state.detectionResults) return {};
      const documents = state.detectionResults.documents.map((doc) =>
        doc.path === docPath ? { ...doc, matches: [...doc.matches, match] } : doc
      );
      return {
        detectionResults: { ...state.detectionResults, documents },
        userSelections: { ...state.userSelections, [`${docPath}_${index}`]: true },
        ...CLEARED_PEOPLE_STATE,
      };
    }),

  setDetectionParamsKey: (key) => set({ detectionParamsKey: key }),

  setRedactionResults: (results) => set({ redactionResults: results }),

  setDeidentifyResults: (results) => set({ deidentifyResults: results }),

  setPersonRole: (fullName, role, customLabel) =>
    set((state) => {
      const custom = { ...state.personCustomLabels };
      if (customLabel) custom[fullName] = customLabel;
      else delete custom[fullName];
      return {
        personRoles: { ...state.personRoles, [fullName]: role },
        personCustomLabels: custom,
        ignoredPeople: state.ignoredPeople.filter((n) => n !== fullName),
      };
    }),

  setPersonIgnored: (fullName, ignored) =>
    set((state) => ({
      ignoredPeople: ignored
        ? Array.from(new Set([...state.ignoredPeople, fullName]))
        : state.ignoredPeople.filter((n) => n !== fullName),
    })),

  acceptSuggestedRoles: (roles) =>
    set((state) => ({ personRoles: { ...roles, ...state.personRoles } })),

  setLastOutputPath: (path) => set({ lastOutputPath: path }),

  setIsProcessing: (busy) => set({ isProcessing: busy }),

  setLoading: (loading, message = '') => set({ loading, loadingMessage: message }),

  setError: (error) => set({ error }),

  // Losing the backend may mean a restarted process with an empty detection
  // cache — drop the fingerprint so the next Continue re-runs detection.
  setBackendReachable: (reachable) =>
    set(reachable ? { backendReachable: true } : { backendReachable: false, detectionParamsKey: '' }),

  reset: () => set(initialState),
}));
