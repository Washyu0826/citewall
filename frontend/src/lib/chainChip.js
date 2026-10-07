// Trust-band audit-chain chip (AppShell ChainChip) — label/tone decision.
//
// Only claim "verified" (green) once a verify call actually succeeded. Roles
// that cannot call verify get a neutral label, never a green trust signal;
// audit-capable roles show "checking" until the first result arrives.

export const CHAIN_CHIP_TONE = {
  fail: 'bg-rose-600/90 hover:bg-rose-600 text-white ring-rose-300/40',
  ok: 'bg-emerald-600/90 hover:bg-emerald-600 text-white ring-emerald-300/40',
  neutral: 'bg-white/10 hover:bg-white/15 text-navy-50 ring-white/15',
};

/**
 * The chip's state from the verify query (AppShell).
 *
 * Order matters (FAILURE_LOG B-55): a chain known to be BROKEN stays red even
 * when a later poll fails — TanStack keeps the last data on a refetch error,
 * and anyone on the demo can exhaust the shared auditor's rate limit. Only
 * then does a failed call mean "couldn't verify" (neither red nor green).
 *
 * @param {{data?: {broken?: unknown[], verified?: number}, error?: Error}} query
 * @param {boolean} canCallAudit
 */
export function auditStateFrom(query, canCallAudit) {
  if (!canCallAudit) return { status: 'idle', verified: 0, broken: 0, error: null };
  const data = query?.data;
  const brokenCount = data && Array.isArray(data.broken) ? data.broken.length : 0;
  if (brokenCount > 0) {
    return { status: 'fail', verified: data.verified ?? 0, broken: brokenCount, error: null };
  }
  if (query?.error) {
    return { status: 'unavailable', verified: 0, broken: 0, error: query.error.message || 'verify failed' };
  }
  if (!data) return { status: 'idle', verified: 0, broken: 0, error: null };
  return { status: 'ok', verified: data.verified ?? 0, broken: 0, error: null };
}

/**
 * @param {{status: 'idle'|'ok'|'fail'|'unavailable'}} state
 * @param {boolean} canCallAudit
 * @returns {{failed: boolean, tone: string, labelKey: string, icon: 'alert'|'question'|'check'|'plain'}}
 *   icon: a check mark only for a chain that verified — not while checking.
 */
export function chainChipView(state, canCallAudit) {
  const failed = state?.status === 'fail';
  if (failed) return { failed, tone: CHAIN_CHIP_TONE.fail, labelKey: 'shell.audit_chip.fail', icon: 'alert' };
  // The verify call could not run: say so — red would claim tampering that
  // nobody checked, green would claim a check that did not happen.
  if (state?.status === 'unavailable') {
    return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.unavailable', icon: 'question' };
  }
  if (!canCallAudit) {
    return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.neutral', icon: 'plain' };
  }
  if (state?.status === 'ok') {
    return { failed, tone: CHAIN_CHIP_TONE.ok, labelKey: 'shell.audit_chip.ok', icon: 'check' };
  }
  return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.checking', icon: 'plain' };
}
