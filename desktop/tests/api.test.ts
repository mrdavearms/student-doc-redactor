import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, BackendUnreachableError } from '../src/api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('request timeout', () => {
  it('rejects with BackendUnreachableError when the backend never responds', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      }),
    );

    const p = api.health();
    const expectation = expect(p).rejects.toBeInstanceOf(BackendUnreachableError);
    await vi.advanceTimersByTimeAsync(60_000);
    await expectation;
  });

  it('propagates an external AbortError without converting it', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      }),
    );
    const p = api.processFolder('/some/folder', { signal: controller.signal });
    controller.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
  });
});
