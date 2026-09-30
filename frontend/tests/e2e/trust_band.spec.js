// Day 9C — CHUNK-8 trust band.
//
// PRODUCT_STRATEGY §10 + CLAUDE.md §4 invariants #3 / #6 / #7 demand that
// three things be VISIBLE on every authenticated page:
//
//   1. Redaction status (Q10 / invariant #3)
//   2. Mapping-table residency (CLAUDE.md §9 — never leaves on-prem)
//   3. Routing decision (Q15 / invariant #7 — confidential → local LLM)
//
// These assertions are the regression net for the trust band: if a future
// PR drops the band from the shell, or if the case-id → confidential
// detection breaks, this test must catch it.
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAnalyze,
  mockRedactionPreview,
  mockAuditRecent,
  mockAuditVerify,
  defaultAnalysisResponse,
  loginAsAlice,
} from './helpers/mock_backend.js';

const TRUST_CHIPS = ['trust-redaction', 'trust-mapping', 'trust-routing'];

test.describe('Trust band (Day 9C CHUNK-8)', () => {
  test('theme toggle flips the document into dark mode and back', async ({ page, viewport }) => {
    // The toggle lives in the AppShell top bar and is sm:+ only.
    test.skip(viewport && viewport.width < 640, 'theme toggle is sm: only');
    await loginAsAlice(page);

    const html = page.locator('html');
    await expect(html).not.toHaveClass(/\bdark\b/);

    // aria-label is localized (zh-TW default) — use the stable testid.
    await page.getByTestId('theme-toggle').click();
    await expect(html).toHaveClass(/\bdark\b/);

    // Toggling back returns to light.
    await page.getByTestId('theme-toggle').click();
    await expect(html).not.toHaveClass(/\bdark\b/);
  });

  test('three trust chips render on Analyze immediately after login', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    // Band lives in the shell — must be present on the analyze landing.
    const band = page.getByTestId('trust-band');
    await expect(band).toBeVisible();
    for (const id of TRUST_CHIPS) {
      await expect(band.getByTestId(id)).toBeVisible();
    }
  });

  test('three trust chips also render on the Audit route', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    // Auditor lands directly on /audit (role-aware landing).
    await page.waitForURL(/\/audit/);

    const band = page.getByTestId('trust-band');
    await expect(band).toBeVisible();
    for (const id of TRUST_CHIPS) {
      await expect(band.getByTestId(id)).toBeVisible();
    }
  });

  test('routing chip follows the SERVER security level of the chosen case', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    await mockRedactionPreview(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        redaction_summary: { masked_entity_count: 7, rules_triggered: ['EMAIL', 'PHONE'] },
      })
    );

    // A public case routes normally…
    await expect(page.getByTestId('trust-routing')).toContainText('一般案件');
    // …a case the registry marks confidential flips to on-prem routing. The
    // level comes from GET /v1/cases, never from how the case id is spelled.
    await page.locator('#analyze-case-id').selectOption('CASE-2025-003-CONF');
    await expect(page.getByTestId('trust-routing')).toContainText(/本地處理|機密案件/);
  });

  test('with no case selected the routing chip does not claim a route', async ({ page }) => {
    await loginAsAlice(page, '/home');
    await expect(page.getByTestId('trust-routing')).toContainText('尚未選擇案件');
  });

  test('chain-verify chip is present in the top bar', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    // Attorney role doesn't poll, but the chip is rendered as the "Chain
    // verified" neutral chip variant. testid is stable across variants.
    await expect(page.getByTestId('trust-chain-chip')).toBeVisible();
  });
});
