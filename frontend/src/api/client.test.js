import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, SESSION_EXPIRED_EVENT, api, call } from './client.js';

function mockFetch(status, body, headers = {}) {
  const res = {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'Status ' + status,
    headers: new Headers(headers),
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  };
  globalThis.fetch = vi.fn(async () => res);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  delete globalThis.fetch;
});

describe('call() error contract', () => {
  it('turns a 422 detail array into one string and keeps the request id (B-9, B-14)', async () => {
    mockFetch(
      422,
      { detail: [{ loc: ['body', 'target_patent_no'], msg: 'String should have at most 64 characters' }] },
      { 'X-Request-ID': 'req-abc123' }
    );
    const err = await call('/v1/oa/analyze', { method: 'POST', body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(typeof err.message).toBe('string');
    expect(err.message).toBe('target_patent_no: String should have at most 64 characters');
    expect(err.requestId).toBe('req-abc123');
  });

  it('fires the session-expired event on an authenticated 401 only', async () => {
    const seen = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, seen);
    mockFetch(401, { detail: 'token expired' });
    await call('/v1/cases', { token: 't' }).catch(() => {});
    expect(seen).toHaveBeenCalledTimes(1);
    await call('/v1/auth/login', { method: 'POST', body: {} }).catch(() => {});
    expect(seen).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_EXPIRED_EVENT, seen);
  });

  it('a timeout message carries no path (paths are not for users)', async () => {
    globalThis.fetch = vi.fn(async () => {
      const e = new Error('aborted');
      e.name = 'AbortError';
      throw e;
    });
    const err = await call('/v1/quota', { timeoutMs: 5 }).catch((e) => e);
    expect(err.status).toBe(408);
    expect(err.message).not.toContain('/v1/');
  });
});

describe('call() cancellation (research 09 FE-L1)', () => {
  const abortingFetch = () =>
    vi.fn(
      (_url, { signal }) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => {
            const e = new Error('aborted');
            e.name = 'AbortError';
            reject(e);
          });
        })
    );

  it('reports the caller aborting as a cancellation, not an error to show', async () => {
    globalThis.fetch = abortingFetch();
    const controller = new AbortController();
    const pending = call('/v1/oa/analyze', { signal: controller.signal, timeoutMs: 60_000 }).catch((e) => e);
    controller.abort();
    const err = await pending;
    expect(err.cancelled).toBe(true);
    expect(err.status).not.toBe(408);
  });

  it('still reports its own timeout as a 408 when a caller signal is present', async () => {
    globalThis.fetch = abortingFetch();
    const controller = new AbortController();
    const err = await call('/v1/oa/analyze', { signal: controller.signal, timeoutMs: 5 }).catch((e) => e);
    expect(err.status).toBe(408);
    expect(err.cancelled).toBeUndefined();
  });

  it('does not even start a request whose signal is already aborted', async () => {
    globalThis.fetch = abortingFetch();
    const controller = new AbortController();
    controller.abort();
    const err = await call('/v1/oa/analyze', { signal: controller.signal }).catch((e) => e);
    expect(err.cancelled).toBe(true);
  });
});

describe('api.login — the public mock-mode demo (phase 5)', () => {
  const sentBody = () => JSON.parse(globalThis.fetch.mock.calls[0][1].body);

  it('sends only the user id by default', async () => {
    mockFetch(200, { token: 't' });
    await api.login('alice');
    expect(sentBody()).toEqual({ user_id: 'alice' });
  });

  it('sends the published demo password when the demo build flag is on', async () => {
    vi.stubEnv('VITE_DEMO_PUBLIC_PASSWORDS', 'true');
    mockFetch(200, { token: 't' });
    await api.login('alice');
    expect(sentBody()).toEqual({ user_id: 'alice', password: 'demo-alice' });
  });
});
