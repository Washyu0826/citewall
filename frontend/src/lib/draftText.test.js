import { describe, expect, it } from 'vitest';
import { applyEdit, hasBlockingMarker, isAcceptBlocked, splitIntoLines } from './draftText.js';

const texts = (s) => splitIntoLines(s).map((l) => l.text);

describe('splitIntoLines', () => {
  it('splits zh-TW sentences with no space after 。！？', () => {
    expect(
      texts('申請人認為引證1未揭示特徵A。故請求項1具進步性！另請參照[GROUNDED_REF_1]。')
    ).toEqual(['申請人認為引證1未揭示特徵A。', '故請求項1具進步性！', '另請參照[GROUNDED_REF_1]。']);
  });

  it('does not split on legal abbreviations', () => {
    expect(
      texts(
        'Claim 1 is rejected under 35 U.S.C. § 103. See Patent No. [GROUNDED_REF_1] and Fig. 2 thereof. Applicant disagrees!'
      )
    ).toEqual([
      'Claim 1 is rejected under 35 U.S.C. § 103.',
      'See Patent No. [GROUNDED_REF_1] and Fig. 2 thereof.',
      'Applicant disagrees!',
    ]);
  });

  it('keeps a period without trailing whitespace inside a token', () => {
    expect(texts('version 1.2 is fine')).toEqual(['version 1.2 is fine']);
  });

  it('returns [] for empty input and seeds pending AI segments', () => {
    expect(splitIntoLines('')).toEqual([]);
    expect(splitIntoLines(null)).toEqual([]);
    const [first] = splitIntoLines('一句。');
    expect(first).toMatchObject({ segment_id: 'seg-0', source: 'ai_generated', status: 'pending' });
  });
});

describe('CITATION_REMOVED gates', () => {
  const ai = {
    segment_id: 's',
    text: 'X [CITATION_REMOVED] Y.',
    source: 'ai_generated',
    status: 'pending',
  };

  it('blocks accepting a line that still carries the marker', () => {
    expect(isAcceptBlocked(ai)).toBe(true);
    expect(isAcceptBlocked({ ...ai, text: 'clean.' })).toBe(false);
  });

  it('an edit that keeps the marker stays pending (no bypass)', () => {
    expect(applyEdit(ai, 'X [CITATION_REMOVED] rewritten.', 'attorney_edited').status).toBe(
      'pending'
    );
  });

  it('an edit that removes the marker is accepted and keeps provenance', () => {
    const edited = applyEdit(ai, 'X rewritten.', 'attorney_edited', new Date('2026-01-01T00:00:00Z'));
    expect(edited).toMatchObject({
      status: 'accepted',
      source: 'attorney_edited',
      edited_from: 'X [CITATION_REMOVED] Y.',
      ts: '2026-01-01T00:00:00.000Z',
    });
  });

  it('re-editing an added line keeps the *_added source', () => {
    const added = { segment_id: 'a', text: 'mine.', source: 'paralegal_added', status: 'accepted' };
    expect(applyEdit(added, 'mine v2.', 'attorney_edited').source).toBe('paralegal_added');
  });
});

describe('hasBlockingMarker (Q14/Q17)', () => {
  it('blocks CITATION_REMOVED and UNSUPPORTED_REF_n, not GROUNDED_REF_n', () => {
    expect(hasBlockingMarker('x [CITATION_REMOVED] y')).toBe(true);
    expect(hasBlockingMarker('x [UNSUPPORTED_REF_12] y')).toBe(true);
    expect(hasBlockingMarker('x [GROUNDED_REF_1] y')).toBe(false);
    expect(hasBlockingMarker('x [UNSUPPORTED_REF_] y')).toBe(false);
  });
  it('isAcceptBlocked / applyEdit honour the unsupported marker', () => {
    const line = { text: '句子[UNSUPPORTED_REF_2]。', source: 'ai_generated', status: 'pending' };
    expect(isAcceptBlocked(line)).toBe(true);
    expect(applyEdit(line, '仍有[UNSUPPORTED_REF_2]。', 'attorney_edited').status).toBe('pending');
    expect(applyEdit(line, '已改寫。', 'attorney_edited').status).toBe('accepted');
  });
});
