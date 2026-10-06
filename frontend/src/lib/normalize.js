/**
 * Response normalisation for the views (research 09 FE-5) — the idea of
 * normalizeRegistry (FAILURE_LOG B-7) applied to the other responses views
 * read field by field: an unexpected shape (an older or newer backend, the
 * minimal backend, a proxy's error page) used to crash the page
 * (`quota.circuit_breaker.current_usd`, `rules_triggered.length`, `rows.map`).
 * Normalised once at the query layer into exactly the shape the view renders.
 * Unknown extra fields are kept. Pure — unit tested in normalize.test.js.
 */

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const str = (v) => (typeof v === 'string' ? v : '');
const strList = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
const boolMap = (v) =>
  isObj(v) ? Object.fromEntries(Object.entries(v).filter(([, b]) => typeof b === 'boolean')) : {};

/** GET /v1/quota → usage bars + cost breaker; null when unusable. */
export function normalizeQuota(data) {
  if (!isObj(data)) return null;
  const cb = isObj(data.circuit_breaker) ? data.circuit_breaker : {};
  return {
    ...data,
    user_daily_used: num(data.user_daily_used),
    user_daily_limit: num(data.user_daily_limit),
    tenant_monthly_used: num(data.tenant_monthly_used),
    tenant_monthly_cap: num(data.tenant_monthly_cap),
    circuit_breaker: {
      ...cb,
      current_usd: num(cb.current_usd),
      threshold_usd: num(cb.threshold_usd),
      tripped: cb.tripped === true,
    },
  };
}

/** GET /v1/audit/recent → table rows (an array; `{rows: [...]}` accepted). */
export function normalizeAuditRows(data) {
  const list = Array.isArray(data) ? data : Array.isArray(data?.rows) ? data.rows : [];
  return list.filter(isObj).map((r, i) => ({
    ...r,
    audit_id: str(r.audit_id) || `row-${i}`,
    timestamp_utc: str(r.timestamp_utc),
    user_id: str(r.user_id),
    case_id: str(r.case_id),
    endpoint: str(r.endpoint),
    model_used: str(r.model_used),
    prompt_tokens: num(r.prompt_tokens),
    completion_tokens: num(r.completion_tokens),
    latency_ms: num(r.latency_ms),
    masked_field_rules: strList(r.masked_field_rules),
    policy_decisions: boolMap(r.policy_decisions),
  }));
}

/** POST /v1/redaction/preview → what the preview panel shows; null when unusable. */
export function normalizeRedactionPreview(data) {
  if (!isObj(data)) return null;
  return { ...data, redacted: str(data.redacted), rules_triggered: strList(data.rules_triggered) };
}
