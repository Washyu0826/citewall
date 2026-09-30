// Q27 — case-registry admin page (it_admin only).
import { test, expect } from '@playwright/test';
import { mockCases, mockLogin, mockQuota, mockAuditVerify, mockStackProbes } from './helpers/mock_backend.js';

const LIST = {
  cases: [
    {
      case_id: 'CASE-2025-001',
      level: 'public',
      active: true,
      note: 'demo',
      updated_by: null,
      updated_at: null,
    },
  ],
  patterns: [{ pattern: 'CASE-DEMO-*', level: 'public' }],
  levels: ['confidential', 'public', 'top_secret'],
};

async function loginAs(page, user) {
  await mockLogin(page, user);
  await mockQuota(page);
  await mockAuditVerify(page);
  await mockStackProbes(page);
  await mockCases(page);
  await page.goto('/');
  await page
    .getByRole('button', { name: new RegExp(user === 'carol' ? 'Carol' : 'Alice') })
    .click();
  // Role-aware landing: IT admin → case registry, attorney → dashboard.
  await page.waitForURL(user === 'carol' ? /\/admin\/cases/ : /\/home/, { timeout: 5000 });
}

test.describe('case registry admin', () => {
  test.beforeEach(({ viewport }) => {
    test.skip(viewport && viewport.width < 1024, 'nav rail link is desktop-only');
  });

  test('it_admin can list, add, change level and deactivate', async ({ page }) => {
    const calls = [];
    await page.route('**/api/v1/admin/cases**', async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const body = req.postData() ? JSON.parse(req.postData()) : null;
      calls.push({ method: req.method(), path: url.pathname, body });
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(LIST),
        });
      }
      return route.fulfill({
        status: req.method() === 'POST' && url.pathname.endsWith('/cases') ? 201 : 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...body,
          level: body?.security_level ?? 'public',
          active: !url.pathname.endsWith('/deactivate'),
        }),
      });
    });

    await loginAs(page, 'carol');
    await page.getByRole('button', { name: /^(案件登錄|Case registry)$/ }).click();
    await expect(page).toHaveURL(/\/admin\/cases/);
    await expect(page.getByTestId('admin-row-CASE-2025-001')).toBeVisible();
    await expect(page.getByText('CASE-DEMO-*')).toBeVisible();

    await page.getByTestId('admin-new-case-id').fill('CASE-2026-042');
    await page.getByTestId('admin-new-level').selectOption('confidential');
    await page.getByTestId('admin-add').click();
    await expect
      .poll(() => calls.find((c) => c.method === 'POST' && c.path.endsWith('/cases'))?.body)
      .toEqual({
        case_id: 'CASE-2026-042',
        security_level: 'confidential',
        note: '',
      });

    await page.getByLabel(/CASE-2025-001/).selectOption('confidential');
    await expect
      .poll(() => calls.find((c) => c.method === 'PUT')?.body?.security_level)
      .toBe('confidential');

    page.once('dialog', (d) => d.accept());
    await page
      .getByTestId('admin-row-CASE-2025-001')
      .getByRole('button', { name: /停用|Deactivate/ })
      .click();
    await expect
      .poll(() => calls.find((c) => c.path.endsWith('/deactivate'))?.body)
      .toEqual({ case_id: 'CASE-2025-001' });

    // case ids never travel in the URL
    for (const c of calls) expect(c.path).not.toContain('CASE-');
  });

  test('non-admin sees no admin nav and is redirected away', async ({ page }) => {
    await loginAs(page, 'alice');
    await expect(page.getByRole('button', { name: /^(案件登錄|Case registry)$/ })).toHaveCount(0);
    await page.evaluate(() => window.history.pushState({}, '', '/admin/cases'));
    await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate')));
    await expect(page).toHaveURL(/\/home/);
  });
});
