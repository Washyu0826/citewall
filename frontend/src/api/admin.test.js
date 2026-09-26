import { describe, expect, it } from 'vitest';

import { filterCases } from './admin.js';

const cases = [
  { case_id: 'CASE-2025-001', note: 'pilot client' },
  { case_id: 'CASE-2026-042', note: '' },
  { case_id: 'CASE-TW-7', note: 'Semiconductor' },
];

describe('filterCases', () => {
  it('returns everything for an empty query', () => {
    expect(filterCases(cases, '')).toBe(cases);
    expect(filterCases(cases, '   ')).toBe(cases);
  });
  it('matches case_id case-insensitively', () => {
    expect(filterCases(cases, 'case-2026').map((c) => c.case_id)).toEqual(['CASE-2026-042']);
  });
  it('matches the note', () => {
    expect(filterCases(cases, 'semicon').map((c) => c.case_id)).toEqual(['CASE-TW-7']);
  });
  it('tolerates a missing note', () => {
    expect(filterCases([{ case_id: 'X' }], 'zzz')).toEqual([]);
  });
});
