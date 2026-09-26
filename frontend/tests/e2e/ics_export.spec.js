// Deadline → calendar (.ics) export — UX_REVIEW industry-gap S item.
//
// The attorney's real calendar is Outlook / Google Calendar, not this tool;
// a missed statutory deadline kills the patent. The export is generated
// entirely client-side (Blob) from data already in the analysis response —
// no backend call, nothing leaves the browser.
import fs from 'node:fs';
import { test, expect } from '@playwright/test';
import { loginAsAlice, mockAnalyze } from './helpers/mock_backend.js';

test.describe('Deadline .ics export', () => {
  test.skip(
    ({ viewport }) => viewport && viewport.width < 1280,
    'exercised on desktop; the summary bar logic is viewport-independent'
  );

  test('exports a two-event RFC 5545 calendar with reminders', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);
    await page
      .getByRole('button', { name: /^分析 OA/ })
      .filter({ visible: true })
      .click();

    // Open the deadline "why" details where the export lives.
    await page.getByRole('button', { name: /計算依據|Why/ }).first().click();
    const exportBtn = page.getByTestId('deadline-ics-export').first();
    await expect(exportBtn).toBeVisible();

    const [download] = await Promise.all([page.waitForEvent('download'), exportBtn.click()]);
    expect(download.suggestedFilename()).toBe('CASE-2025-001-deadlines.ics');

    const ics = fs.readFileSync(await download.path(), 'utf-8');
    expect(ics).toContain('BEGIN:VCALENDAR');
    // Two all-day events: statutory + recommended internal.
    expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(2);
    expect(ics).toContain('DTSTART;VALUE=DATE:');
    expect(ics).toContain('CASE-2025-001');
    // Reminders ride along (7d statutory / 3d internal).
    expect(ics).toContain('TRIGGER:-P7D');
    expect(ics).toContain('TRIGGER:-P3D');
    // RFC 5545 mandates CRLF line endings.
    expect(ics).toContain('\r\n');
  });
});
