// OAUpload drag-drop e2e — drives the hidden <input type="file"> directly
// since DataTransfer is non-trivial to fake in Playwright. The DropZone
// click-target opens the input picker, but the file is delivered via
// setInputFiles() which fires the same onChange handler.
import { test, expect } from '@playwright/test';
import {
  loginAsAlice,
  mockUpload,
} from './helpers/mock_backend.js';

// The workspace renders ONE layout; OAUpload lives in the "上傳檔案" tab of
// the OA card (the paste tab is the default, pre-filled with a sample OA).
// The file input is display:none by design — setInputFiles works on it.
function fileInput(page) {
  return page.locator('main input[type="file"]');
}

function visibleMain(page) {
  return page.locator('main');
}

async function openUpload(page) {
  await loginAsAlice(page);
  await page.getByRole('tab', { name: /上傳檔案/ }).click();
}

test.describe('Upload flow', () => {
  // The mobile project still mounts OAUpload (it's inside the InputPane,
  // which renders on the default mobile tab), so these tests work on both.

  test('successful upload populates the textarea via onExtractSuccess', async ({ page }) => {
    await openUpload(page);
    await mockUpload(page, {
      extracted_text: 'EXTRACTED OA TEXT for test — Claim 1 rejected under §103.',
      page_count: 3,
      char_count: 57,
      warnings: [],
      ocr_pages_used: 0,
      cost_meta: { estimated_cost_usd: 0 },
    });

    const input = fileInput(page);
    await input.setInputFiles({
      name: 'sample-oa.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 fake pdf bytes for the e2e harness'),
    });

    // Scope to the visible main so we don't pick up the hidden mobile/desktop
    // duplicate that React also rendered (see fileInput() above).
    const main = visibleMain(page);

    // The status pane should now show the file name + an Upload button.
    await expect(main.getByText('sample-oa.pdf').first()).toBeVisible();
    const uploadBtn = main.getByRole('button', { name: /^上傳$/ });
    await expect(uploadBtn).toBeVisible();
    await uploadBtn.click();

    // After server-extracting → success, the "使用此文字" button appears.
    const useBtn = main.getByRole('button', { name: /使用此文字/ });
    await expect(useBtn).toBeVisible({ timeout: 5000 });
    await useBtn.click();

    // Using the text switches to the paste tab with the extracted OA loaded.
    await expect(page.locator('#analyze-oa-text')).toHaveValue(/EXTRACTED OA TEXT/);
  });

  test('a >30MB file shows a size error', async ({ page }) => {
    await openUpload(page);
    await mockUpload(page); // mocked, but the size guard fires client-side first.

    // 31 MB of zeroes — over the 30 MB hard ceiling.
    const tooBig = Buffer.alloc(31 * 1024 * 1024, 0);
    await fileInput(page).setInputFiles({
      name: 'huge-oa.pdf',
      mimeType: 'application/pdf',
      buffer: tooBig,
    });

    // The component renders the i18n string upload.too_large into a rose chip.
    await expect(visibleMain(page).getByText('檔案太大（>30MB）').first()).toBeVisible();
  });

  test('a .txt file is rejected with a type error', async ({ page }) => {
    await openUpload(page);
    await mockUpload(page);

    await fileInput(page).setInputFiles({
      name: 'oa.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Office Action body text - not allowed'),
    });

    // upload.invalid_type → "只支援 PDF 或 DOCX" — said once, in the upload
    // panel, never as the workspace's "connection failed" banner (UX-1).
    await expect(visibleMain(page).getByRole('alert')).toHaveText('只支援 PDF 或 DOCX');
    await expect(page.getByText(/連線失敗/)).toHaveCount(0);
  });

  test('a server-side upload failure keeps the file and offers a retry', async ({ page }) => {
    await openUpload(page);
    await mockUpload(page, { status: 500, body: { detail: 'OCR engine unavailable' } });
    await fileInput(page).setInputFiles({
      name: 'scan.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 fake'),
    });
    const main = visibleMain(page);
    await main.getByRole('button', { name: /^上傳$/ }).click();

    await expect(main.getByRole('alert')).toHaveText('OCR engine unavailable');
    await expect(main.getByText('scan.pdf').first()).toBeVisible();
    await expect(main.getByRole('button', { name: '重試' })).toBeEnabled();
    // The analyze action is untouched: no analyze banner, no misleading retry.
    await expect(page.getByText(/連線失敗/)).toHaveCount(0);
  });

  test('drop zone is keyboard-accessible (role=button)', async ({ page }) => {
    await openUpload(page);

    // The DropZone is role=button and accepts space/enter.
    const dz = visibleMain(page)
      .getByRole('button', { name: /拖放.*PDF|browse files|瀏覽檔案/ })
      .first();
    await expect(dz).toBeVisible();
    // Ensure clickability — the click delegates to a hidden file input.
    await expect(dz).toBeEnabled();
  });

  test('dragover highlights the drop zone (navy state)', async ({ page }) => {
    await openUpload(page);

    const dz = visibleMain(page)
      .getByRole('button', { name: /拖放.*PDF|browse files|瀏覽檔案/ })
      .first();
    await expect(dz).toBeVisible();

    // Idle: slate border, no navy background. Dispatch real drag events with a
    // genuine DataTransfer (constructed in-page) so React's onDragOver fires and
    // flips the highlight state — a plain-object dataTransfer can't be coerced
    // into a DragEvent by Playwright's dispatchEvent.
    await expect(dz).not.toHaveClass(/bg-navy-50/);
    await dz.evaluate((el) => {
      const dt = new DataTransfer();
      el.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    });
    await expect(dz).toHaveClass(/border-navy-400/);
    await expect(dz).toHaveClass(/bg-navy-50/);

    // dragleave clears the highlight again.
    await dz.evaluate((el) => {
      const dt = new DataTransfer();
      el.dispatchEvent(new DragEvent('dragleave', { bubbles: true, cancelable: true, dataTransfer: dt }));
    });
    await expect(dz).not.toHaveClass(/bg-navy-50/);
  });

  test('upload renders preview: per-page text, OCR badge, element table, PDF frame', async ({
    page,
  }) => {
    await openUpload(page);
    await mockUpload(page, {
      // Two pages joined with the backend separator. The component splits on it.
      extracted_text:
        'PAGE ONE BODY — Claim 1 rejected under §103.' +
        '\n\n--- page break ---\n\n' +
        'PAGE TWO BODY — see figure element 200.',
      page_count: 2,
      char_count: 82,
      ocr_pages_used: 1,
      warnings: ['第 2 頁為掃描影像，已使用 OCR'],
      cost_meta: { estimated_cost_usd: 0.02 },
      element_table: { 100: 'housing', 200: 'microchannel' },
    });

    await fileInput(page).setInputFiles({
      name: 'scanned-oa.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 fake pdf bytes for the e2e harness'),
    });

    const main = visibleMain(page);
    const uploadBtn = main.getByRole('button', { name: /^上傳$/ });
    await expect(uploadBtn).toBeVisible();
    await uploadBtn.click();

    // Preview block appears once extraction succeeds.
    const preview = main.locator('[data-testid="extracted-text-preview"]');
    await expect(preview).toBeVisible({ timeout: 5000 });

    // Per-page blocks: both pages rendered as separate scrollable blocks.
    const pages = main.locator('[data-testid="extracted-text-pages"] > div');
    await expect(pages).toHaveCount(2);
    await expect(main.getByText('PAGE ONE BODY')).toBeVisible();
    await expect(main.getByText('PAGE TWO BODY')).toBeVisible();

    // OCR badge ("1 頁透過 OCR").
    await expect(main.locator('[data-testid="ocr-badge"]')).toBeVisible();
    await expect(main.locator('[data-testid="ocr-badge"]')).toContainText('OCR');

    // Element table (numeral → description) surfaced in the preview.
    const table = main.locator('[data-testid="element-table"]');
    await expect(table).toBeVisible();
    await expect(table).toContainText('microchannel');

    // Native PDF preview: <object type="application/pdf"> on the file blob URL.
    const pdfFrame = main.locator('[data-testid="pdf-preview"]');
    await expect(pdfFrame).toHaveAttribute('type', 'application/pdf');
    await expect(pdfFrame).toHaveAttribute('data', /^blob:/);
  });
});
