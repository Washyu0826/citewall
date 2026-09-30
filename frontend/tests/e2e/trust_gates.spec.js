// UX_REVIEW T2 + T3 — the trust gates the banners promise must actually bind.
//
//   T2: a DEGRADED (fallback-engine) result shows a banner saying it is not
//       legal analysis — so the sign-off export gate must refuse it outright.
//   T3: a sentence still carrying [CITATION_REMOVED] (the verifier stripped a
//       fabricated citation from it) cannot be accepted as-is: the accept
//       affordance is blocked; rewrite or exclusion are the only ways forward.
//
// Desktop-only: the three-pane DraftEditor requires the xl breakpoint.
import { test, expect } from '@playwright/test';
import {
  loginAsAlice,
  mockAnalyze,
  defaultAnalysisResponse,
} from './helpers/mock_backend.js';

test.describe('Trust gates (T2 degraded / T3 stripped citation) — desktop', () => {
  test.skip(
    ({ viewport }) => viewport && viewport.width < 1280,
    'three-pane DraftEditor requires xl breakpoint'
  );

  async function analyzeWith(page, response) {
    await loginAsAlice(page);
    await mockAnalyze(page, response);
    await page
      .getByRole('button', { name: /^分析 OA/ })
      .filter({ visible: true })
      .click();
    const main = page.locator('main').filter({ visible: true }).last();
    await expect(main.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
    return main;
  }

  test('T2: DEGRADED result keeps export locked even after full review', async ({ page }) => {
    const degraded = defaultAnalysisResponse();
    degraded.cost_meta.model = 'mock-llama3.1:8b-DEGRADED-fallback';
    const main = await analyzeWith(page, degraded);

    // The degraded banner is shown…
    await expect(main.getByRole('alert').first()).toBeVisible();

    // …and even a fully-reviewed draft cannot be exported.
    await main.getByTestId('signoff-accept-all').first().click();
    await main.getByTestId('signoff-checkbox').first().check();
    await expect(main.getByTestId('signoff-export').first()).toBeDisabled();
    await expect(main.getByText(/不可簽核匯出/).first()).toBeVisible(); // gate hint
    // The whole-response export is locked for the same reason.
    await expect(main.getByTestId('response-export-submit')).toBeDisabled();
  });

  test('T3: a stripped-citation sentence cannot be accepted as-is', async ({ page }) => {
    const tainted = defaultAnalysisResponse();
    tainted.drafts[0].draft_text =
      'Applicant respectfully traverses. The reference [CITATION_REMOVED] fails to disclose the claimed feature.';
    const main = await analyzeWith(page, tainted);

    // Sentence 2 carries the stripped marker: its accept affordance is the
    // blocked variant, and bulk-accept must skip it.
    await expect(main.getByTestId('line-accept-blocked').first()).toBeVisible();
    await main.getByTestId('line-accept').first().click(); // sentence 1 accepts fine

    // Only the tainted sentence remains undecided → export stays locked…
    await main.getByTestId('signoff-checkbox').first().check();
    await expect(main.getByTestId('signoff-export').first()).toBeDisabled();

    // …until the attorney excludes THE TAINTED LINE (not just any line —
    // the accepted first sentence also still shows an exclude affordance).
    await main
      .getByTestId('draft-line')
      .filter({ has: page.getByTestId('citation-removed') })
      .getByTestId('line-exclude')
      .click();
    await expect(main.getByTestId('signoff-export').first()).toBeEnabled();
  });
});
