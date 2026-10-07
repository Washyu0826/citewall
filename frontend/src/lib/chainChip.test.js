import { describe, expect, it } from 'vitest';
import { CHAIN_CHIP_TONE, auditStateFrom, chainChipView } from './chainChip.js';

describe('chainChipView', () => {
  it('never shows a green "verified" to roles that cannot verify', () => {
    const v = chainChipView({ status: 'idle' }, false);
    expect(v.labelKey).toBe('shell.audit_chip.neutral');
    expect(v.tone).toBe(CHAIN_CHIP_TONE.neutral);
  });

  it('shows "checking" (neutral) until the first verify result arrives', () => {
    const v = chainChipView({ status: 'idle' }, true);
    expect(v.labelKey).toBe('shell.audit_chip.checking');
    expect(v.tone).toBe(CHAIN_CHIP_TONE.neutral);
  });

  it('is green only after a successful verify', () => {
    expect(chainChipView({ status: 'ok' }, true)).toMatchObject({
      failed: false,
      labelKey: 'shell.audit_chip.ok',
      tone: CHAIN_CHIP_TONE.ok,
    });
  });

  it('a verify call that could not run is neither red nor green (review of B-53)', () => {
    expect(chainChipView({ status: 'unavailable' }, true)).toMatchObject({
      failed: false,
      labelKey: 'shell.audit_chip.unavailable',
      tone: CHAIN_CHIP_TONE.neutral,
    });
  });

  it('a failed chain is red for everyone', () => {
    for (const can of [true, false]) {
      expect(chainChipView({ status: 'fail' }, can)).toMatchObject({
        failed: true,
        labelKey: 'shell.audit_chip.fail',
        tone: CHAIN_CHIP_TONE.fail,
      });
    }
  });
});

describe('auditStateFrom (AppShell)', () => {
  const broken = { broken: ['AUD-1'], verified: 10 };
  const fine = { broken: [], verified: 10 };
  const err = new Error('429');

  it('a known broken chain stays red when a later poll fails (B-55)', () => {
    // TanStack keeps the last data on a refetch error.
    expect(auditStateFrom({ data: broken, error: err }, true)).toMatchObject({ status: 'fail', broken: 1 });
  });

  it('a failed call without a broken result is "unavailable", not red', () => {
    expect(auditStateFrom({ error: err }, true).status).toBe('unavailable');
    expect(auditStateFrom({ data: fine, error: err }, true).status).toBe('unavailable');
  });

  it('ok only on a clean result; idle before any result or without the role', () => {
    expect(auditStateFrom({ data: fine }, true)).toMatchObject({ status: 'ok', verified: 10 });
    expect(auditStateFrom({}, true).status).toBe('idle');
    expect(auditStateFrom({ data: broken }, false).status).toBe('idle');
  });
});
