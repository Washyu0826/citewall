import { describe, expect, it } from 'vitest';

import { filterCases, normalizeRegistry } from './admin.js';

describe('normalizeRegistry', () => {
  it('passes a well-formed body through', () => {
    const body = {
      cases: [{ case_id: 'CASE-1', level: 'public' }],
      patterns: [{ pattern: 'CASE-DEMO-*', level: 'public' }],
      levels: ['confidential', 'public', 'top_secret'],
    };
    expect(normalizeRegistry(body)).toEqual(body);
  });
  it('turns a malformed body into an empty registry instead of throwing', () => {
    // The shape that crashed the page: patterns as an object, levels missing.
    expect(normalizeRegistry({ cases: [], patterns: {} })).toEqual({
      cases: [],
      patterns: [],
      levels: ['public', 'confidential'],
    });
    expect(normalizeRegistry(null).cases).toEqual([]);
    expect(normalizeRegistry('<html>502</html>').levels).toEqual(['public', 'confidential']);
  });
  it('drops rows without an id', () => {
    expect(normalizeRegistry({ cases: [{ case_id: 'A' }, {}, null] }).cases).toEqual([{ case_id: 'A' }]);
  });
});

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
