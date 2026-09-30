// Vite dev-server warm-up — runs once before both browser projects
// (see `dependencies` in playwright.config.js).
//
// Local e2e runs hit the DEV server, which transforms ~1900 modules on the
// first page load. On Windows that cold transform cannot serve 5-10 parallel
// browser contexts — page.goto('/') times out across the whole suite. This
// single serial pass loads every major surface (login → analyze → audit) so
// the module graph is fully transformed and cached before the real tests
// fan out.
import { test } from '@playwright/test';
import { gotoNav, loginAsAlice, mockStackProbes } from './helpers/mock_backend.js';

test('warm the vite module graph', async ({ page }) => {
  test.setTimeout(180_000);
  page.setDefaultNavigationTimeout(150_000);

  await mockStackProbes(page);
  // login → /home (dashboard) → /analyze (the heavy workspace modules)
  await loginAsAlice(page);
  await page.getByTestId('workspace-stepper').waitFor({ timeout: 30_000 });
  // The case list too.
  await gotoNav(page, '/cases');
  await page.getByTestId('cases-table').waitFor({ timeout: 30_000 });
});
