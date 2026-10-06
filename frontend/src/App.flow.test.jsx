import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Profiler, StrictMode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';

import App from './App.jsx';
import i18n from './lib/i18n.js';
import { queryClient } from './lib/queryClient.js';
import { ThemeProvider } from './lib/theme.jsx';
import { ToastViewport } from './lib/toast.jsx';
import {
  DEMO_USERS,
  defaultAnalysisResponse,
  defaultCases,
  defaultQuota,
} from '../tests/e2e/helpers/mock_backend.js';

// The whole app, StrictMode and lazy pages included, against a fake gateway:
// the workspace flows that cross pages (research 09 FE-L1).

let releaseAnalyze;
let analyzeCalls;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

beforeEach(() => {
  analyzeCalls = 0;
  const gate = new Promise((resolve) => {
    releaseAnalyze = resolve;
  });
  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^\/api/, '').split('?')[0];
    if (path === '/v1/auth/login') return json(DEMO_USERS.alice);
    if (path === '/v1/quota') return json(defaultQuota());
    if (path === '/v1/cases') return json(defaultCases());
    if (path === '/v1/oa/analyze') {
      analyzeCalls += 1;
      await gate;
      if (init.signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
      return json(defaultAnalysisResponse());
    }
    return json({});
  });
});

afterEach(() => {
  queryClient.clear();
  vi.restoreAllMocks();
});

function renderApp() {
  return render(
    <StrictMode>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <MemoryRouter initialEntries={['/login']}>
              <App />
              <ToastViewport />
            </MemoryRouter>
          </ThemeProvider>
        </QueryClientProvider>
      </I18nextProvider>
    </StrictMode>
  );
}

async function loginAndOpenWorkspace() {
  renderApp();
  fireEvent.click(await screen.findByRole('button', { name: /Alice/ }));
  fireEvent.click(await screen.findByTestId('nav-analyze'));
  return screen.findByTestId('analyze-submit', {}, { timeout: 5000 });
}

describe('App render stability', () => {
  it('the workspace settles: no commits while the attorney does nothing', async () => {
    let commits = 0;
    render(
      <Profiler id="app" onRender={() => (commits += 1)}>
        <StrictMode>
          <I18nextProvider i18n={i18n}>
            <QueryClientProvider client={queryClient}>
              <ThemeProvider>
                <MemoryRouter initialEntries={['/login']}>
                  <App />
                  <ToastViewport />
                </MemoryRouter>
              </ThemeProvider>
            </QueryClientProvider>
          </I18nextProvider>
        </StrictMode>
      </Profiler>
    );
    fireEvent.click(await screen.findByRole('button', { name: /Alice/ }));
    fireEvent.click(await screen.findByTestId('nav-analyze'));
    await screen.findByTestId('analyze-submit', {}, { timeout: 5000 });
    await new Promise((r) => setTimeout(r, 300));
    const settled = commits;
    await new Promise((r) => setTimeout(r, 600));
    expect(commits - settled).toBeLessThan(3);
  });
});

describe('App workspace flows', () => {
  it('an analysis that finishes while the attorney is on another page is announced and kept', async () => {
    fireEvent.click(await loginAndOpenWorkspace());
    await screen.findByTestId('analysis-cancel');
    fireEvent.click(screen.getByTestId('nav-home'));
    await screen.findByTestId('home-new-analysis', {}, { timeout: 5000 });
    releaseAnalyze();
    expect(await screen.findByText(/的分析完成了/, {}, { timeout: 5000 })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('nav-analyze'));
    expect(await screen.findByText('答辯策略', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(analyzeCalls).toBe(1); // kept, not re-run
  });
});
