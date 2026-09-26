import { AlertTriangle } from 'lucide-react';
import i18n from '../lib/i18n.js';

// Crash screen. It renders OUTSIDE <I18nextProvider> (the boundary wraps the
// whole tree), so it reads the shared i18n instance directly instead of the
// useTranslation hook — still follows the user's language choice.
export default function CrashFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6 text-center">
      <div className="max-w-md">
        <AlertTriangle
          className="mx-auto mb-3 h-12 w-12 text-amber-500"
          strokeWidth={1.5}
          aria-hidden="true"
        />
        <h1 className="mb-1 text-lg font-semibold">{i18n.t('crash.title')}</h1>
        <p className="mb-4 text-sm text-slate-500">{i18n.t('crash.body')}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-md bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
        >
          {i18n.t('crash.reload')}
        </button>
      </div>
    </div>
  );
}
