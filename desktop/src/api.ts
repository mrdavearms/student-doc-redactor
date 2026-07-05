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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), DEFAULT_TIMEOUT_MS);
  const signal = options?.signal
    ? AbortSignal.any([options.signal, timeoutController.signal])
    : timeoutController.signal;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
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
    }),

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
  }, options?: RequestInit) =>
    request<import('./types').RedactionResults>('/api/redact', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
    }),

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
