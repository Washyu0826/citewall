// Audit view e2e — Dave (auditor) sees rows + can verify the hash chain.
//
// Navigation is role-aware: auditors land on /audit; IT admins land on the
// case registry and reach the audit log from their nav rail; attorneys have
// no audit entry (the gateway 403s /v1/audit/* for them anyway).
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAuditRecent,
  mockAuditVerify,
  loginAsAlice,
} from './helpers/mock_backend.js';

async function loginAsDave(page) {
  await mockLogin(page, 'audit_dave');
  await mockQuota(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Dave/ }).click();
  // Auditor lands directly on /audit (role-aware landing).
  await page.waitForURL(/\/audit/, { timeout: 5000 });
}

test.describe('Audit flow', () => {
  test('Dave can view audit rows', async ({ page }) => {
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await loginAsDave(page);

    await expect(page.getByRole('heading', { name: /Audit Log/ })).toBeVisible();
    await expect(page.locator('th', { hasText: /User/ })).toBeVisible();
    await expect(page.locator('th', { hasText: /Endpoint/ })).toBeVisible();
    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
    await expect(page.locator('span', { hasText: /^CASE_REF$/ }).first()).toBeVisible();
  });

  test('non-auditor receives 403 and shows an error banner', async ({ page }) => {
    // Carol (it_admin / tenant_b) cannot read tenant_a audit logs.
    await mockLogin(page, 'carol');
    await mockQuota(page);
    await mockAuditRecent(page, [], {
      status: 403,
      body: { detail: 'forbidden: audit role required' },
    });
    await page.route('**/api/v1/audit/verify**', (route) => {
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'forbidden' }),
      });
    });
    await page.route('**/api/v1/admin/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cases: [], patterns: {} }) })
    );

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    // IT admins land on the case registry; the audit log is in their nav.
    await page.waitForURL(/\/admin\/cases/, { timeout: 5000 });
    await page.getByTestId('nav-audit').click();
    await page.waitForURL(/\/audit/);

    const alert = page.getByRole('alert').filter({ hasText: '您沒有此案件的存取權限' }).first();
    await expect(alert).toBeVisible({ timeout: 5000 });
  });

  test('verify chain button renders green banner', async ({ page }) => {
    await mockAuditRecent(page);
    await mockAuditVerify(page, [], 2);
    await loginAsDave(page);

    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
    await page.getByTestId('audit-verify-now').click();
    await expect(page.getByText(/全部驗證通過/)).toBeVisible({ timeout: 5000 });
  });

  test('verify chain reports broken rows', async ({ page }) => {
    await mockAuditRecent(page);
    await mockAuditVerify(page, ['AUD-0042', 'AUD-0044'], 50);
    await loginAsDave(page);

    await page.getByTestId('audit-verify-now').click();
    await expect(page.getByText(/發現 2 筆紀錄遭竄改/)).toBeVisible({ timeout: 5000 });
  });

  test('an attorney has no audit entry in the navigation', async ({ page }) => {
    await loginAsAlice(page, '/home');
    await expect(page.getByTestId('nav-rail')).toBeVisible();
    await expect(page.getByTestId('nav-audit')).toHaveCount(0);
    await expect(page.getByTestId('nav-cases')).toBeVisible();
  });
});
