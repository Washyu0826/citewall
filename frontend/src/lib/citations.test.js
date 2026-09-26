import { describe, expect, it } from 'vitest';
import { FALLBACK_KEY, buildCitationLookup, lookupForRejection } from './citations.js';

const hit = (patent_no, rejection_id, ref_index) => ({
  patent_no,
  metadata: rejection_id ? { rejection_id, ref_index } : {},
});

describe('buildCitationLookup', () => {
  it('numbers GROUNDED_REF per rejection, not across the flattened list', () => {
    const lookup = buildCitationLookup([
      hit('US111', 'R1', 1),
      hit('US222', 'R1', 2),
      hit('TW333', 'R2', 1),
    ]);
    expect(lookupForRejection(lookup, 'R1')['[GROUNDED_REF_2]'].patent_no).toBe('US222');
    // The bug this fixes: R2's REF_1 must be TW333, not R1's first hit.
    expect(lookupForRejection(lookup, 'R2')['[GROUNDED_REF_1]'].patent_no).toBe('TW333');
    expect(lookupForRejection(lookup, 'R2')['[GROUNDED_REF_2]']).toBeUndefined();
  });

  it('falls back to positional indexing for untagged hits (older gateway)', () => {
    const lookup = buildCitationLookup([hit('US1'), hit('US2')]);
    expect(lookup[FALLBACK_KEY]['[GROUNDED_REF_2]'].patent_no).toBe('US2');
    expect(lookupForRejection(lookup, 'unknown')['[GROUNDED_REF_1]'].patent_no).toBe('US1');
  });

  it('caps the positional fallback at 20 and tolerates empty input', () => {
    const many = Array.from({ length: 25 }, (_, i) => hit(`US${i}`));
    expect(Object.keys(buildCitationLookup(many)[FALLBACK_KEY])).toHaveLength(20);
    expect(lookupForRejection(buildCitationLookup(undefined), 'R1')).toEqual({});
    expect(lookupForRejection(undefined, 'R1')).toEqual({});
  });
});
