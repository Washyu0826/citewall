import { describe, expect, it } from 'vitest';
import {
  FALLBACK_KEY,
  buildCitationLookup,
  hitsForRejection,
  lookupForRejection,
} from './citations.js';

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

  it('hitsForRejection shows the grounding hits even when the examiner did not cite them', () => {
    const result = {
      oa: {
        rejections: [
          { rejection_id: 'R1', cited_prior_art: ['US222'] },
          { rejection_id: 'R2', cited_prior_art: [] },
        ],
      },
      related_prior_art: [hit('US222', 'R1', 2), hit('US111', 'R1', 1), hit('TW333', 'R2', 1)],
    };
    const r1 = hitsForRejection(result, 'R1');
    // The old panel filtered by cited_prior_art and hid US111 (= GROUNDED_REF_1).
    expect(r1.map((h) => h.patent_no)).toEqual(['US111', 'US222']);
    expect(r1.map((h) => h.examinerCited)).toEqual([false, true]);
    expect(hitsForRejection(result, 'R2').map((h) => h.patent_no)).toEqual(['TW333']);
  });

  it('hitsForRejection falls back to the cited filter for untagged hits', () => {
    const result = {
      oa: { rejections: [{ rejection_id: 'R1', cited_prior_art: ['US2'] }] },
      related_prior_art: [hit('US1'), hit('US2')],
    };
    expect(hitsForRejection(result, 'R1').map((h) => h.patent_no)).toEqual(['US2']);
    expect(hitsForRejection(undefined, 'R1')).toEqual([]);
  });

  it('caps the positional fallback at 20 and tolerates empty input', () => {
    const many = Array.from({ length: 25 }, (_, i) => hit(`US${i}`));
    expect(Object.keys(buildCitationLookup(many)[FALLBACK_KEY])).toHaveLength(20);
    expect(lookupForRejection(buildCitationLookup(undefined), 'R1')).toEqual({});
    expect(lookupForRejection(undefined, 'R1')).toEqual({});
  });
});
