// Stack-status footer — one chip per infrastructure tier (Gateway / AI Engine
// / digiRunner / Dify). Shown to IT / audit roles only (UX_REVIEW M3: the
// attorney reading drafts all day does not need integration lights).
//
//   - Gateway is probed through the same-origin /api/v1/health (JSON body).
//   - The other three are opaque `no-cors` reachability probes: any HTTP
//     response = green "up"; connection refused / timeout = gray "unknown".
import { test, expect } from '@playwright/test';
import {
  loginAsAlice,
  mockAuditRecent,
  mockAuditVerify,
  mockLogin,
  mockQuota,
  mockStackProbes,
} from './helpers/mock_backend.js';

async function loginAsDave(page) {
  await mockLogin(page, 'audit_dave');
  await mockQuota(page);
  await mockAuditRecent(page);
  await mockAuditVerify(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Dave/ }).click();
  await page.waitForURL(/\/audit/, { timeout: 5000 });
}

test.describe('Stack status footer', () => {
  test('renders all four service chips for the auditor', async ({ page }) => {
    await mockStackProbes(page);
    await loginAsDave(page);

    const footer = page.getByTestId('stack-status');
    await expect(footer).toBeVisible();
    for (const label of ['Gateway', 'AI Engine', 'digiRunner', 'Dify']) {
      await expect(footer.getByText(label)).toBeVisible();
    }
  });

  test('is not shown to an attorney', async ({ page }) => {
    await mockStackProbes(page);
    await loginAsAlice(page);
    await expect(page.getByTestId('workspace-stepper')).toBeVisible();
    await expect(page.getByTestId('stack-status')).toHaveCount(0);
  });

  test('gateway green, unreachable externals gray', async ({ page }) => {
    await mockStackProbes(page, { gateway: true, aiEngine: false, digirunner: false, dify: false });
    await loginAsDave(page);

    await expect(page.getByTestId('stack-status-gateway')).toHaveAttribute('data-status', 'up');
    await expect(page.getByTestId('stack-status-ai-engine')).toHaveAttribute('data-status', 'unknown');
    await expect(page.getByTestId('stack-status-digirunner')).toHaveAttribute('data-status', 'unknown');
    await expect(page.getByTestId('stack-status-dify')).toHaveAttribute('data-status', 'unknown');
  });

  test('all chips green when every tier responds', async ({ page }) => {
    await mockStackProbes(page, { gateway: true, aiEngine: true, digirunner: true, dify: true });
    await loginAsDave(page);

    for (const id of ['gateway', 'ai-engine', 'digirunner', 'dify']) {
      await expect(page.getByTestId(`stack-status-${id}`)).toHaveAttribute('data-status', 'up');
    }
  });

  test('gateway 503 degrades to gray, not an error', async ({ page }) => {
    await mockStackProbes(page, { gateway: false });
    await loginAsDave(page);
    await expect(page.getByTestId('stack-status-gateway')).toHaveAttribute('data-status', 'unknown');
  });
});
