import { describe, expect, it } from 'vitest';

import { CASE_BOUND_FIELDS, dropCaseBound, hasUnsavedDecisions } from './workspaceState.js';

const line = (status, source = 'ai_generated') => ({ segment_id: 's', text: 't', status, source });

describe('hasUnsavedDecisions', () => {
  const base = { result: { drafts: [] } };

  it('is false with nothing decided', () => {
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: [line('pending')] } } })).toBe(false);
    expect(hasUnsavedDecisions({ ...base })).toBe(false);
    expect(hasUnsavedDecisions({})).toBe(false);
  });

  it('is true once a sentence is accepted, excluded, edited or added', () => {
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: [line('accepted')] } } })).toBe(true);
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: [line('excluded')] } } })).toBe(true);
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: [line('pending', 'attorney_edited')] } } })).toBe(true);
  });

  it('is false when that rejection — or the whole response — was exported', () => {
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: [line('accepted')], exportResult: {} } } })).toBe(false);
    expect(
      hasUnsavedDecisions({ ...base, responseExported: true, editors: { r1: { lines: [line('accepted')] } } })
    ).toBe(false);
  });

  it('ignores editor state left without a result', () => {
    expect(hasUnsavedDecisions({ editors: { r1: { lines: [line('accepted')] } } })).toBe(false);
  });
});

describe('dropCaseBound', () => {
  it('drops the analysis but keeps the typed inputs', () => {
    const next = dropCaseBound({ oaText: 'OA', targetPatent: 'US1', result: {}, progress: {}, editors: {}, error: 'x' });
    expect(next).toEqual({ oaText: 'OA', targetPatent: 'US1' });
  });

  it('returns the same object when there is nothing to drop', () => {
    const f = { oaText: 'OA' };
    expect(dropCaseBound(f)).toBe(f);
    expect(CASE_BOUND_FIELDS).toContain('editors');
  });
});
