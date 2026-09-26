import { describe, expect, it } from 'vitest';

import {
  coveragePct,
  evidenceRefKey,
  statusCounts,
  statusKey,
  statusTone,
  tablesForRejection,
} from './elementTable.js';

const RESULT = {
  element_tables: [
    { rejection_id: 'rej-2', claim_no: 1, elements: [] },
    { rejection_id: 'rej-1', claim_no: 9, elements: [] },
    { rejection_id: 'rej-1', claim_no: 1, elements: [] },
  ],
};

describe('tablesForRejection', () => {
  it('filters by rejection and sorts by claim number', () => {
    expect(tablesForRejection(RESULT, 'rej-1').map((t) => t.claim_no)).toEqual([1, 9]);
  });
  it('tolerates older gateways without the field', () => {
    expect(tablesForRejection({}, 'rej-1')).toEqual([]);
    expect(tablesForRejection(null, 'rej-1')).toEqual([]);
  });
});

describe('status helpers', () => {
  it('maps statuses to tones and i18n keys', () => {
    expect(statusTone('disclosed')).toBe('rose');
    expect(statusTone('partial')).toBe('amber');
    expect(statusTone('not_disclosed')).toBe('emerald');
    expect(statusTone('weird')).toBe('slate');
    expect(statusKey('partial')).toBe('element_table.status.partial');
    expect(statusKey('weird')).toBe('element_table.status.no_evidence');
  });
  it('counts statuses', () => {
    const table = {
      elements: [{ status: 'disclosed' }, { status: 'partial' }, { status: 'partial' }, {}],
    };
    expect(statusCounts(table)).toEqual({
      disclosed: 1,
      partial: 2,
      not_disclosed: 0,
      no_evidence: 0,
    });
  });
});

describe('evidence helpers', () => {
  it('builds the GROUNDED_REF key the citation lookup uses', () => {
    expect(evidenceRefKey({ ref_index: 3 })).toBe('[GROUNDED_REF_3]');
    expect(evidenceRefKey({ ref_index: 0 })).toBeNull();
    expect(evidenceRefKey(null)).toBeNull();
  });
  it('formats coverage as a clamped whole percent', () => {
    expect(coveragePct(0.667)).toBe(67);
    expect(coveragePct(1.4)).toBe(100);
    expect(coveragePct(undefined)).toBeNull();
  });
});
