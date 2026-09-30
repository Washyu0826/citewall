// Login flow e2e — landing page renders, role cards work, and a 401 from
// the gateway surfaces an alert on screen. All tests are hermetic via
// page.route() mocks.
import { test, expect } from '@playwright/test';
import { EMPTY_REGISTRY, mockCases, mockLogin, mockQuota, DEMO_USERS } from './helpers/mock_backend.js';

test.describe('Login flow', () => {
  test('landing renders with hero + role cards', async ({ page }) => {
    await page.goto('/');

    // Hero brand + tagline are visible.
    await expect(page.locator('text=CiteWall').first()).toBeVisible();

    // All four demo identity cards render. The button text is just the user
    // initial + name + role label, so a name-matcher is the most stable.
    for (const name of ['Alice', 'Bob', 'Carol', 'Dave']) {
      await expect(page.getByRole('button', { name: new RegExp(name) })).toBeVisible();
    }
  });

  test('an attorney lands on the dashboard', async ({ page }) => {
    await mockLogin(page, 'alice');
    await mockQuota(page);
    await mockCases(page);

    await page.goto('/');
    await page.getByRole('button', { name: /Alice/ }).click();

    await page.waitForURL(/\/home/, { timeout: 5000 });
    await expect(page.locator('header').getByText('CiteWall')).toBeVisible();
    // Dashboard: the case with a deadline is listed.
    await expect(page.getByTestId('home-deadlines')).toContainText('CASE-2025-001');
  });

  test('Carol logs in as IT Admin with tenant_b', async ({ page, viewport }) => {
    // Name + role sit on the account-menu trigger, shown from `lg` (1024px);
    // the tenant is in the trust band (from `sm`).
    test.skip(viewport && viewport.width < 1024, 'account name/role label is lg: only');

    await mockLogin(page, 'carol');
    await mockQuota(page);
    await page.route('**/api/v1/admin/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_REGISTRY) })
    );
    // AppShell calls auditVerify on mount for it_admin / auditor — mock so it
    // doesn't error out (would otherwise show a fail chip but not crash).
    await page.route('**/api/v1/audit/verify**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ broken: [], verified: 0 }),
      })
    );

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    // IT admins land on the case registry.
    await page.waitForURL(/\/admin\/cases/, { timeout: 5000 });

    const header = page.locator('header');
    await expect(header.getByText(DEMO_USERS.carol.display_name)).toBeVisible();
    // Role label: t('shell.role_badge.it_admin') = 'IT 管理'.
    await expect(header.getByText(/IT 管理/)).toBeVisible();
    await expect(page.getByTestId('trust-band')).toContainText('tenant_b');
  });

  test('error message appears when backend returns 401', async ({ page }) => {
    await mockLogin(page, 'alice', {
      status: 401,
      body: { detail: 'Unauthorized — demo secret mismatch' },
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Alice/ }).click();

    // Login.jsx renders the error as <div role="alert"> in the login card.
    const alert = page.getByRole('alert').first();
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Unauthorized|demo secret|401/i);

    // URL must NOT have changed.
    await expect(page).toHaveURL(/\/(login)?$|\/$/);
  });
});
