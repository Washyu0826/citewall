import { describe, expect, it } from 'vitest';
import {
  buildDeadlineRequestFields,
  isIsoDate,
  showNotReviewedNote,
  startBasisKey,
} from './deadlineInputs.js';

describe('buildDeadlineRequestFields', () => {
  it('sends nothing for an untouched form', () => {
    expect(buildDeadlineRequestFields({ domicile: 'unknown', oaSequence: '', serviceDate: '' })).toEqual({});
    expect(buildDeadlineRequestFields()).toEqual({});
  });

  it('maps the domicile tri-state to applicant_domestic', () => {
    expect(buildDeadlineRequestFields({ domicile: 'domestic' })).toEqual({ applicant_domestic: true });
    expect(buildDeadlineRequestFields({ domicile: 'foreign' })).toEqual({ applicant_domestic: false });
  });

  it('accepts oa_sequence 1..50 only', () => {
    expect(buildDeadlineRequestFields({ oaSequence: '2' })).toEqual({ oa_sequence: 2 });
    expect(buildDeadlineRequestFields({ oaSequence: 50 })).toEqual({ oa_sequence: 50 });
    for (const bad of ['0', '51', '1.5', 'abc', ' ']) {
      expect(buildDeadlineRequestFields({ oaSequence: bad })).toEqual({});
    }
  });

  it('accepts only real ISO dates for service_date', () => {
    expect(buildDeadlineRequestFields({ serviceDate: '2026-03-02' })).toEqual({
      service_date: '2026-03-02',
    });
    expect(buildDeadlineRequestFields({ serviceDate: '2026-02-30' })).toEqual({});
    expect(buildDeadlineRequestFields({ serviceDate: '03/02/2026' })).toEqual({});
  });
});

describe('isIsoDate', () => {
  it.each([
    ['2024-02-29', true],
    ['2025-02-29', false],
    ['2025-13-01', false],
    ['', false],
    [null, false],
  ])('%s -> %s', (v, ok) => {
    expect(isIsoDate(v)).toBe(ok);
  });
});

describe('startBasisKey', () => {
  it('maps known bases to i18n keys and ignores the rest', () => {
    expect(startBasisKey('presumed_service')).toBe('deadline_detail.basis.presumed_service');
    expect(startBasisKey('mailing_date_fallback')).toBe(
      'deadline_detail.basis.mailing_date_fallback'
    );
    expect(startBasisKey('something_else')).toBeNull();
    expect(startBasisKey(undefined)).toBeNull();
  });
});

describe('showNotReviewedNote', () => {
  it('hides the note only when rules_reviewed is explicitly true', () => {
    expect(showNotReviewedNote({ rules_reviewed: false })).toBe(true);
    expect(showNotReviewedNote({})).toBe(true);
    expect(showNotReviewedNote(undefined)).toBe(true);
    expect(showNotReviewedNote({ rules_reviewed: true })).toBe(false);
  });
});
