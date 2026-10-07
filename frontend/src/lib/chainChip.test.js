import { describe, expect, it } from 'vitest';
import { CHAIN_CHIP_TONE, chainChipView } from './chainChip.js';

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
