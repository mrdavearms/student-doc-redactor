/**
 * Zustand store — single source of truth for application state.
 * Mirrors the session_state keys from the Streamlit version.
 */

import { create } from 'zustand';
import type {
  Screen,
  ConversionResults,
  DetectionResults,
  DocumentPII,
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
  folderValid: boolean;
  setFolderPath: (path: string) => void;
  setStudentName: (name: string) => void;
  setParentNames: (names: string) => void;
  setFamilyNames: (names: string) => void;
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

  // Step 4 & 5: Redaction
  redactionResults: RedactionResults | null;
  setRedactionResults: (results: RedactionResults) => void;

  // Loading state
  loading: boolean;
  loadingMessage: string;
  setLoading: (loading: boolean, message?: string) => void;

  // Error state
  error: string | null;
  setError: (error: string | null) => void;

  // Reset
  reset: () => void;
}

const initialState = {
  currentScreen: 'folder_selection' as Screen,
  folderPath: '',
  studentName: '',
  parentNames: '',
  familyNames: '',
  folderValid: false,
  conversionResults: null,
  detectionResults: null,
  currentDocIndex: 0,
  userSelections: {} as Record<string, boolean>,
  redactionResults: null,
  loading: false,
  loadingMessage: '',
  error: null,
};

export const useStore = create<AppState>((set, get) => ({
  ...initialState,

  navigateTo: (screen) => set({ currentScreen: screen, error: null }),

  setFolderPath: (path) => set({ folderPath: path }),
  setStudentName: (name) => set({ studentName: name }),
  setParentNames: (names) => set({ parentNames: names }),
  setFamilyNames: (names) => set({ familyNames: names }),
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

  setRedactionResults: (results) => set({ redactionResults: results }),

  setLoading: (loading, message = '') => set({ loading, loadingMessage: message }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
}));
