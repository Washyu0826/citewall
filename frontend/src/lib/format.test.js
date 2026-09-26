import { describe, expect, it } from 'vitest';
import { formatCurrency, formatDate, formatNumber } from './format.js';

describe('formatDate', () => {
  it('treats a bare YYYY-MM-DD as a LOCAL calendar date (no UTC day shift)', () => {
    // new Date('2025-04-30') is UTC midnight → "04/29" west of UTC. The local
    // parse must keep the calendar day regardless of the runner's timezone.
    expect(formatDate('2025-04-30', { locale: 'en-US' })).toBe('04/30/2025');
    expect(formatDate('2025-04-30', { era: 'roc' })).toBe('民國114年04月30日');
  });

  it('keeps the calendar day west of UTC (where the naive parse drifts)', () => {
    const prev = process.env.TZ;
    process.env.TZ = 'America/Los_Angeles';
    try {
      // Control: the naive UTC parse really does drift a day here…
      expect(new Date('2025-04-30').getDate()).toBe(29);
      // …while formatDate keeps the calendar date.
      expect(formatDate('2025-04-30', { locale: 'en-US' })).toBe('04/30/2025');
    } finally {
      if (prev === undefined) delete process.env.TZ;
      else process.env.TZ = prev;
    }
  });

  it('renders ROC era', () => {
    expect(formatDate(new Date(2025, 0, 5), { era: 'roc' })).toBe('民國114年01月05日');
  });

  it('returns "" for invalid input instead of throwing', () => {
    expect(formatDate('not a date')).toBe('');
    expect(formatDate(null)).toBe('');
    expect(formatDate('2025-13-45')).toBe('');
  });
});

describe('formatNumber / formatCurrency', () => {
  it('groups digits', () => {
    expect(formatNumber(1234567, 'en-US')).toBe('1,234,567');
  });

  it('never throws on bad input', () => {
    expect(() => formatNumber('x')).not.toThrow();
    expect(() => formatCurrency(undefined)).not.toThrow();
  });
});
