import { useMutation, useQuery } from '@tanstack/react-query';

import { api } from './client.js';

/**
 * TanStack Query hooks over the transport in client.js (P1③).
 *
 * client.js stays the thin fetch/transport layer; these hooks own caching,
 * de-dupe, retry and polling. Components consume the hooks instead of
 * hand-rolling useState+useEffect+fetch.
 */

/** Per-user / per-tenant usage — not case-scoped, so one cache entry. */
export function useQuota(token, enabled = true) {
  return useQuery({
    queryKey: ['quota'],
    queryFn: () => api.quota(token),
    enabled: enabled && !!token,
    // Quota fetch failing must never block the analyze surface — the old code
    // swallowed the error (.catch(()=>{})); mirror that by not retrying.
    retry: false,
  });
}

/** Accessible cases + server-resolved security level + last-analysis metadata. */
export function useCases(token, enabled = true) {
  return useQuery({
    queryKey: ['cases'],
    queryFn: () => api.cases(token),
    enabled: enabled && !!token,
    staleTime: 30_000,
  });
}

export function useAuditRecent(token, enabled = true) {
  return useQuery({
    queryKey: ['audit', 'recent'],
    queryFn: () => api.auditRecent(token),
    enabled: enabled && !!token,
  });
}

/**
 * Chain verification. AppShell (poll=true) and AuditView (poll=false) pass the
 * SAME scope so they share the queryKey ['audit','verify',scope] — one request
 * serves both, killing the duplicate verify call (the top finding in the
 * frontend architecture review).
 */
export function useAuditVerify(token, scope = 'tenant', { poll = false, enabled = true } = {}) {
  return useQuery({
    queryKey: ['audit', 'verify', scope],
    queryFn: () => api.auditVerify(token, scope),
    enabled: enabled && !!token,
    refetchInterval: poll ? 60_000 : false,
  });
}

export function useAnalyze(token) {
  return useMutation({
    mutationFn: (payload) => api.analyze(token, payload),
  });
}
