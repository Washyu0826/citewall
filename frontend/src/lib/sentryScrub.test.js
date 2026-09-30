import { describe, expect, it } from 'vitest';

import { SCRUBBED, scrubSentryEvent } from './sentryScrub.js';

const OA_TEXT = '申請人昕澄科技股份有限公司 請求項9「該第一電動車」缺先行詞 alice@example.com';

function rawEvent() {
  return {
    level: 'error',
    transaction: '/analyze',
    request: {
      method: 'POST',
      url: 'http://localhost:5173/analyze?case_id=CASE-1',
      data: { oa_text: OA_TEXT },
      query_string: 'case_id=CASE-1',
      headers: { 'X-Case-Id': 'CASE-1' },
    },
    exception: {
      values: [
        {
          type: 'TypeError',
          value: `cannot read ${OA_TEXT}`,
          stacktrace: {
            frames: [{ filename: 'DraftEditor.jsx', function: 'render', lineno: 42, vars: { t: OA_TEXT } }],
          },
        },
      ],
    },
    message: OA_TEXT,
    breadcrumbs: [
      { category: 'console', level: 'error', message: OA_TEXT, data: { arguments: [OA_TEXT] } },
      { category: 'fetch', type: 'http', data: { url: '/api/v1/oa/analyze', method: 'POST' } },
    ],
    spans: [{ op: 'http.client', description: 'POST /api/v1/oa/analyze', data: { body: OA_TEXT } }],
    extra: { payload: OA_TEXT },
    user: { id: 'alice', email: 'alice@example.com' },
    tags: { env: 'test' },
  };
}

describe('scrubSentryEvent', () => {
  it('removes every copy of OA text and case ids', () => {
    const dumped = JSON.stringify(scrubSentryEvent(rawEvent()));
    expect(dumped).not.toContain('昕澄');
    expect(dumped).not.toContain('該第一電動車');
    expect(dumped).not.toContain('alice@example.com');
    expect(dumped).not.toContain('CASE-1');
  });

  it('keeps what is needed to debug', () => {
    const out = scrubSentryEvent(rawEvent());
    const exc = out.exception.values[0];
    expect(exc.type).toBe('TypeError');
    expect(exc.value).toBe(SCRUBBED);
    expect(exc.stacktrace.frames[0]).toEqual({ filename: 'DraftEditor.jsx', function: 'render', lineno: 42 });
    expect(out.request).toEqual({ method: 'POST', url: 'http://localhost:5173/analyze' });
    expect(out.breadcrumbs[0]).toEqual({ category: 'console', level: 'error' });
    expect(out.spans[0]).toEqual({ op: 'http.client', description: 'POST /api/v1/oa/analyze' });
    expect(out.tags).toEqual({ env: 'test' });
  });

  it('tolerates minimal events', () => {
    expect(scrubSentryEvent({})).toEqual({});
    expect(scrubSentryEvent(null)).toBe(null);
  });
});
