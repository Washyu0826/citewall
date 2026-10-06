// Workspace state (research 09 FE-L1 / UX-5).
//
// The workspace's state lives above the routes: leaving the page keeps the
// result, the sentence decisions and a running analysis; a running analysis
// can be cancelled; throwing unsaved decisions or a running analysis away
// (re-analysing, switching case) asks first.
import { test, expect } from '@playwright/test';
import { defaultAnalysisResponse, gotoNav, loginAsAlice, mockAnalyze } from './helpers/mock_backend.js';

const analyzeButton = (page) => page.getByTestId('analyze-submit');
const main = (page) => page.locator('main').filter({ visible: true }).last();
const XL_ONLY = 'the sentence review needs the xl layout (as in signoff_export.spec.js)';

async function analyzed(page) {
  await loginAsAlice(page);
  await mockAnalyze(page);
  await analyzeButton(page).click();
  await expect(main(page).getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
}

async function acceptFirstSentence(page) {
  await main(page).getByTestId('line-accept').first().click();
  await expect(main(page).getByTestId('draft-line').first()).toHaveAttribute('data-status', 'accepted');
}

/** Hold /v1/oa/analyze until the returned function is called. */
async function holdAnalyze(page) {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await page.route('**/api/v1/oa/analyze', async (route) => {
    await gate;
    await route
      .fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(defaultAnalysisResponse()) })
      .catch(() => {}); // the page may have stopped waiting (aborted)
  });
  return release;
}

test.describe('Workspace state (FE-L1 / UX-5)', () => {
  test('sentence decisions survive going to another page and back', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, XL_ONLY);
    await analyzed(page);
    await acceptFirstSentence(page);

    await gotoNav(page, '/home');
    await gotoNav(page, '/analyze');

    await expect(main(page).getByText('答辯策略').first()).toBeVisible();
    await expect(main(page).getByTestId('draft-line').first()).toHaveAttribute('data-status', 'accepted');
  });

  test('an analysis keeps running while the attorney is on another page', async ({ page }) => {
    await loginAsAlice(page);
    const release = await holdAnalyze(page);
    await analyzeButton(page).click();
    await expect(page.getByTestId('analysis-cancel')).toBeVisible();

    await gotoNav(page, '/home');
    // The URL changes before React shows the (lazily loaded) page: release
    // only once Home is really on screen — until then the attorney is still
    // looking at the workspace, where no notice is needed.
    await expect(page.getByTestId('home-new-analysis')).toBeVisible();
    release();
    await expect(page.getByText(/的分析完成了/)).toBeVisible({ timeout: 10_000 });

    await gotoNav(page, '/analyze');
    await expect(main(page).getByText('答辯策略').first()).toBeVisible();
  });

  test('cancel stops waiting and brings the form back', async ({ page }) => {
    await loginAsAlice(page);
    await page.route('**/api/v1/oa/analyze', () => {}); // never answers
    await analyzeButton(page).click();
    await page.getByTestId('analysis-cancel').click();
    await expect(page.getByText('已停止等待分析結果。')).toBeVisible();
    await expect(analyzeButton(page)).toBeVisible();
  });

  test('re-analysing with sentence decisions asks first', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, XL_ONLY);
    await analyzed(page);
    await acceptFirstSentence(page);
    let posts = 0;
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/api/v1/oa/analyze')) posts += 1;
    });

    await page.getByRole('button', { name: '編輯輸入' }).click();
    await analyzeButton(page).click();
    await page.getByTestId('discard-keep').click();
    await page.waitForTimeout(500); // a request would have been sent by now
    expect(posts).toBe(0);

    await analyzeButton(page).click();
    await page.getByTestId('discard-confirm').click();
    await expect.poll(() => posts).toBe(1);
    await expect(main(page).getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
    // The new result starts with no decisions.
    await expect(main(page).getByTestId('draft-line').first()).toHaveAttribute('data-status', 'pending');
  });

  test('switching case with sentence decisions asks first, and the page stays usable', async ({
    page,
    viewport,
  }) => {
    test.skip(viewport && viewport.width < 1280, XL_ONLY);
    await analyzed(page);
    await acceptFirstSentence(page);

    await page.getByTestId('case-switcher').click();
    await page.getByRole('menuitem', { name: /CASE-2025-002/ }).click();
    await page.getByTestId('discard-keep').click();
    await expect(page.getByTestId('case-switcher')).toContainText('CASE-2025-001');
    await expect(main(page).getByTestId('draft-line').first()).toHaveAttribute('data-status', 'accepted');

    // Confirming switches and drops the old case's result.
    await page.getByTestId('case-switcher').click();
    await page.getByRole('menuitem', { name: /CASE-2025-002/ }).click();
    await page.getByTestId('discard-confirm').click();
    await expect(page.getByTestId('case-switcher')).toContainText('CASE-2025-002');
    await expect(page.getByText('答辯策略')).toHaveCount(0);
    // The dialogs opened from a dropdown item: the page must still take clicks.
    await gotoNav(page, '/home');
  });

  test('switching case from the dashboard asks too (one guard for every switch)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, XL_ONLY);
    await analyzed(page);
    await acceptFirstSentence(page);
    await gotoNav(page, '/home');

    await page.getByRole('button', { name: '開始分析' }).first().click(); // another case
    await page.getByTestId('discard-keep').click();
    await expect(page.getByTestId('case-switcher')).toContainText('CASE-2025-001');
  });
});
