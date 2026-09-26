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

/** Case-insensitive filter over case_id + note. Pure — unit tested. */
export function filterCases(cases, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return cases;
  return cases.filter(
    (c) => c.case_id.toLowerCase().includes(q) || (c.note || '').toLowerCase().includes(q)
  );
}
