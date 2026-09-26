// 2026-09 UX pass: emailed magic-link consume-on-load (Q23), deadline caveats
// (Q18/Q21), ordinal confidence pips (Q36), logout revocation.
import { test, expect } from '@playwright/test';
import {
  DEMO_USERS,
  defaultAnalysisResponse,
  loginAsAlice,
  mockAnalyze,
  mockQuota,
} from './helpers/mock_backend.js';

test.describe('Magic link (emailed, Q23)', () => {
  test('landing on #token=… consumes it once, logs in and clears the hash', async ({ page }) => {
    const consumed = [];
    await page.route('**/api/v1/auth/magic/consume', (route) => {
      consumed.push(route.request().postDataJSON());
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(DEMO_USERS.alice),
      });
    });
    await mockQuota(page);

    await page.goto('/#token=emailed-token-123');
    await page.waitForURL(/\/analyze/, { timeout: 5000 });

    expect(consumed).toEqual([{ token: 'emailed-token-123' }]); // single-use: exactly once
    expect(new URL(page.url()).hash).toBe(''); // token never left in the address bar
  });

  test('a failed consume shows the error on the login page', async ({ page }) => {
    await page.route('**/api/v1/auth/magic/consume', (route) =>
      route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"x"}' })
    );
    await page.goto('/#token=stale');
    await expect(page.getByRole('alert')).toBeVisible();
    expect(new URL(page.url()).hash).toBe('');
  });

  test('no token in the response = "check your inbox", no demo token box', async ({ page }) => {
    await page.route('**/api/v1/auth/magic/request', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'ok', magic_token: null }),
      })
    );
    await page.goto('/');
    await page.getByRole('button', { name: /寄送登入連結/ }).click();
    await page.getByPlaceholder(/輸入帳號/).fill('alice');
    await page.getByRole('button', { name: '寄送連結', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('請查看信箱');
    await expect(page.getByTestId('magic-token')).toHaveCount(0);
  });
});

test.describe('Deadline caveats + confidence pips', () => {
  test('not-reviewed notice always shows; TW hint only for TW cases', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    await mockAnalyze(page);

    await page.locator('#analyze-target-patent').fill('TWI812345');
    await page.getByRole('button', { name: /^分析 OA/ }).click();

    await expect(page.getByTestId('deadline-notice')).toContainText('未經專利師覆核');
    await expect(page.getByTestId('deadline-tw-foreign-hint')).toBeVisible();

    // Confidence is ordinal (pips), exact % only on the accessible name.
    const pips = page.getByTestId('confidence-pips').first();
    await expect(pips).toBeVisible();
    await expect(pips).toHaveAttribute('aria-label', /\d+%/);
    await expect(page.getByText(/信心 \d+%/)).toHaveCount(0);
  });

  test('US case: no TW foreign-applicant hint', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    await mockAnalyze(page, defaultAnalysisResponse());
    await page.getByRole('button', { name: /^分析 OA/ }).click();
    await expect(page.getByTestId('deadline-notice')).toBeVisible();
    await expect(page.getByTestId('deadline-tw-foreign-hint')).toHaveCount(0);
  });
});

test.describe('Logout', () => {
  test('logout calls /v1/auth/logout to revoke the session token', async ({ page }) => {
    let revokedWith = null;
    await page.route('**/api/v1/auth/logout', (route) => {
      revokedWith = route.request().headers()['authorization'];
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"revoked":true}' });
    });
    await loginAsAlice(page);
    await page.getByRole('button', { name: /登出|Logout|Sign out/i }).first().click();
    await expect(page.getByRole('button', { name: /Alice/ })).toBeVisible();
    await expect.poll(() => revokedWith).toBe(`Bearer ${DEMO_USERS.alice.token}`);
  });
});
