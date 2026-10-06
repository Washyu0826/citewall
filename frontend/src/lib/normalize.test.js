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
    const q = normalizeQuota({ user_daily_used: '7', tenant_monthly_cap: null });
    expect(q.user_daily_used).toBe(0);
    expect(q.tenant_monthly_cap).toBe(0);
    expect(q.circuit_breaker).toEqual({ current_usd: 0, threshold_usd: 0, tripped: false });
  });

  it('returns null for something that is not a snapshot', () => {
    expect(normalizeQuota(null)).toBeNull();
    expect(normalizeQuota('<html>502</html>')).toBeNull();
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
  it('never hands an object to React as the preview text', () => {
    expect(normalizeRedactionPreview({ redacted: { x: 1 }, rules_triggered: 'email' })).toEqual({
      redacted: '',
      rules_triggered: [],
    });
    expect(normalizeRedactionPreview({ redacted: 'a [EMAIL_1]', rules_triggered: ['email'] })).toEqual({
      redacted: 'a [EMAIL_1]',
      rules_triggered: ['email'],
    });
    expect(normalizeRedactionPreview(null)).toBeNull();
  });
});
