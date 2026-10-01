// Case list → workspace, and one current case everywhere (FAILURE_LOG B-6).
//
// Desktop renders the list as a table, phones as cards (one variant only, so
// rows are not duplicated). Either way, opening a case must select it in the
// workspace and the trust band — the case id never enters the URL.
import { test, expect } from '@playwright/test';
import { loginAsAlice } from './helpers/mock_backend.js';

test.describe('Case list', () => {
  test('opening a case selects it in the workspace and the trust band', async ({ page, viewport }) => {
    await loginAsAlice(page, '/cases');
    const desktop = !viewport || viewport.width >= 768;
    const list = page.getByTestId(desktop ? 'cases-table' : 'cases-list');
    await expect(list).toBeVisible();

    await list
      .locator(desktop ? 'tr' : 'li')
      .filter({ hasText: 'CASE-2025-003-CONF' })
      .getByRole('button', { name: /開啟分析/ })
      .click();

    await page.waitForURL(/\/analyze$/);
    expect(page.url()).not.toContain('CASE-');
    await expect(page.locator('#analyze-case-id')).toHaveValue('CASE-2025-003-CONF');
    await expect(page.getByTestId('trust-routing')).toContainText('機密');
    if (desktop) await expect(page.getByTestId('case-switcher')).toContainText('CASE-2025-003-CONF');
  });

  test('the workspace default case is the current case in the top bar', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 768, 'the case switcher is shown from md');
    // Straight to the workspace without picking a case: the switcher must not
    // say "no case selected" while the workspace analyses CASE-2025-001.
    await loginAsAlice(page);
    await expect(page.locator('#analyze-case-id')).toHaveValue('CASE-2025-001');
    await expect(page.getByTestId('case-switcher')).toContainText('CASE-2025-001');
  });
});
