import { describe, expect, it } from 'vitest';
import { buildDeadlineIcs } from './ics.js';

const t = (key, opts) => (opts?.caseId ? `${key}:${opts.caseId}` : key);

describe('buildDeadlineIcs', () => {
  const deadline = {
    statutory_deadline: '2025-07-15T00:00:00Z',
    recommended_internal_deadline: '2025-07-08T00:00:00Z',
    holiday_calendar_version: '2025.1+2026.1',
    warnings: ['a, b; c'],
  };

  it('emits two all-day events with exclusive DTEND and alarms', () => {
    const ics = buildDeadlineIcs({ caseId: 'CASE-1', deadline, t });
    expect(ics).toContain('DTSTART;VALUE=DATE:20250715');
    expect(ics).toContain('DTEND;VALUE=DATE:20250716');
    expect(ics).toContain('DTSTART;VALUE=DATE:20250708');
    expect(ics).toContain('TRIGGER:-P7D');
    expect(ics).toContain('TRIGGER:-P3D');
    expect(ics).toContain('UID:CASE-1-statutory@citewall.local');
  });

  it('uses CRLF line endings and escapes TEXT values (RFC 5545)', () => {
    const ics = buildDeadlineIcs({ caseId: 'CASE-1', deadline, t });
    expect(ics.split('\r\n')[0]).toBe('BEGIN:VCALENDAR');
    expect(ics).toContain('a\\, b\\; c');
  });

  it('rolls DTEND across a month boundary', () => {
    const ics = buildDeadlineIcs({
      caseId: 'C',
      deadline: { statutory_deadline: '2025-04-30' },
      t,
    });
    expect(ics).toContain('DTEND;VALUE=DATE:20250501');
    expect(ics).not.toContain('internal@');
  });

  it('returns null when there is no parsable statutory deadline', () => {
    expect(buildDeadlineIcs({ caseId: 'C', deadline: {}, t })).toBeNull();
    expect(buildDeadlineIcs({ caseId: 'C', deadline: { statutory_deadline: 'x' }, t })).toBeNull();
  });
});
