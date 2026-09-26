// Q36 — confidence as an ordinal pip glyph, not a number.
//
// docs/AI_TRANSPARENCY_UX.md §2.6 / §3: a bare "72%" primes acceptance and
// offers no next step (failure mode F4). We render 3 dots instead:
//
//   ● ● ●  score ≥ 0.80   high
//   ● ● ○  0.60 – 0.80    medium
//   ● ○ ○  0.40 – 0.60    low
//   ○ ○ ○  < 0.40         very low (should not have shipped — F5)
//
// The exact value is still available to assistive tech / on hover (aria-label
// + title), so nothing is hidden — it just isn't the headline.
// These are the ONLY thresholds; change them here, not at call sites.

export const PIP_THRESHOLDS = [0.4, 0.6, 0.8];
export const PIP_MAX = PIP_THRESHOLDS.length;
const BANDS = ['very_low', 'low', 'medium', 'high'];

/** @returns {{filled: 0|1|2|3, band: string, pct: number} | null} */
export function confidencePips(score) {
  const n = Number(score);
  if (score == null || !Number.isFinite(n)) return null;
  const clamped = Math.min(1, Math.max(0, n));
  const filled = PIP_THRESHOLDS.filter((th) => clamped >= th).length;
  return { filled, band: BANDS[filled], pct: Math.round(clamped * 100) };
}
