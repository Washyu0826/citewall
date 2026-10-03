import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, SESSION_EXPIRED_EVENT, call } from './client.js';

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
