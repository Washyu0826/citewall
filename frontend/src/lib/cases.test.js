import { describe, expect, it } from 'vitest';

import {
  caseStatus,
  dashboardStats,
  daysUntil,
  deadlineTone,
  filterCases,
  isConfidentialLevel,
  upcomingDeadlines,
} from './cases.js';

const NOW = new Date(2026, 8, 30, 15, 0); // 2026-09-30 15:00 local

function row(id, { level = 'public', deadline = null, degraded = false, analyzed = true } = {}) {
  return {
    case_id: id,
    security_level: level,
    last_activity: null,
    last_analysis: analyzed ? { statutory_deadline: deadline, degraded, rejection_types: [] } : null,
  };
}

describe('daysUntil', () => {
  it('counts calendar days, ignoring the time of day', () => {
    expect(daysUntil('2026-10-01T00:30:00', NOW)).toBe(1);
    expect(daysUntil('2026-09-30T23:59:00', NOW)).toBe(0);
    expect(daysUntil('2026-09-29T08:00:00', NOW)).toBe(-1);
  });
  it('returns null for missing or invalid dates', () => {
    expect(daysUntil(null, NOW)).toBeNull();
    expect(daysUntil('not a date', NOW)).toBeNull();
  });
});

describe('deadlineTone', () => {
  it('flags overdue as error and the next 14 days as warning', () => {
    expect(deadlineTone(-1)).toBe('error');
    expect(deadlineTone(0)).toBe('warning');
    expect(deadlineTone(14)).toBe('warning');
    expect(deadlineTone(15)).toBe('neutral');
    expect(deadlineTone(null)).toBe('neutral');
  });
});

describe('isConfidentialLevel', () => {
  it('treats everything but an explicit public as confidential (fail-closed)', () => {
    expect(isConfidentialLevel('public')).toBe(false);
    expect(isConfidentialLevel('confidential')).toBe(true);
    expect(isConfidentialLevel('top_secret')).toBe(true);
    expect(isConfidentialLevel(undefined)).toBe(true);
  });
});

describe('caseStatus', () => {
  it('distinguishes not analyzed, degraded and analyzed', () => {
    expect(caseStatus(row('A', { analyzed: false }))).toBe('not_analyzed');
    expect(caseStatus(row('B', { degraded: true }))).toBe('degraded');
    expect(caseStatus(row('C'))).toBe('analyzed');
  });
});

describe('dashboard helpers', () => {
  const cases = [
    row('LATE', { deadline: '2026-09-20T23:59:00' }),
    row('SOON', { deadline: '2026-10-05T23:59:00', level: 'confidential' }),
    row('LATER', { deadline: '2026-12-01T23:59:00' }),
    row('NEW', { analyzed: false }),
  ];

  it('orders upcoming deadlines soonest first, overdue leading', () => {
    expect(upcomingDeadlines(cases, NOW).map((c) => c.case_id)).toEqual(['LATE', 'SOON', 'LATER']);
  });

  it('counts the dashboard tiles', () => {
    expect(dashboardStats(cases, NOW)).toEqual({
      total: 4,
      dueSoon: 1,
      overdue: 1,
      confidential: 1,
      notAnalyzed: 1,
    });
  });

  it('filters by query and by category', () => {
    expect(filterCases(cases, { query: 'soo' }, NOW).map((c) => c.case_id)).toEqual(['SOON']);
    expect(filterCases(cases, { filter: 'due_soon' }, NOW).map((c) => c.case_id)).toEqual(['LATE', 'SOON']);
    expect(filterCases(cases, { filter: 'not_analyzed' }, NOW).map((c) => c.case_id)).toEqual(['NEW']);
    expect(filterCases(cases, { filter: 'confidential' }, NOW).map((c) => c.case_id)).toEqual(['SOON']);
  });
});
