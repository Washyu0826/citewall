import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';

import App from './App.jsx';
import i18n from './lib/i18n.js';
import { queryClient } from './lib/queryClient.js';
import { ThemeProvider } from './lib/theme.jsx';
import { DEMO_USERS, defaultCases, defaultQuota } from '../tests/e2e/helpers/mock_backend.js';

// Research 09 FE-5, through the real App: one page crashing keeps the shell,
// and leaving the page clears its error (App.jsx keys the boundary by path).

vi.mock('./components/pages/Cases.jsx', () => ({
  default: function CrashingCases() {
    throw new TypeError('Cannot read properties of undefined (reading map)');
  },
}));

function json(body) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  globalThis.fetch = vi.fn(async (url) => {
    const path = String(url).replace(/^\/api/, '').split('?')[0];
    if (path === '/v1/auth/login') return json(DEMO_USERS.alice);
    if (path === '/v1/quota') return json(defaultQuota());
    if (path === '/v1/cases') return json(defaultCases());
    return json({});
  });
});

afterEach(() => {
  queryClient.clear();
  vi.restoreAllMocks();
});

describe('App page boundaries', () => {
  it('a crashing page keeps the shell, and navigating away clears the error', async () => {
    render(
      <StrictMode>
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={queryClient}>
            <ThemeProvider>
              <MemoryRouter initialEntries={['/login']}>
                <App />
              </MemoryRouter>
            </ThemeProvider>
          </QueryClientProvider>
        </I18nextProvider>
      </StrictMode>
    );
    fireEvent.click(await screen.findByRole('button', { name: /Alice/ }));
    fireEvent.click(await screen.findByTestId('nav-cases'));

    expect(await screen.findByText(i18n.t('page.failed_title'))).toBeInTheDocument();
    expect(screen.getByTestId('primary-nav')).toBeInTheDocument(); // the shell survived

    fireEvent.click(screen.getByTestId('nav-home'));
    expect(await screen.findByTestId('home-new-analysis', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('page.failed_title'))).toBeNull();
  });
});
