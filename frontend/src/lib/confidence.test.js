import { describe, expect, it } from 'vitest';
import { confidencePips } from './confidence.js';

describe('confidencePips', () => {
  it.each([
    [0.95, 3, 'high'],
    [0.8, 3, 'high'],
    [0.79, 2, 'medium'],
    [0.6, 2, 'medium'],
    [0.5, 1, 'low'],
    [0.4, 1, 'low'],
    [0.39, 0, 'very_low'],
    [0, 0, 'very_low'],
  ])('%f -> %i pips (%s)', (score, filled, band) => {
    expect(confidencePips(score)).toMatchObject({ filled, band });
  });

  it('clamps and keeps the exact percentage for assistive tech', () => {
    expect(confidencePips(1.4)).toMatchObject({ filled: 3, pct: 100 });
    expect(confidencePips(0.724).pct).toBe(72);
  });

  it('returns null when there is no score', () => {
    expect(confidencePips(null)).toBeNull();
    expect(confidencePips(undefined)).toBeNull();
    expect(confidencePips('n/a')).toBeNull();
  });
});
