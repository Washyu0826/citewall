import { describe, expect, it } from 'vitest';

import { errorDetailText } from '../api/client.js';
import { asText, classifyError } from './errorInfo.js';

const t = (key) => key;

describe('errorDetailText', () => {
  it('passes a string detail through', () => {
    expect(errorDetailText({ detail: 'case_id mismatch' }, 'Bad Request')).toBe('case_id mismatch');
  });
  it('joins the msg fields of a FastAPI validation (422) detail array', () => {
    const body = {
      detail: [
        { loc: ['body', 'target_patent_no'], msg: 'String should have at most 64 characters', type: 'x' },
        { loc: ['body', 'oa_text'], msg: 'Field required', type: 'missing' },
      ],
    };
    expect(errorDetailText(body, 'Unprocessable Entity')).toBe(
      'String should have at most 64 characters; Field required'
    );
  });
  it('falls back to the status text for anything else', () => {
    expect(errorDetailText(null, 'Bad Gateway')).toBe('Bad Gateway');
    expect(errorDetailText({ raw: '<html>' }, 'Bad Gateway')).toBe('Bad Gateway');
    expect(errorDetailText({ detail: { nested: true } }, 'X')).toBe('X');
    expect(errorDetailText({ detail: [{}] }, 'X')).toBe('X');
  });
});

describe('classifyError', () => {
  it('never returns a non-string message, even for a structured body (B-9)', () => {
    const err = { status: 422, message: [{ msg: 'bad' }], body: { detail: [{ msg: 'bad' }] } };
    expect(typeof classifyError(err, t).message).toBe('string');
  });
  it('treats a timeout (408) and a gateway timeout (504) as retryable', () => {
    expect(classifyError({ status: 408 }, t)).toMatchObject({ message: 'errors.timeout', retryable: true });
    expect(classifyError({ status: 504 }, t)).toMatchObject({ message: 'errors.timeout', retryable: true });
  });
  it('maps quota exhaustion (402) to a sentence, not the raw backend text', () => {
    expect(classifyError({ status: 402, message: 'daily token quota exceeded: used=1' }, t)).toMatchObject({
      message: 'errors.quota_exceeded',
      retryable: false,
    });
  });
  it('keeps the existing classes', () => {
    expect(classifyError({ status: 401 }, t).requiresLogin).toBe(true);
    expect(classifyError({ status: 429 }, t).countdown).toBe(true);
    expect(classifyError({ status: 0 }, t).message).toBe('errors.network');
    expect(classifyError({ status: 418, message: 'teapot' }, t).message).toBe('teapot');
  });
});

describe('asText', () => {
  it('drops anything that is not a string', () => {
    expect(asText('a')).toBe('a');
    expect(asText([{ msg: 'x' }])).toBe('');
    expect(asText(undefined)).toBe('');
  });
});
