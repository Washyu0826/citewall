import { describe, expect, it } from 'vitest';

import { normalizeAuditRows, normalizeQuota, normalizeRedactionPreview } from './normalize.js';

describe('normalizeQuota', () => {
  it('keeps a well-formed snapshot (and its extra fields)', () => {
    const q = normalizeQuota({
      user_daily_used: 10,
      user_daily_limit: 100,
      tenant_monthly_used: 5,
      tenant_monthly_cap: 50,
      circuit_breaker: { current_usd: 1.5, threshold_usd: 100, tripped: false, tenant_id: 'tenant_a' },
      budget: { status: 'ok' },
    });
    expect(q.user_daily_used).toBe(10);
    expect(q.circuit_breaker).toEqual({ current_usd: 1.5, threshold_usd: 100, tripped: false, tenant_id: 'tenant_a' });
    expect(q.budget).toEqual({ status: 'ok' });
  });

  it('fills a missing circuit breaker instead of crashing the setup page', () => {
    const q = normalizeQuota({ user_daily_used: 7, tenant_monthly_cap: null });
    expect(q.user_daily_used).toBe(7);
    expect(q.tenant_monthly_cap).toBe(0);
    expect(q.circuit_breaker).toEqual({ current_usd: 0, threshold_usd: 0, tripped: false });
  });

  it('returns null — never a table of made-up zeros — for something that is not a snapshot', () => {
    // call() hands a non-JSON 200 (a proxy's page) on as {raw: …} (review W2b-E5).
    expect(normalizeQuota({ raw: '<html>502 Bad Gateway</html>' })).toBeNull();
    expect(normalizeQuota({ user_daily_used: '7' })).toBeNull();
    expect(normalizeQuota(null)).toBeNull();
    expect(normalizeQuota([1, 2])).toBeNull();
  });
});

describe('normalizeAuditRows', () => {
  it('coerces each field the table renders', () => {
    const [row] = normalizeAuditRows([
      {
        audit_id: 'a1',
        timestamp_utc: '2026-10-06T00:00:00Z',
        user_id: 'alice',
        case_id: null,
        endpoint: '/v1/oa/analyze',
        model_used: null,
        prompt_tokens: 3,
        completion_tokens: 'x',
        latency_ms: 12,
        masked_field_rules: ['email', 5],
        policy_decisions: { authz_passed: true, junk: { nested: 1 } },
      },
    ]);
    expect(row.case_id).toBe('');
    expect(row.model_used).toBe('');
    expect(row.completion_tokens).toBe(0);
    expect(row.masked_field_rules).toEqual(['email']);
    expect(row.policy_decisions).toEqual({ authz_passed: true });
  });

  it('keeps the scalar facts auditors read next to the gates (review W2b-E1)', () => {
    // The export endpoint records provenance counts; the registry an outcome.
    const [row] = normalizeAuditRows([
      {
        audit_id: 'e1',
        policy_decisions: {
          authz_passed: true,
          attorney_signoff: true,
          prov_total_segments: 4,
          prov_attorney_edited: 0,
          outcome: 'ok',
          nested: { a: 1 },
          list: [1],
        },
      },
    ]);
    expect(row.policy_decisions).toEqual({
      authz_passed: true,
      attorney_signoff: true,
      prov_total_segments: 4,
      prov_attorney_edited: 0,
      outcome: 'ok',
    });
  });

  it('accepts {rows: [...]} and drops non-objects; anything else is an empty table', () => {
    expect(normalizeAuditRows({ rows: [{ audit_id: 'b' }, 'x', null] })).toHaveLength(1);
    expect(normalizeAuditRows({ detail: 'Not Found' })).toEqual([]);
    expect(normalizeAuditRows(undefined)).toEqual([]);
  });

  it('gives a row without an id a stable key', () => {
    expect(normalizeAuditRows([{}, {}]).map((r) => r.audit_id)).toEqual(['row-0', 'row-1']);
  });
});

describe('normalizeRedactionPreview', () => {
  it('passes a real preview through', () => {
    expect(normalizeRedactionPreview({ redacted: 'a [EMAIL_1]', rules_triggered: ['email'] })).toEqual({
      redacted: 'a [EMAIL_1]',
      rules_triggered: ['email'],
    });
    expect(normalizeRedactionPreview({ redacted: 'no PII here' })).toEqual({ redacted: 'no PII here', rules_triggered: [] });
  });

  it('is null — an error for the caller, never an empty "nothing to mask" preview — without the masked text', () => {
    expect(normalizeRedactionPreview({ redacted: { x: 1 }, rules_triggered: ['email'] })).toBeNull();
    expect(normalizeRedactionPreview({ raw: '<html>' })).toBeNull();
    expect(normalizeRedactionPreview(null)).toBeNull();
  });
});
