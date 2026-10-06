import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { isChunkLoadError } from '../lib/errorInfo.js';
import { SentryErrorBoundary } from '../lib/sentry.jsx';
import { Page } from './ui/page.jsx';

/**
 * One error boundary per page (research 09 FE-5). Before, the only boundary
 * wrapped the whole app: any render error in one page replaced everything —
 * header, navigation, session — with the crash screen, and the only way out
 * was a reload. Here the shell stays and the user can go to another page.
 * App.jsx keys it by path, so navigating away resets it.
 */
export default function RouteErrorBoundary({ children }) {
  return (
    <SentryErrorBoundary fallback={({ error, resetError }) => <RouteError error={error} onRetry={resetError} />}>
      {children}
    </SentryErrorBoundary>
  );
}

function RouteError({ error, onRetry }) {
  const { t } = useTranslation();
  // A page chunk that failed to download stays failed (React.lazy caches the
  // rejected import): only a reload helps, so offer only that.
  const chunk = isChunkLoadError(error);
  return (
    <Page>
      <div role="alert" className="max-w-2xl border-l-4 border-warning bg-warning-soft px-5 py-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
          <div>
            <h1 className="text-lg font-semibold text-fg">{t('page.failed_title')}</h1>
            <p className="mt-1 text-sm text-fg-secondary">{chunk ? t('page.chunk_failed') : t('page.failed_body')}</p>
            <button
              type="button"
              onClick={chunk ? () => window.location.reload() : onRetry}
              className="mt-3 rounded-brand bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              {chunk ? t('page.reload') : t('page.retry')}
            </button>
          </div>
        </div>
      </div>
    </Page>
  );
}
