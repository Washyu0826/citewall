// Audit view e2e — Dave (auditor) sees rows + can verify the hash chain.
//
// Navigation is role-aware: auditors land on /audit; IT admins land on the
// case registry and reach the audit log from their nav rail; attorneys have
// no audit entry (the gateway 403s /v1/audit/* for them anyway).
import { test, expect } from '@playwright/test';
import {
  EMPTY_REGISTRY,
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

    await expect(page.getByRole('heading', { name: '稽核紀錄' })).toBeVisible();
    await expect(page.locator('th', { hasText: '使用者' })).toBeVisible();
    await expect(page.locator('th', { hasText: '端點' })).toBeVisible();
    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
    await expect(page.locator('span', { hasText: /^CASE_REF$/ }).first()).toBeVisible();
  });

  test('IT admin audit calls carry no case id and are not refused', async ({ page }) => {
    // The audit API is role-gated (auditor / it_admin), not case-scoped. A
    // hard-coded demo X-Case-Id used to run the case ACL and 403 Carol, and
    // this suite had mocked that 403 as if it were intended (FAILURE_LOG B-11).
    const auditHeaders = [];
    page.on('request', (req) => {
      if (/\/api\/v1\/audit\//.test(req.url())) auditHeaders.push(req.headers());
    });
    await mockLogin(page, 'carol');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await page.route('**/api/v1/admin/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_REGISTRY) })
    );

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    await page.waitForURL(/\/admin\/cases/, { timeout: 5000 });
    await page.getByTestId('nav-audit').click();
    await page.waitForURL(/\/audit/);

    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(auditHeaders.length).toBeGreaterThan(0);
    for (const h of auditHeaders) expect(h['x-case-id']).toBeUndefined();
  });

  test('a 403 from the audit API shows an error banner', async ({ page }) => {
    // e.g. the role was revoked server-side after login.
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
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_REGISTRY) })
    );

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    // IT admins land on the case registry; the audit log is in their nav.
    await page.waitForURL(/\/admin\/cases/, { timeout: 5000 });
    await page.getByTestId('nav-audit').click();
    await page.waitForURL(/\/audit/);

    // Role-neutral wording: this 403 is a role gate, not a case ACL (V-F3).
    const alert = page.getByRole('alert').filter({ hasText: '您沒有權限執行這個操作' }).first();
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
    await expect(page.getByTestId('primary-nav')).toBeVisible();
    await expect(page.getByTestId('nav-audit')).toHaveCount(0);
    await expect(page.getByTestId('nav-cases')).toBeVisible();
  });
});
