// Analyze flow e2e — the redesigned workspace (setup → analyze → review).
//
// Each test logs Alice in (mock /v1/auth/login), opens the workspace through
// the nav rail, mocks /v1/oa/analyze and asserts what the attorney sees.
// At 1440px (desktop project) the layout is two columns and prior art opens
// in a dialog; three columns only from 1536px.
import { test, expect } from '@playwright/test';
import { mockAnalyze, defaultAnalysisResponse, loginAsAlice } from './helpers/mock_backend.js';

const analyzeButton = (page) => page.getByTestId('analyze-submit');

test.describe('Analyze flow', () => {
  test('setup mode shows the steps, the OA input and the case', async ({ page }) => {
    await loginAsAlice(page);
    await expect(page.getByTestId('workspace-stepper')).toBeVisible();
    await expect(page.locator('#analyze-oa-text')).toBeVisible();
    await expect(page.locator('#analyze-case-id')).toHaveValue('CASE-2025-001');
    await expect(analyzeButton(page)).toBeEnabled();
  });

  test('analyze button POSTs to /v1/oa/analyze with expected body', async ({ page }) => {
    await loginAsAlice(page);
    const route = mockAnalyze(page);
    await route;
    await analyzeButton(page).click();

    const body = await route.capture;
    expect(body.case_id).toBe('CASE-2025-001');
    expect(body.target_patent_no).toBe('US17123456');
    expect(typeof body.oa_text).toBe('string');
    expect(body.oa_text.length).toBeGreaterThan(50);
  });

  test('a result shows the rejection, strategy and prior art', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);
    await analyzeButton(page).click();

    const main = page.locator('main');
    await expect(main.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
    await expect(main.getByText(/主張 cited prior art/).first()).toBeVisible();
    await expect(main.getByText('103_obviousness').first()).toBeVisible();

    // Prior art: inline from 1536px, otherwise behind the 前案 button.
    const inline = page.getByTestId('references-panel');
    if (!(await inline.isVisible())) {
      await page.getByRole('button', { name: /^前案$/ }).first().click();
    }
    await expect(page.getByTestId('references-panel').getByText('US7654321').first()).toBeVisible();
  });

  test('verification banner surfaces stripped citations + verifier model', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        drafts: [
          {
            rejection_id: 'REJ-1',
            strategy: '主張 cited prior art 並未揭露非均勻截面。 [GROUNDED_REF_1]',
            draft_text:
              'Applicant respectfully traverses. [GROUNDED_REF_1] does not teach the ' +
              'limitation. The examiner cited [CITATION_REMOVED] which is unsupported.',
            grounded_citations: ['[GROUNDED_REF_1]'],
            confidence: 0.82,
            requires_attorney_review: true,
            invalid_citations: ['US9999999', 'Smith v. Jones, 999 F.3d 1234'],
            verifier_confidence: 0.91,
            verifier_model: 'mock-haiku-verifier',
          },
        ],
      })
    );
    await analyzeButton(page).click();

    const banner = page.getByTestId('verification-banner').filter({ visible: true }).first();
    await expect(banner).toBeVisible({ timeout: 10_000 });
    await expect(banner).toContainText('2 個引用未通過驗證');
    await expect(banner).toContainText('US9999999');
    await expect(banner).toContainText('Smith v. Jones, 999 F.3d 1234');
    await expect(banner).toContainText('mock-haiku-verifier');
  });

  test('a citation pill opens its source in an accessible popover', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);
    await analyzeButton(page).click();

    const pill = page.getByTestId('grounded-ref').filter({ visible: true }).first();
    await expect(pill).toBeVisible({ timeout: 10_000 });
    await pill.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog').getByText('US7654321')).toBeVisible();
  });

  test('degraded result shows an unmissable alert banner', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        cost_meta: {
          model: 'dify/qwen2.5:7b-DEGRADED-mock',
          prompt_tokens: 0,
          completion_tokens: 0,
          estimated_cost_usd: 0,
          cache_hit: false,
        },
      })
    );
    await analyzeButton(page).click();

    const alert = page.getByRole('alert').filter({ hasText: 'AI 服務降級中' }).first();
    await expect(alert).toBeVisible({ timeout: 10_000 });
  });

  test('deadline summary explains the calculation basis on demand', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        deadline_summary: {
          received_date: '2025-04-15T00:00:00Z',
          statutory_deadline: '2025-07-15T00:00:00Z',
          recommended_internal_deadline: '2025-07-08T00:00:00Z',
          days_remaining: 42,
          holiday_calendar_version: '2025.1',
          warnings: ['截止日落在週六，依規則順延至下一個工作日'],
        },
      })
    );
    await analyzeButton(page).click();

    const whyBtn = page.getByRole('button', { name: /計算依據/ });
    await expect(whyBtn.first()).toBeVisible({ timeout: 10_000 });
    await whyBtn.first().click();

    const details = page.getByTestId('deadline-details');
    await expect(details).toBeVisible();
    await expect(details).toContainText('2025.1');
    await expect(details).toContainText('順延至下一個工作日');
    // The recommended internal date is shown in the header itself.
    await expect(page.getByText(/建議內部完成日/).first()).toBeVisible();
  });

  test('language switch to EN translates the workspace', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 640, 'the header language toggle is sm+ (phones use the account menu)');
    await loginAsAlice(page);
    await mockAnalyze(page);

    await page
      .getByRole('group', { name: /^(Language|語言)$/ })
      .getByRole('button', { name: 'EN' })
      .click();

    await expect(analyzeButton(page)).toHaveText(/Analyze OA/);
    await analyzeButton(page).click();
    await expect(page.locator('main').getByText('Response strategy').first()).toBeVisible({ timeout: 10_000 });
  });

  test('error 500 shows an ErrorBanner with a retry button', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page, { status: 500, body: { detail: 'engine timeout' } });
    await analyzeButton(page).click();

    const alert = page.getByRole('alert').filter({ hasText: '伺服器忙線中' }).first();
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert.getByRole('button', { name: '重試' })).toBeVisible();
  });

  test('edit input returns to the setup form with the OA text kept', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);
    await analyzeButton(page).click();
    await expect(page.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: '編輯輸入' }).click();
    await expect(page.locator('#analyze-oa-text')).toHaveValue(/Office Action/);
  });

  test('the usage card renders the quota', async ({ page }) => {
    await loginAsAlice(page);
    await expect(page.getByRole('heading', { name: /用量/ }).first()).toBeVisible();
    await expect(page.getByText('1,500 / 100,000')).toBeVisible();
  });
});
