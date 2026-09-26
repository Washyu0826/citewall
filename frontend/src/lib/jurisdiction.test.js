import { describe, expect, it } from 'vitest';
import { jurisdictionForPatent } from './jurisdiction.js';

describe('jurisdictionForPatent (mirror of the gateway)', () => {
  it.each([
    ['US17123456', 'US'],
    ['TWI123456', 'TW'],
    ['us-9999999', 'US'],
    ['EP3123456', 'EP'],
    ['WO2020123456', 'TW'],
    ['1234567', 'TW'],
    ['', 'TW'],
    [null, 'TW'],
  ])('%s -> %s', (no, code) => {
    expect(jurisdictionForPatent(no)).toBe(code);
  });
});
