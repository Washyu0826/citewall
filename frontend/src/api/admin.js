import { call } from './client.js';

/**
 * Q27 case-registry admin API (it_admin only). case_id always travels in the
 * JSON body, never the URL (gateway rule: no case data in paths/logs).
 */
export const adminApi = {
  listCases: (token) => call('/v1/admin/cases', { token }),
  lookupCase: (token, case_id) =>
    call('/v1/admin/cases/lookup', { method: 'POST', token, body: { case_id } }),
  createCase: (token, { case_id, security_level, note }) =>
    call('/v1/admin/cases', { method: 'POST', token, body: { case_id, security_level, note } }),
  updateCase: (token, { case_id, security_level, note }) =>
    call('/v1/admin/cases', { method: 'PUT', token, body: { case_id, security_level, note } }),
  deactivateCase: (token, case_id) =>
    call('/v1/admin/cases/deactivate', { method: 'POST', token, body: { case_id } }),
};

const DEFAULT_LEVELS = ['public', 'confidential'];

/**
 * Coerce a /v1/admin/cases body into {cases, patterns, levels} arrays. A
 * malformed body (older gateway, proxy error page, bad mock) must render as an
 * empty registry — it used to throw inside render and take down the whole SPA
 * through the top-level error boundary. Pure — unit tested.
 */
export function normalizeRegistry(body) {
  const arr = (v) => (Array.isArray(v) ? v : []);
  const levels = arr(body?.levels).filter((l) => typeof l === 'string');
  return {
    cases: arr(body?.cases).filter((c) => c && typeof c.case_id === 'string'),
    patterns: arr(body?.patterns).filter((p) => p && typeof p.pattern === 'string'),
    levels: levels.length ? levels : DEFAULT_LEVELS,
  };
}

/** Case-insensitive filter over case_id + note. Pure — unit tested. */
export function filterCases(cases, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return cases;
  return cases.filter(
    (c) => c.case_id.toLowerCase().includes(q) || (c.note || '').toLowerCase().includes(q)
  );
}
