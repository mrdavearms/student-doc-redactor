/**
 * API client — talks to the FastAPI backend on localhost.
 */

const BASE = 'http://127.0.0.1:8765';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
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
  }, options?: RequestInit) =>
    request<import('./types').RedactionResults>('/api/redact', {
      method: 'POST',
      body: JSON.stringify(params),
      ...options,
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
};
