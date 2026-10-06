// Visual regression baselines for the redesigned SPA (2026-09-30).
//
// Screenshots of the key states are compared against committed baselines in
// tests/e2e/__screenshots__/. Seed or refresh them with `--update-snapshots`.
// The 5% threshold (playwright.config.js) absorbs Linux-vs-Windows antialias.
import { test, expect } from '@playwright/test';
import {
  loginAsAlice,
  mockAnalyze,
  mockAuditRecent,
  mockAuditVerify,
  mockLogin,
  mockQuota,
  mockStackProbes,
} from './helpers/mock_backend.js';

const shot = { fullPage: false, animations: 'disabled', caret: 'hide' };

// Pin dates that render relative to "today" so baselines don't drift daily.
async function freezeClock(page) {
  await page.clock.setFixedTime(new Date('2026-09-30T10:00:00+08:00'));
}

async function waitForStackSettled(page) {
  for (const id of ['gateway', 'ai-engine', 'digirunner', 'dify']) {
    await expect(page.getByTestId(`stack-status-${id}`)).not.toHaveAttribute('data-status', 'checking');
  }
}

async function analyzeResult(page) {
  await mockAnalyze(page);
  await page.getByTestId('analyze-submit').click();
  await expect(page.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
}

test.describe('Visual regression', () => {
  test.beforeEach(async ({ page }) => {
    await mockStackProbes(page);
    await freezeClock(page);
  });

  test('landing', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=Patent OA Assistant').first()).toBeVisible();
    await expect(page).toHaveScreenshot('landing.png', shot);
  });

  test('home dashboard', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await loginAsAlice(page, '/home');
    await expect(page.getByTestId('home-deadlines')).toBeVisible();
    await expect(page).toHaveScreenshot('home.png', shot);
  });

  test('case list', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await loginAsAlice(page, '/cases');
    await expect(page.getByTestId('cases-table')).toBeVisible();
    await expect(page).toHaveScreenshot('cases.png', shot);
  });

  test('workspace — setup', async ({ page }) => {
    await loginAsAlice(page);
    await expect(page.getByText('1,500 / 100,000')).toBeVisible();
    await expect(page).toHaveScreenshot('workspace_setup.png', shot);
  });

  test('workspace — result', async ({ page }) => {
    await loginAsAlice(page);
    await analyzeResult(page);
    await expect(page).toHaveScreenshot('workspace_result.png', shot);
  });

  test('workspace — 500 error banner', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await loginAsAlice(page);
    await mockAnalyze(page, { status: 500, body: { detail: 'engine timeout' } });
    await page.getByTestId('analyze-submit').click();
    const alert = page.getByRole('alert').filter({ hasText: '伺服器忙線中' }).first();
    await expect(alert).toBeVisible({ timeout: 5000 });
    await expect(alert).toHaveScreenshot('error_banner.png', { animations: 'disabled', caret: 'hide' });
  });
});

test.describe('Visual regression — dark mode', () => {
  test.skip(({ viewport }) => viewport && viewport.width < 1280, 'desktop snapshots');

  test.beforeEach(async ({ page }) => {
    await mockStackProbes(page);
    await freezeClock(page);
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem('theme', 'dark');
      } catch {
        /* private mode — non-fatal */
      }
    });
  });

  test('workspace — setup (dark)', async ({ page }) => {
    await loginAsAlice(page);
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await expect(page.getByText('1,500 / 100,000')).toBeVisible();
    await expect(page).toHaveScreenshot('workspace_setup_dark.png', shot);
  });

  test('workspace — result (dark)', async ({ page }) => {
    await loginAsAlice(page);
    await analyzeResult(page);
    await expect(page).toHaveScreenshot('workspace_result_dark.png', shot);
  });

  test('home dashboard (dark)', async ({ page }) => {
    await loginAsAlice(page, '/home');
    await expect(page.getByTestId('home-deadlines')).toBeVisible();
    await expect(page).toHaveScreenshot('home_dark.png', shot);
  });

  test('audit table (dark)', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/audit/);
    await expect(page.getByRole('heading', { name: '稽核紀錄' })).toBeVisible();
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('audit_table_dark.png', shot);
  });
});
