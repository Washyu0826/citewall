/**
 * Optional deadline inputs on the analyze request (Q16/Q17/Q19) and the
 * helpers the result bar uses to explain how the deadline was computed.
 *
 * Field names mirror backend/shared/models.py AnalysisRequest / DeadlineInfo.
 */

// Tri-state applicant domicile select → AnalysisRequest.applicant_domestic.
export const DOMICILE_OPTIONS = ['unknown', 'domestic', 'foreign'];

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True for a real calendar date in 'YYYY-MM-DD' form (rejects 2025-02-30). */
export function isIsoDate(value) {
  const m = ISO_DATE.exec(value || '');
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}

/**
 * Build the optional request fields. Only fields the user actually set are
 * included, so an untouched form sends the same body (and hits the same
 * cache key) as before. Invalid values are dropped rather than sent — the
 * backend would 422 them.
 */
export function buildDeadlineRequestFields({ domicile, oaSequence, serviceDate } = {}) {
  const out = {};
  if (domicile === 'domestic') out.applicant_domestic = true;
  else if (domicile === 'foreign') out.applicant_domestic = false;

  const seq = typeof oaSequence === 'string' ? oaSequence.trim() : oaSequence;
  if (seq !== '' && seq != null) {
    const n = Number(seq);
    if (Number.isInteger(n) && n >= 1 && n <= 50) out.oa_sequence = n;
  }

  if (isIsoDate(serviceDate)) out.service_date = serviceDate;
  return out;
}

// DeadlineInfo.start_date_basis values the backend emits.
const START_BASES = new Set([
  'mailing_date',
  'service_date',
  'presumed_service',
  'mailing_date_fallback',
]);

/** i18n key for a start_date_basis value, or null when absent/unknown. */
export function startBasisKey(basis) {
  return START_BASES.has(basis) ? `deadline_detail.basis.${basis}` : null;
}

/**
 * Show the "rules not reviewed by a patent attorney" note unless the backend
 * explicitly says the rules WERE reviewed — an older payload without the
 * field keeps the note (Q21).
 */
export function showNotReviewedNote(deadline) {
  return deadline?.rules_reviewed !== true;
}
