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
 * @param {{status: 'idle'|'ok'|'fail'|'unavailable'}} state
 * @param {boolean} canCallAudit
 * @returns {{failed: boolean, tone: string, labelKey: string}}
 */
export function chainChipView(state, canCallAudit) {
  const failed = state?.status === 'fail';
  if (failed) return { failed, tone: CHAIN_CHIP_TONE.fail, labelKey: 'shell.audit_chip.fail' };
  // The verify call could not run: say so — red would claim tampering that
  // nobody checked, green would claim a check that did not happen.
  if (state?.status === 'unavailable') {
    return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.unavailable' };
  }
  if (!canCallAudit) {
    return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.neutral' };
  }
  if (state?.status === 'ok') {
    return { failed, tone: CHAIN_CHIP_TONE.ok, labelKey: 'shell.audit_chip.ok' };
  }
  return { failed, tone: CHAIN_CHIP_TONE.neutral, labelKey: 'shell.audit_chip.checking' };
}
