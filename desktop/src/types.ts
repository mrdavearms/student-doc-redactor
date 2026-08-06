/** Screens in the wizard flow */
export type Screen =
  | 'setup'
  | 'mode_selection'
  | 'folder_selection'
  | 'conversion_status'
  | 'document_review'
  | 'no_pii_found'
  | 'people_review'
  | 'final_confirmation'
  | 'completion';

/** What the user picked to redact: one document, or a whole folder */
export type InputMode = 'file' | 'folder';

/**
 * Which pathway the user chose at the start:
 *  - 'redact'     — black out PII, producing redacted PDFs
 *  - 'deidentify' — replace PII with labels, producing text safe to paste into AI
 * Everything between step 1 and the review screen is identical; only the final
 * output step differs.
 */
export type WorkflowMode = 'redact' | 'deidentify';

export interface StepInfo { key: Screen; label: string; step: number }

/**
 * The wizard's steps for a given pathway. De-identify has one extra step —
 * classifying who each person is — so the sidebar must be built per mode
 * rather than from a fixed array.
 */
export function screensFor(mode: WorkflowMode): StepInfo[] {
  const steps: { key: Screen; label: string }[] = [
    { key: 'folder_selection', label: 'Select Documents' },
    { key: 'conversion_status', label: 'Convert Docs' },
    { key: 'document_review', label: 'Review PII' },
    ...(mode === 'deidentify'
      ? [{ key: 'people_review' as Screen, label: "Who's Who" }]
      : []),
    { key: 'final_confirmation', label: 'Confirm' },
    { key: 'completion', label: 'Complete' },
  ];
  return steps.map((s, i) => ({ ...s, step: i + 1 }));
}

/** Redact-mode steps. Prefer screensFor(mode) — this is the default pathway. */
export const SCREENS: StepInfo[] = screensFor('redact');

/** API response types */

export interface DependencyStatus {
  libreoffice_ok: boolean;
  libreoffice_message: string;
  tesseract_ok: boolean;
  can_convert_word: boolean;
  ner_ok?: boolean;
  ner_message?: string;
}

export interface ConversionResults {
  pdf_files: string[];
  converted_files: string[];
  failed_conversions: { path: string; reason: string }[];
  password_protected: string[];
  total_files: number;
  processable_count: number;
  flagged_count: number;
}

export interface PIIMatch {
  text: string;
  category: string;
  confidence: number;
  confidence_label: string;
  page_num: number;
  line_num: number;
  context: string;
  source: string;
  bbox: number[] | null;
}

export interface DocumentPII {
  path: string;
  filename: string;
  matches: PIIMatch[];
  ocr_pages: number[];
}

export interface DetectionResults {
  documents: DocumentPII[];
  total_matches: number;
}

export interface DocumentResult {
  document_name: string;
  output_path: string | null;
  success: boolean;
  items_redacted: number;
  verification_failures: string[];
  ocr_warnings: string[];
  error_message: string | null;
  quarantine_path: string | null;
}

export interface PreviewResponse {
  image_base64: string;
  total_pages: number;
  page_num: number;
}

export interface RedactionResults {
  redacted_folder: string;
  document_results: DocumentResult[];
  log_content: string;
  log_path: string | null;
  total_documents: number;
  successfully_redacted: number;
  verification_failures: { filename: string; message: string }[];
  ocr_warnings: { filename: string; count: number }[];
  cancelled: boolean;
}

export interface DeidentifyDocumentResult {
  document_name: string;
  output_path: string | null;
  success: boolean;
  items_replaced: number;
  verification_failures: string[];
  ocr_warnings: string[];
  image_warnings: string[];
  /** Post-run NER sweep: names still readable in the output. Real names —
   *  display only, never persisted. */
  leftover_name_warnings: string[];
  error_message: string | null;
  quarantine_path: string | null;
}

export interface PersonInfo {
  full_name: string;
  label: string;
  role: string;
  custom_label: string | null;
  suggested_role: string;
  /** 'likely' | 'possible' | 'unknown' | 'entered' */
  confidence: string;
  evidence: string;
  snippet: string;
  occurrences: number;
  /** 'entered' (typed into the form) | 'detected' */
  source: string;
}

export interface PeopleResponse {
  people: PersonInfo[];
  roles: { key: string; label: string }[];
}

export interface LabelPreviewResponse {
  labels: Record<string, string>;
}

export interface DeidentifyResults {
  output_folder: string;
  /** Written next to the ORIGINALS — never inside output_folder. */
  key_file_path: string | null;
  /** The user pointed output at the folder holding the originals, so that
   *  folder is NOT safe to share wholesale. */
  output_folder_holds_originals: boolean;
  document_results: DeidentifyDocumentResult[];
  log_content: string;
  log_path: string | null;
  total_documents: number;
  successfully_deidentified: number;
  verification_failures: { filename: string; message: string }[];
  ocr_warnings: { filename: string; count: number }[];
  cancelled: boolean;
}
