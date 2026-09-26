// Q16/Q17/Q19/Q21: optional deadline inputs go out on the analyze request,
// and the result explains the start date, period and any assumptions.
import { test, expect } from '@playwright/test';
import { defaultAnalysisResponse, loginAsAlice, mockAnalyze } from './helpers/mock_backend.js';

function withDeadline(extra) {
  const r = defaultAnalysisResponse();
  r.deadline_summary = { ...r.deadline_summary, ...extra };
  return r;
}

test.describe('Deadline inputs & explanation', () => {
  test('untouched form sends no deadline fields', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    const route = mockAnalyze(page);
    await page.getByRole('button', { name: /^分析 OA/ }).click();
    const body = await route.capture;
    expect(body).not.toHaveProperty('applicant_domestic');
    expect(body).not.toHaveProperty('oa_sequence');
    expect(body).not.toHaveProperty('service_date');
  });

  test('filled inputs are sent and the result shows basis + assumptions', async ({
    page,
    viewport,
  }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    const route = mockAnalyze(
      page,
      withDeadline({
        mailing_date: '2026-03-02',
        start_date: '2026-03-17',
        start_date_basis: 'presumed_service',
        period_applied: '2 months (subsequent OA)',
        assumptions: ['未提供送達日，以發文日 + 15 日推定送達'],
      })
    );

    await page.locator('#analyze-applicant-domicile').selectOption('foreign');
    await page.locator('#analyze-oa-sequence').fill('2');
    await page.locator('#analyze-service-date').fill('2026-03-05');
    await page.getByRole('button', { name: /^分析 OA/ }).click();

    const body = await route.capture;
    expect(body.applicant_domestic).toBe(false);
    expect(body.oa_sequence).toBe(2);
    expect(body.service_date).toBe('2026-03-05');

    // Assumptions change the date itself → visible without opening "Why".
    await expect(page.getByTestId('deadline-assumptions')).toContainText('推定送達');
    await expect(page.getByTestId('deadline-notice')).toContainText('未經專利師覆核');

    await page.getByRole('button', { name: /計算依據/ }).click();
    const start = page.getByTestId('deadline-start');
    await expect(start).toContainText('推定送達日');
    await expect(page.getByTestId('deadline-details')).toContainText('2 months (subsequent OA)');
  });

  test('rules_reviewed=true hides the not-reviewed note', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    mockAnalyze(page, withDeadline({ rules_reviewed: true }));
    await page.getByRole('button', { name: /^分析 OA/ }).click();
    await expect(page.getByTestId('deadline-notice')).toBeAttached();
    await expect(page.getByTestId('deadline-notice')).not.toContainText('未經專利師覆核');
  });
});
