// Pure helpers for the Q15/Q16 claim-element comparison table
// (components/analyze/ElementTable.jsx). Kept free of React for vitest.

export const ELEMENT_STATUSES = ['disclosed', 'partial', 'not_disclosed', 'no_evidence'];

const STATUS_TONE = {
  disclosed: 'rose', // bad for the applicant: the examiner's reading holds
  partial: 'amber',
  not_disclosed: 'emerald', // an argument the attorney can make
  no_evidence: 'slate',
};

/** Tables for one rejection, in claim order. Tolerates older gateways. */
export function tablesForRejection(result, rejectionId) {
  const all = Array.isArray(result?.element_tables) ? result.element_tables : [];
  return all
    .filter((t) => t && t.rejection_id === rejectionId)
    .sort((a, b) => (a.claim_no ?? 0) - (b.claim_no ?? 0));
}

/** Tone key for a status chip (unknown statuses render neutral). */
export function statusTone(status) {
  return STATUS_TONE[status] || 'slate';
}

/** i18n key for a status label. */
export function statusKey(status) {
  return ELEMENT_STATUSES.includes(status)
    ? `element_table.status.${status}`
    : 'element_table.status.no_evidence';
}

/** Counts per status, for the table header summary. */
export function statusCounts(table) {
  const out = { disclosed: 0, partial: 0, not_disclosed: 0, no_evidence: 0 };
  for (const e of table?.elements || []) {
    if (e && e.status in out) out[e.status] += 1;
  }
  return out;
}

/** "[GROUNDED_REF_n]" key the draft citation lookup uses for this evidence. */
export function evidenceRefKey(evidence) {
  const n = evidence?.ref_index;
  return Number.isInteger(n) && n > 0 ? `[GROUNDED_REF_${n}]` : null;
}

/** Whole-percent term coverage, or null when not a finite 0..1 number. */
export function coveragePct(score) {
  if (!Number.isFinite(score)) return null;
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}
