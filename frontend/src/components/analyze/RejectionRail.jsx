import { useTranslation } from 'react-i18next';
import { CheckCircle2 } from 'lucide-react';

import { cn } from '../../lib/utils';
import ClaimTree from './ClaimTree.jsx';

/**
 * The OA's rejections as a list, each with its sentence-review progress, plus
 * the whole-response total (UX_REVIEW W1: status of every rejection visible at
 * once). `layout="rail"` for the xl+ side column, `"strip"` for a horizontal
 * selector on narrower screens.
 */
export default function RejectionRail({
  rejections,
  activeId,
  onSelect,
  progress,
  claimTree,
  layout = 'rail',
}) {
  const { t } = useTranslation();
  const totals = rejections.reduce(
    (acc, r) => {
      const p = progress[r.rejection_id];
      if (p) {
        acc.decided += p.decided;
        acc.total += p.total;
      }
      return acc;
    },
    { decided: 0, total: 0 }
  );
  const pct = totals.total ? Math.round((totals.decided / totals.total) * 100) : 0;

  const items = rejections.map((r) => {
    const p = progress[r.rejection_id];
    const active = r.rejection_id === activeId;
    const done = p && p.total > 0 && p.decided === p.total;
    return (
      <li key={r.rejection_id} className={layout === 'strip' ? 'w-56 shrink-0' : ''}>
        <button
          type="button"
          onClick={() => onSelect(r.rejection_id)}
          aria-current={active ? 'true' : undefined}
          data-testid="rejection-item"
          className={cn(
            'relative w-full rounded-brand border px-3 py-2.5 text-left transition-colors',
            active
              ? 'border-brand-fg/40 bg-brand-soft'
              : 'border-line bg-surface-raised hover:border-line-strong hover:bg-surface-hover'
          )}
        >
          <span className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-fg">
              {t(`rejection.${r.rejection_type}`, { defaultValue: r.rejection_type })}
            </span>
            {p?.exported ? (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                {t('workspace.exported')}
              </span>
            ) : (
              done && <CheckCircle2 className="h-4 w-4 text-success" aria-label={t('workspace.exported')} />
            )}
          </span>
          <span className="mt-0.5 block text-sm text-fg-muted">
            {t('claims_list', { list: r.affected_claims.join(', ') })}
          </span>
          {p && p.total > 0 && (
            <span className="mt-2 block">
              <span className="mb-1 block text-xs text-fg-muted">
                {t('workspace.rejections_progress', { decided: p.decided, total: p.total })}
              </span>
              <span className="block h-1 overflow-hidden rounded-full bg-line" aria-hidden="true">
                <span
                  className={cn('block h-full rounded-full', done ? 'bg-success' : 'bg-brand-fg')}
                  style={{ width: `${Math.round((p.decided / p.total) * 100)}%` }}
                />
              </span>
            </span>
          )}
        </button>
      </li>
    );
  });

  if (layout === 'strip') {
    return (
      <ul className="flex gap-2 overflow-x-auto pb-1" aria-label={t('workspace.rejections')}>
        {items}
      </ul>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby="rail-rejections">
        <div className="mb-2 flex items-baseline justify-between">
          <h2 id="rail-rejections" className="text-sm font-semibold text-fg">
            {t('workspace.rejections')}
          </h2>
          <span className="text-xs text-fg-muted">
            {t('workspace.whole_progress')} {pct}%
          </span>
        </div>
        <ul className="space-y-2">{items}</ul>
      </section>
      {claimTree?.length > 0 && (
        <ClaimTree
          claimTree={claimTree}
          rejections={rejections}
          activeRejectionId={activeId}
          onClaimClick={(_claimNo, rejectionId) => rejectionId && onSelect(rejectionId)}
        />
      )}
    </div>
  );
}
