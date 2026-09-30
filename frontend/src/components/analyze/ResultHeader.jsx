import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CalendarPlus, ChevronDown, PencilLine } from 'lucide-react';

import { downloadDeadlineIcs } from '../../lib/ics.js';
import { formatDate } from '../../lib/format.js';
import { jurisdictionForPatent } from '../../lib/jurisdiction.js';
import { showNotReviewedNote, startBasisKey } from '../../lib/deadlineInputs.js';
import { deadlineTone } from '../../lib/cases.js';
import { toast } from '../../lib/toast.jsx';
import { cn } from '../../lib/utils';
import { Badge } from '../ui/badge.jsx';
import { Button } from '../ui/button.jsx';
import { SecurityBadge } from '../cases/CaseBits.jsx';

const POLICY_KEYS = ['authz_passed', 'rate_limit_passed', 'quota_passed'];

/**
 * Result header: the case, the statutory deadline (with how it was computed —
 * a wrong date forfeits rights, so "why this date" must be one click away) and
 * the request's REAL gate outcomes (policy_decisions — never faked, UX_REVIEW T1).
 */
export default function ResultHeader({ result, caseId, targetPatent, securityLevel, onEditInput }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const ds = result.deadline_summary || {};
  const days = Number.isFinite(ds.days_remaining) ? ds.days_remaining : null;
  const locale = (i18n.language || 'zh-TW').startsWith('zh') ? 'zh-TW' : 'en-US';
  const fmt = (iso) => (iso ? formatDate(iso, { locale, year: 'numeric', month: '2-digit', day: '2-digit' }) || '—' : '—');
  const warnings = Array.isArray(ds.warnings) ? ds.warnings : [];
  const assumptions = Array.isArray(ds.assumptions) ? ds.assumptions : [];
  const basisKey = startBasisKey(ds.start_date_basis);
  const isTW = jurisdictionForPatent(targetPatent) === 'TW';

  const chips = useMemo(() => {
    const pd = result.policy_decisions || {};
    const out = POLICY_KEYS.filter((k) => typeof pd[k] === 'boolean').map((k) => ({
      key: k,
      good: pd[k],
      label: t(`security_badge.${k}.${pd[k] ? 'ok' : 'no'}`),
    }));
    if (typeof result.cost_meta?.cache_hit === 'boolean') {
      out.push({ key: 'cache_hit', good: true, neutral: true, label: t(`security_badge.cache_hit.${result.cost_meta.cache_hit ? 'ok' : 'no'}`) });
    }
    if (typeof pd.circuit_open === 'boolean') {
      out.push({ key: 'circuit_open', good: !pd.circuit_open, label: t(`security_badge.circuit_open.${pd.circuit_open ? 'ok' : 'no'}`) });
    }
    return out;
  }, [result, t]);

  const daysLabel =
    days === null
      ? '—'
      : days < 0
        ? t('deadline.overdue', { count: -days })
        : days === 0
          ? t('deadline.today')
          : t('deadline.days_left', { count: days });

  return (
    <section className="rounded-brand border border-line bg-surface-raised shadow-elev-1" aria-label={t('analyze.result.deadline_label')}>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4 p-4">
        <div className="min-w-0">
          <p className="text-sm text-fg-muted">{t('workspace.case_card')}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-2">
            <span className="font-mono text-lg font-semibold text-fg">{caseId}</span>
            <SecurityBadge level={securityLevel} size="sm" />
          </p>
          <p className="mt-0.5 font-mono text-sm text-fg-muted">{targetPatent}</p>
        </div>

        <div className="min-w-0">
          <p className="text-sm text-fg-muted">{t('analyze.result.deadline_label')}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-2">
            <time dateTime={ds.statutory_deadline} className="font-mono text-lg font-semibold text-fg">
              {fmt(ds.statutory_deadline)}
            </time>
            <Badge tone={deadlineTone(days)}>{daysLabel}</Badge>
            {warnings.length > 0 && (
              <Badge tone="warning" title={warnings.join('\n')}>
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                {warnings.length}
              </Badge>
            )}
          </p>
          {ds.recommended_internal_deadline && (
            <p className="mt-0.5 text-sm text-fg-muted">
              {t('analyze.result.internal')}：<span className="font-mono">{fmt(ds.recommended_internal_deadline)}</span>
            </p>
          )}
        </div>

        <div className="ml-auto flex flex-col items-end gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {t('analyze.result.why')}
              <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} aria-hidden="true" />
            </Button>
            <Button variant="ghost" size="sm" onClick={onEditInput}>
              <PencilLine className="h-4 w-4" aria-hidden="true" />
              {t('workspace.edit_input')}
            </Button>
          </div>
          {chips.length > 0 && (
            <span className="flex flex-wrap justify-end gap-1.5" data-testid="policy-chips">
              {chips.map((c) => (
                <Badge key={c.key} size="sm" tone={c.neutral ? 'neutral' : c.good ? 'success' : 'error'}>
                  {c.label}
                </Badge>
              ))}
            </span>
          )}
        </div>
      </div>

      {/* Rules not reviewed by a patent attorney — said every time a deadline
          is shown, not only inside the details. */}
      {(showNotReviewedNote(ds) || isTW) && (
        <div
          data-testid="deadline-notice"
          className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line-subtle bg-warning-soft px-4 py-2 text-sm text-warning"
        >
          {showNotReviewedNote(ds) && <span>{t('deadline_notice.not_reviewed')}</span>}
          {isTW && <span data-testid="deadline-tw-foreign-hint">{t('deadline_notice.tw_foreign_hint')}</span>}
        </div>
      )}

      {/* Assumptions change the date itself, so they stay visible. */}
      {assumptions.length > 0 && (
        <div data-testid="deadline-assumptions" className="border-t border-line-subtle px-4 py-2 text-sm text-fg-secondary">
          <span className="font-medium">{t('deadline_detail.assumptions')}：</span>
          {assumptions.join('；')}
        </div>
      )}

      {open && (
        <div data-testid="deadline-details" className="space-y-3 border-t border-line-subtle bg-surface-sunken px-4 py-3 text-sm">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
            {ds.mailing_date && <Detail term={t('deadline_detail.mailing_date')} value={fmt(ds.mailing_date)} />}
            {ds.start_date && (
              <div data-testid="deadline-start">
                <dt className="text-fg-muted">{t('deadline_detail.start_date')}</dt>
                <dd className="text-fg">
                  <span className="font-mono">{fmt(ds.start_date)}</span>
                  {basisKey && <span className="block text-xs text-fg-muted">{t(basisKey)}</span>}
                </dd>
              </div>
            )}
            {ds.period_applied && <Detail term={t('deadline_detail.period')} value={ds.period_applied} mono={false} />}
            <Detail term={t('analyze.result.received')} value={fmt(ds.received_date)} />
            <Detail term={t('analyze.result.statutory')} value={fmt(ds.statutory_deadline)} />
            {ds.holiday_calendar_version && <Detail term={t('analyze.result.calendar')} value={ds.holiday_calendar_version} />}
          </dl>
          {warnings.length > 0 && (
            <ul className="list-inside list-disc text-warning">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-3">
            {/* Plain client-side Blob download — nothing leaves the browser. */}
            <Button
              type="button"
              variant="outline"
              size="xs"
              data-testid="deadline-ics-export"
              onClick={() => {
                const ok = downloadDeadlineIcs({ caseId, deadline: ds, t });
                if (ok) toast.success(t('analyze.ics.downloaded'));
                else toast.error(t('analyze.ics.no_deadline'));
              }}
            >
              <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" />
              {t('analyze.ics.button')}
            </Button>
            <span className="ml-auto font-mono text-xs text-fg-muted">
              {t('workspace.model')} {result.cost_meta?.model ?? '—'} · {t('workspace.request')}{' '}
              {(result.request_id || '').slice(0, 8)}
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

function Detail({ term, value, mono = true }) {
  return (
    <div>
      <dt className="text-fg-muted">{term}</dt>
      <dd className={cn('text-fg', mono && 'font-mono')}>{value}</dd>
    </div>
  );
}
