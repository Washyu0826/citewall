import { useTranslation } from 'react-i18next';
import { PIP_MAX, confidencePips } from '../../lib/confidence.js';

/**
 * Q36 — ordinal confidence glyph (● ● ○). See lib/confidence.js for the
 * thresholds and why this replaces the percentage. `labelKey` names what is
 * being rated (e.g. 'confidence.kind.parse'); the exact % stays available via
 * aria-label / title.
 */
export default function ConfidencePips({ score, labelKey }) {
  const { t } = useTranslation();
  const view = confidencePips(score);
  if (!view) return null;
  const what = t(labelKey);
  const bandText = t(`confidence.band.${view.band}`);
  const full = t('confidence.aria', { what, band: bandText, pct: view.pct });
  return (
    <span
      className="inline-flex items-center gap-1"
      role="img"
      aria-label={full}
      title={full}
      data-testid="confidence-pips"
      data-filled={view.filled}
    >
      <span className="text-slate-500 dark:text-slate-400">{what}</span>
      <span aria-hidden="true" className="inline-flex gap-0.5">
        {Array.from({ length: PIP_MAX }, (_, i) => (
          <span
            key={i}
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              i < view.filled
                ? 'bg-slate-600 dark:bg-slate-300'
                : 'border border-slate-400 dark:border-slate-500'
            }`}
          />
        ))}
      </span>
      <span className="text-slate-500 dark:text-slate-400">{bandText}</span>
    </span>
  );
}
