import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';

import { Button } from './ui/button.jsx';
import { asText, classifyError } from '../lib/errorInfo.js';

const RATE_LIMIT_COUNTDOWN_SEC = 30;

export default function ErrorBanner({ error, onRetry, onDismiss, onLogin }) {
  const { t } = useTranslation();
  const info = classifyError(error, t);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (info?.countdown) setCountdown(RATE_LIMIT_COUNTDOWN_SEC);
    else setCountdown(0);
  }, [error, info?.countdown]);

  useEffect(() => {
    if (countdown <= 0) return undefined;
    const id = setInterval(() => setCountdown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [countdown]);

  if (!info) return null;

  const retryDisabled = info.countdown && countdown > 0;
  const showRetry = info.retryable && typeof onRetry === 'function';
  const showLogin = info.requiresLogin && typeof onLogin === 'function';
  const rawMessage =
    error && typeof error === 'object' ? error.message || String(error) : String(error || '');

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300 sm:flex-row sm:items-start sm:gap-3"
    >
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />

      <div className="min-w-0 flex-1">
        <p className="wrap-break-word text-sm leading-5">{asText(info.message)}</p>
        {error?.requestId && (
          <p className="mt-1 text-xs opacity-80">
            {t('errors.reference', { id: error.requestId })}
          </p>
        )}
        {info.showDetails && rawMessage && (
          <details className="mt-1 text-xs text-rose-600/80 dark:text-rose-300/80">
            <summary className="cursor-pointer select-none">
              {t('errors.technical_details')}
            </summary>
            <pre className="mt-1 whitespace-pre-wrap wrap-break-word font-mono text-2xs">
              {rawMessage}
            </pre>
          </details>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap gap-2 self-start sm:self-auto">
        {showLogin && (
          <Button type="button" variant="destructive" size="xs" onClick={onLogin}>
            {t('errors.login_again')}
          </Button>
        )}
        {showRetry && (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={onRetry}
            disabled={retryDisabled}
            className="border-rose-300 text-rose-700 hover:bg-rose-100 hover:text-rose-700 disabled:cursor-not-allowed dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-900/40 dark:hover:text-rose-300"
          >
            {retryDisabled ? t('errors.retry_in', { seconds: countdown }) : t('errors.retry')}
          </Button>
        )}
        {typeof onDismiss === 'function' && (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={onDismiss}
            className="border-rose-200 text-rose-600 hover:bg-rose-100 hover:text-rose-600 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-900/40 dark:hover:text-rose-300"
          >
            {t('errors.dismiss')}
          </Button>
        )}
      </div>
    </div>
  );
}
