import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import i18n from '../lib/i18n.js';
import RouteErrorBoundary from './RouteErrorBoundary.jsx';

// Research 09 FE-5: one page crashing must not take the shell with it.

afterEach(() => vi.restoreAllMocks());

describe('RouteErrorBoundary', () => {
  it('shows a page-level error with a retry that re-renders the page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    let fail = true;
    function Page() {
      if (fail) throw new TypeError('Cannot read properties of undefined (reading map)');
      return <p>page content</p>;
    }
    render(
      <>
        <header>shell header</header>
        <RouteErrorBoundary>
          <Page />
        </RouteErrorBoundary>
      </>
    );
    expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('page.failed_title'));
    expect(screen.getByText('shell header')).toBeInTheDocument(); // the shell stays
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: i18n.t('page.retry') }));
    expect(screen.getByText('page content')).toBeInTheDocument();
  });

  it('offers only a reload when the page file failed to download', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    function Page() {
      throw new TypeError('Failed to fetch dynamically imported module: /assets/Analyze-1.js');
    }
    render(
      <RouteErrorBoundary>
        <Page />
      </RouteErrorBoundary>
    );
    expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('page.chunk_failed'));
    expect(screen.getByRole('button', { name: i18n.t('page.reload') })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: i18n.t('page.retry') })).toBeNull();
  });
});
