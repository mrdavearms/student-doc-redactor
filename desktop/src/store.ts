/**
 * Zustand store — single source of truth for application state.
 * Mirrors the session_state keys from the Streamlit version.
 */

import { create } from 'zustand';
import type {
  Screen,
  ConversionResults,
  DetectionResults,
  RedactionResults,
} from './types';

interface AppState {
  // Navigation
  currentScreen: Screen;
  navigateTo: (screen: Screen) => void;

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

  // Step 4 & 5: Redaction
  redactionResults: RedactionResults | null;
  setRedactionResults: (results: RedactionResults) => void;
  lastOutputPath: string;
  setLastOutputPath: (path: string) => void;

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
  currentScreen: 'folder_selection' as Screen,
  folderPath: '',
  studentName: '',
  parentNames: '',
  familyNames: '',
  organisationNames: '',
  redactHeaderFooter: false,
  folderValid: false,
  conversionResults: null,
  detectionResults: null,
  currentDocIndex: 0,
  userSelections: {} as Record<string, boolean>,
  redactionResults: null,
  lastOutputPath: '',
  loading: false,
  loadingMessage: '',
  error: null,
  backendReachable: true,
  detectionParamsKey: '',
};

export const useStore = create<AppState>((set) => ({
  ...initialState,

  navigateTo: (screen) => set({ currentScreen: screen, error: null }),

  setFolderPath: (path) => set({ folderPath: path }),
  setStudentName: (name) => set({ studentName: name }),
  setParentNames: (names) => set({ parentNames: names }),
  setFamilyNames: (names) => set({ familyNames: names }),
  setOrganisationNames: (names) => set({ organisationNames: names }),
  setRedactHeaderFooter: (val) => set({ redactHeaderFooter: val }),
  setFolderValid: (valid) => set({ folderValid: valid }),

  setConversionResults: (results) => set({ conversionResults: results }),

  setDetectionResults: (results) => {
    // Initialise all selections to true (pre-selected)
    const selections: Record<string, boolean> = {};
    for (const doc of results.documents) {
      doc.matches.forEach((_, idx) => {
        selections[`${doc.path}_${idx}`] = true;
      });
    }
    set({ detectionResults: results, userSelections: selections, currentDocIndex: 0 });
  },

  setCurrentDocIndex: (idx) => set({ currentDocIndex: idx }),

  toggleSelection: (key) =>
    set((state) => ({
      userSelections: {
        ...state.userSelections,
        [key]: !state.userSelections[key],
      },
    })),

  selectAll: (docPath, count) =>
    set((state) => {
      const selections = { ...state.userSelections };
      for (let i = 0; i < count; i++) selections[`${docPath}_${i}`] = true;
      return { userSelections: selections };
    }),

  deselectAll: (docPath, count) =>
    set((state) => {
      const selections = { ...state.userSelections };
      for (let i = 0; i < count; i++) selections[`${docPath}_${i}`] = false;
      return { userSelections: selections };
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
      };
    }),

  setDetectionParamsKey: (key) => set({ detectionParamsKey: key }),

  setRedactionResults: (results) => set({ redactionResults: results }),

  setLastOutputPath: (path) => set({ lastOutputPath: path }),

  setLoading: (loading, message = '') => set({ loading, loadingMessage: message }),

  setError: (error) => set({ error }),

  // Losing the backend may mean a restarted process with an empty detection
  // cache — drop the fingerprint so the next Continue re-runs detection.
  setBackendReachable: (reachable) =>
    set(reachable ? { backendReachable: true } : { backendReachable: false, detectionParamsKey: '' }),

  reset: () => set(initialState),
}));
