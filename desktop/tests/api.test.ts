import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, BackendUnreachableError, __resetApiTokenCache } from '../src/api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  __resetApiTokenCache();
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

  // Word conversion spawns a fresh soffice per file, so a folder of a dozen
  // documents runs well past a minute. Timing out there reported a healthy
  // backend as dead and told the user to restart, losing the run.
  it('gives folder conversion far longer than the default minute', async () => {
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

    let failure: unknown = null;
    const p = api.processFolder('/some/folder').catch((e) => { failure = e; });

    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(failure).toBeNull();

    await vi.advanceTimersByTimeAsync(30 * 60_000);
    await p;
    expect(failure).toBeInstanceOf(BackendUnreachableError);
  });

  it('gives single-document preparation the same long timeout', async () => {
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

    let failure: unknown = null;
    const p = api.processFile('/some/file.docx').catch((e) => { failure = e; });

    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(failure).toBeNull();

    await vi.advanceTimersByTimeAsync(30 * 60_000);
    await p;
    expect(failure).toBeInstanceOf(BackendUnreachableError);
  });

  it('propagates an external AbortError without converting it', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        // Mirror real fetch(): check the already-aborted case synchronously,
        // not just future 'abort' events. request() now awaits the API token
        // before calling fetch, so by the time this mock runs, the combined
        // signal may already be aborted rather than about to fire.
        const rejectAborted = () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        };
        if (opts.signal?.aborted) {
          rejectAborted();
          return;
        }
        opts.signal?.addEventListener('abort', rejectAborted);
      }),
    );
    const p = api.processFolder('/some/folder', { signal: controller.signal });
    controller.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('api token header', () => {
  it('sends X-Api-Token when Electron provides one', async () => {
    let captured: Record<string, string> = {};
    vi.stubGlobal('window', { electronAPI: { getApiToken: () => Promise.resolve('tok-123') } });
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) => {
      captured = (opts.headers ?? {}) as Record<string, string>;
      return Promise.resolve(new Response(JSON.stringify({ status: 'ok', version: 'x' })));
    });
    await api.health();
    expect(captured['X-Api-Token']).toBe('tok-123');
  });

  it('omits the header outside Electron', async () => {
    let captured: Record<string, string> = {};
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', (_url: string, opts: RequestInit = {}) => {
      captured = (opts.headers ?? {}) as Record<string, string>;
      return Promise.resolve(new Response(JSON.stringify({ status: 'ok', version: 'x' })));
    });
    await api.health();
    expect(captured['X-Api-Token']).toBeUndefined();
  });

  it('surfaces the 401 detail as a readable Error (the real network path)', async () => {
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', () =>
      Promise.resolve(new Response(
        JSON.stringify({ detail: 'Invalid or missing API token' }),
        { status: 401 },
      )),
    );
    await expect(api.health()).rejects.toThrow('Invalid or missing API token');
  });
});
