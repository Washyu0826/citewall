import { describe, expect, it } from 'vitest';

import { buildResponsePayload, exportReadiness } from './responseExport.js';

const R = [{ rejection_id: 'r1' }, { rejection_id: 'r2' }];
const seg = (id, accepted) => ({ segment_id: id, text: id, source: 'ai_generated', accepted });

describe('exportReadiness', () => {
  it('is ready only when every sentence of every rejection is decided', () => {
    const progress = {
      r1: { total: 2, decided: 2, accepted: 1, segments: [] },
      r2: { total: 3, decided: 2, accepted: 2, segments: [] },
    };
    expect(exportReadiness(R, progress)).toMatchObject({ ready: false, pending: 1 });
    progress.r2.decided = 3;
    expect(exportReadiness(R, progress)).toMatchObject({ ready: true, pending: 0, accepted: 3 });
  });

  it('is not ready while a rejection has not reported yet, or nothing is accepted', () => {
    expect(exportReadiness(R, { r1: { total: 1, decided: 1, accepted: 1 } })).toMatchObject({
      ready: false,
      missing: 1,
    });
    expect(
      exportReadiness(R, {
        r1: { total: 1, decided: 1, accepted: 0 },
        r2: { total: 1, decided: 1, accepted: 0 },
      }).ready
    ).toBe(false);
    expect(exportReadiness([], {}).ready).toBe(false);
  });
});

describe('buildResponsePayload', () => {
  it('builds one section per rejection in OA order, with the sign-off flag set', () => {
    const payload = buildResponsePayload({
      caseId: 'CASE-1',
      title: 'T',
      rejections: R,
      progress: { r1: { segments: [seg('a', true)] }, r2: { segments: [seg('b', false)] } },
      headingFor: (r, i) => `${i + 1}-${r.rejection_id}`,
    });
    expect(payload).toEqual({
      case_id: 'CASE-1',
      title: 'T',
      attorney_signoff: true,
      sections: [
        { rejection_id: 'r1', heading: '1-r1', segments: [seg('a', true)] },
        { rejection_id: 'r2', heading: '2-r2', segments: [seg('b', false)] },
      ],
    });
  });
});
