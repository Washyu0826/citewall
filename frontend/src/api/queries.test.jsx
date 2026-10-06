import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { api } from './client.js';
import { useAuditRecent, useQuota } from './queries.js';

// FE-5: the hooks hand views the normalised shape (lib/normalize.js), not the
// raw response — deleting a `select:` must fail here.

function wrapper({ children }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

describe('query hooks normalise what views read', () => {
  it('useQuota: a proxy error page is "unavailable", not a crash or zeros', async () => {
    vi.spyOn(api, 'quota').mockResolvedValue({ raw: '<html>502</html>' });
    const { result } = renderHook(() => useQuota('tok'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it('useQuota: a snapshot without the breaker gets one', async () => {
    vi.spyOn(api, 'quota').mockResolvedValue({ user_daily_used: 3, user_daily_limit: 10 });
    const { result } = renderHook(() => useQuota('tok'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data.circuit_breaker).toEqual({ current_usd: 0, threshold_usd: 0, tripped: false });
  });

  it('useAuditRecent: rows come back as a renderable array', async () => {
    vi.spyOn(api, 'auditRecent').mockResolvedValue({ rows: [{ audit_id: 'a', case_id: null }] });
    const { result } = renderHook(() => useAuditRecent('tok'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([expect.objectContaining({ audit_id: 'a', case_id: '' })]);
  });
});
