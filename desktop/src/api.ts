/**
 * API client — talks to the FastAPI backend on localhost.
 */

const BASE = 'http://127.0.0.1:8765';

export class BackendUnreachableError extends Error {
  constructor() {
    super('Backend not reachable');
    this.name = 'BackendUnreachableError';
  }
}

const DEFAULT_TIMEOUT_MS = 60_000;

// The API token is fetched once over IPC and cached for the session.
// Outside Electron (vitest, browser dev without the shell) it resolves to ''
// and no header is sent — the backend then has auth disabled too.
let tokenPromise: Promise<string> | null = null;

function getApiToken(): Promise<string> {
  if (!tokenPromise) {
    const getter = typeof window === 'undefined' ? undefined : window.electronAPI?.getApiToken;
    tokenPromise = getter ? getter().catch(() => '') : Promise.resolve('');
  }
  return tokenPromise;
}

/** Test-only: drop the cached token so each test can stub its own. */
export function __resetApiTokenCache() {
  tokenPromise = null;
}

async function request<T>(
  path: string,
  options?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);
  const signal = options?.signal
    ? AbortSignal.any([options.signal, timeoutController.signal])
    : timeoutController.signal;

  let res: Response;
  try {
    const token = await getApiToken();
    res = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'X-Api-Token': token } : {}),
      },
      ...options,
      signal,
    });
  } catch (e) {
    // Only a genuine external cancel (the caller's own signal, NOT our internal
    // timeout) stays an AbortError so callers can suppress the error toast. If
    // our timeout fired — even alongside an external abort in the same tick — it
    // means the backend is unreachable.
    if (options?.signal?.aborted && !timeoutController.signal.aborted) throw e;
    throw new BackendUnreachableError();
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),

  checkDependencies: () =>
    request<import('./types').DependencyStatus>('/api/dependencies/check'),

  validateFolder: (folder_path: string) =>
    request<{ exists: boolean; is_directory: boolean; path: string }>(
      '/api/folder/validate',
      { method: 'POST', body: JSON.stringify({ folder_path }) },
    ),

  processFolder: (folder_path: string, options?: RequestInit) =>
    request<import('./types').ConversionResults>('/api/folder/process', {
      method: 'POST',
      body: JSON.stringify({ folder_path }),
      ...options,
    }),

  validateFile: (file_path: string) =>
    request<{ exists: boolean; is_file: boolean; supported: boolean; path: string }>(
      '/api/file/validate',
      { method: 'POST', body: JSON.stringify({ file_path }) },
    ),

  processFile: (file_path: string, options?: RequestInit) =>
    request<import('./types').ConversionResults>('/api/file/process', {
      method: 'POST',
      body: JSON.stringify({ file_path }),
      ...options,
    }),

  detectPII: (params: {
    pdf_paths: string[];
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, options?: RequestInit) =>
    request<import('./types').DetectionResults>('/api/pii/detect', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),

  detectText: (params: {
    text: string;
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
  }, options?: RequestInit) =>
    request<import('./types').DetectionResults>('/api/text/detect', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),

  textPeople: (params: Record<string, unknown>, options?: RequestInit) =>
    request<import('./types').PeopleResponse>('/api/text/people', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),

  textLabels: (params: Record<string, unknown>, options?: RequestInit) =>
    request<import('./types').LabelPreviewResponse>('/api/text/labels', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),

  cleanText: (params: Record<string, unknown>, options?: RequestInit) =>
    request<import('./types').CleanTextResult>('/api/text/clean', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),

  saveText: (text: string, path: string, kind: 'pdf' | 'txt') =>
    request<{ path: string; unsupported_characters: string[] }>('/api/text/save', {
      method: 'POST',
      body: JSON.stringify({ text, path, kind }),
    }),

  discardText: () =>
    request<{ discarded: boolean }>('/api/text/discard', { method: 'POST' }),

  redact: (params: {
    folder_path: string;
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
    redact_header_footer: boolean;
    documents: string[];
    detected_pii: Record<string, unknown[]>;
    selected_keys: string[];
    folder_action: string | null;
    custom_output_path?: string | null;
    custom_output_filename?: string | null;
  }, options?: RequestInit) =>
    request<import('./types').RedactionResults>('/api/redact', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),

  deidentify: (params: {
    folder_path: string;
    student_name: string;
    parent_names: string[];
    family_names: string[];
    organisation_names: string[];
    redact_header_footer: boolean;
    documents: string[];
    selected_keys: string[];
    folder_action: string | null;
    custom_output_path?: string | null;
    custom_output_filename?: string | null;
    person_roles?: Record<string, string>;
    person_custom_labels?: Record<string, string>;
    ignored_people?: string[];
  }, options?: RequestInit) =>
    request<import('./types').DeidentifyResults>('/api/deidentify', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }, 30 * 60_000),

  deidentifyPeople: (params: Record<string, unknown>, options?: RequestInit) =>
    request<import('./types').PeopleResponse>('/api/deidentify/people', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),

  deidentifyLabels: (params: Record<string, unknown>, options?: RequestInit) =>
    request<import('./types').LabelPreviewResponse>('/api/deidentify/labels', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),

  cancelRedaction: () =>
    request<{ status: string }>('/api/redact/cancel', { method: 'POST' }),

  addManualPII: (params: {
    doc_path: string;
    text: string;
    page_num: number;
    category?: string;
  }) =>
    request<{ match: import('./types').PIIMatch; index: number }>('/api/pii/manual', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  previewPage: (pdf_path: string, page_num: number) =>
    request<import('./types').PreviewResponse>('/api/preview', {
      method: 'POST',
      body: JSON.stringify({ pdf_path, page_num }),
    }),

  openFolder: (folder_path: string) =>
    request<{ status: string }>('/api/folder/open', {
      method: 'POST',
      body: JSON.stringify({ folder_path }),
    }),

  readOutput: (output_folder: string, file_path: string) =>
    request<{ content: string }>('/api/output/read', {
      method: 'POST',
      body: JSON.stringify({ output_folder, file_path }),
    }),

  cleanupList: (output_path: string) =>
    request<{ files: string[] }>('/api/cleanup/list', {
      method: 'POST',
      body: JSON.stringify({ output_path }),
    }),

  cleanup: (output_folder: string, file_paths: string[]) =>
    request<{ deleted: string[]; failed: { path: string; reason: string }[] }>('/api/cleanup', {
      method: 'POST',
      body: JSON.stringify({ output_folder, file_paths }),
    }),
};
