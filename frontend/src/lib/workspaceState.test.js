import { describe, expect, it } from 'vitest';

import { CASE_BOUND_FIELDS, dropCaseBound, hasUnsavedDecisions, mergeReceipt } from './workspaceState.js';

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

  it('is false when exactly the current sentences were exported — per rejection or as the whole response', () => {
    const lines = [line('accepted')];
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines, exportedLines: lines } } })).toBe(false);
    expect(
      hasUnsavedDecisions({ ...base, responseExport: { linesByRejection: { r1: lines } }, editors: { r1: { lines } } })
    ).toBe(false);
  });

  it('counts changes made after an export again (review W2b-D4)', () => {
    const exported = [line('accepted')];
    const changedAfter = [line('excluded')];
    expect(hasUnsavedDecisions({ ...base, editors: { r1: { lines: changedAfter, exportedLines: exported } } })).toBe(true);
    expect(
      hasUnsavedDecisions({
        ...base,
        responseExport: { linesByRejection: { r1: exported } },
        editors: { r1: { lines: changedAfter } },
      })
    ).toBe(true);
  });

  it('ignores editor state left without a result', () => {
    expect(hasUnsavedDecisions({ editors: { r1: { lines: [line('accepted')] } } })).toBe(false);
  });
});

describe('dropCaseBound', () => {
  it('drops the analysis but keeps the typed inputs', () => {
    const next = dropCaseBound({
      oaText: 'OA',
      targetPatent: 'US1',
      result: {},
      progress: {},
      editors: {},
      responseExport: {},
      error: 'x',
    });
    expect(next).toEqual({ oaText: 'OA', targetPatent: 'US1' });
  });

  it('returns the same object when there is nothing to drop', () => {
    const f = { oaText: 'OA' };
    expect(dropCaseBound(f)).toBe(f);
    expect(CASE_BOUND_FIELDS).toContain('editors');
  });
});

describe('mergeReceipt (review W2b-R1)', () => {
  const base = { result: { drafts: [] } };
  const receipt = (exportedLines) => ({ draft: 'D', exportResult: { document: 'doc' }, exportedLines });

  it('marks exactly the exported sentences as saved', () => {
    const lines = [line('accepted')];
    const editors = mergeReceipt({ r1: { draft: 'D', lines, reviewed: true } }, 'r1', receipt(lines));
    expect(editors.r1).toMatchObject({ lines, reviewed: true, exportResult: { document: 'doc' }, exportedLines: lines });
    expect(hasUnsavedDecisions({ ...base, editors })).toBe(false);
  });

  it('keeps sentences changed while the export ran — and they stay unsaved', () => {
    const sent = [line('accepted')];
    const changed = [line('excluded')];
    const other = { draft: 'X', lines: [line('pending')] };
    const editors = mergeReceipt({ r1: { draft: 'D', lines: changed }, r2: other }, 'r1', receipt(sent));
    expect(editors.r1.lines).toBe(changed);
    expect(editors.r1.exportedLines).toBe(sent);
    expect(editors.r2).toBe(other);
    expect(hasUnsavedDecisions({ ...base, editors })).toBe(true);
  });

  it('replaces an entry for another draft (or none) with what was exported', () => {
    const sent = [line('accepted')];
    for (const editors of [undefined, {}, { r1: { draft: 'OTHER', lines: [line('excluded')] } }]) {
      const next = mergeReceipt(editors, 'r1', receipt(sent));
      expect(next.r1).toEqual({ draft: 'D', lines: sent, reviewed: true, exportResult: { document: 'doc' }, exportedLines: sent });
    }
  });
});
