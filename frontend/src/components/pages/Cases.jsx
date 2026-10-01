import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';

import { useCases } from '../../api/queries.js';
import { useCurrentCase } from '../../lib/currentCase.jsx';
import { CASE_FILTERS, filterCases } from '../../lib/cases.js';
import { useMediaQuery } from '../../lib/useMediaQuery.js';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button.jsx';
import { Input } from '../ui/field.jsx';
import { Page, PageHeader } from '../ui/page.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { Skeleton } from '../Skeleton.jsx';
import {
  DateText,
  DaysLeftText,
  RejectionText,
  SecurityText,
  StatusText,
} from '../cases/CaseBits.jsx';

/**
 * Case list. Opening a case sets the in-memory current case and goes to the
 * workspace — the case id never enters the URL (CLAUDE.md §9). Auditors get a
 * read-only view (no "open in workspace").
 */
export default function Cases({ session }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { setCaseId } = useCurrentCase();
  const casesQ = useCases(session.token);
  const readOnly = casesQ.data?.read_only ?? session.role === 'auditor';
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  // Phones get a stacked list (one variant only — no duplicated rows/test ids).
  const asTable = useMediaQuery('(min-width: 768px)');

  const all = useMemo(() => casesQ.data?.cases ?? [], [casesQ.data]);
  const rows = useMemo(() => filterCases(all, { query, filter }), [all, query, filter]);
  const counts = useMemo(
    () => Object.fromEntries(CASE_FILTERS.map((f) => [f, filterCases(all, { query, filter: f }).length])),
    [all, query]
  );

  const openCase = (caseId) => {
    setCaseId(caseId);
    navigate('/analyze');
  };
  const jurisdictionOf = (a) =>
    a?.jurisdiction ? t(`jurisdiction.${a.jurisdiction}`, { defaultValue: a.jurisdiction }) : null;

  return (
    <Page>
      <PageHeader
        title={t('cases_page.title')}
        description={readOnly ? t('cases_page.subtitle_readonly') : t('cases_page.subtitle')}
      />

      {casesQ.error && (
        <div className="mb-4">
          <ErrorBanner error={casesQ.error} onRetry={() => casesQ.refetch()} />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        {/* Filters as a sub-navigation with counts (one is always selected). */}
        <div role="group" aria-label={t('cases_page.filter_label')} className="flex flex-wrap gap-x-5 gap-y-2">
          {CASE_FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                'border-b-4 pb-1 text-base transition-colors',
                filter === f
                  ? 'border-accent font-bold text-fg'
                  : 'border-transparent text-fg-link underline underline-offset-4 hover:decoration-2'
              )}
            >
              {t(`cases_page.filters.${f}`)}
              <span className="ml-1 tabular-nums text-fg-muted">({counts[f]})</span>
            </button>
          ))}
        </div>
        <div className="relative w-full sm:max-w-xs">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('cases_page.search')}
            aria-label={t('cases_page.search')}
            className="pl-9"
            data-testid="cases-search"
          />
        </div>
      </div>

      <p className="sr-only" aria-live="polite">
        {t('cases_page.count', { count: rows.length })}
      </p>

      {casesQ.isLoading ? (
        <div className="space-y-3 border-t-2 border-fg pt-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="border-t-2 border-fg py-6 text-fg-muted">{t('cases_page.empty')}</p>
      ) : !asTable ? (
        <ul className="border-t-2 border-fg" data-testid="cases-list">
          {rows.map((c) => {
            const a = c.last_analysis;
            const where = [jurisdictionOf(a), a?.target_patent_no].filter(Boolean).join(' · ');
            return (
              <li key={c.case_id} className="flex flex-col gap-1.5 border-b border-line py-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="break-all font-mono font-semibold text-fg">{c.case_id}</span>
                  <SecurityText level={c.security_level} />
                </div>
                {where && <p className="text-sm text-fg-secondary">{where}</p>}
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  <dt className="text-fg-muted">{t('cases_page.columns.rejections')}</dt>
                  <dd>
                    <RejectionText types={a?.rejection_types} />
                  </dd>
                  <dt className="text-fg-muted">{t('cases_page.columns.deadline')}</dt>
                  <dd className="flex flex-wrap gap-x-3">
                    <DateText iso={a?.statutory_deadline} />
                    {a?.statutory_deadline && <DaysLeftText iso={a.statutory_deadline} />}
                  </dd>
                  <dt className="text-fg-muted">{t('cases_page.columns.status')}</dt>
                  <dd>
                    <StatusText row={c} />
                  </dd>
                </dl>
                {!readOnly && (
                  <Button variant="link" size="sm" className="h-auto self-start px-0" onClick={() => openCase(c.case_id)}>
                    {t('cases_page.open_analysis')}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="overflow-x-auto">
          <table className="doc-table" data-testid="cases-table">
            <thead>
              <tr>
                <th scope="col">{t('cases_page.columns.case')}</th>
                <th scope="col">{t('cases_page.columns.security')}</th>
                <th scope="col">{t('cases_page.columns.rejections')}</th>
                <th scope="col">{t('cases_page.columns.deadline')}</th>
                <th scope="col">{t('home.remaining')}</th>
                <th scope="col">{t('cases_page.columns.status')}</th>
                <th scope="col">{t('cases_page.columns.last_analysis')}</th>
                {!readOnly && (
                  <th scope="col">
                    <span className="sr-only">{t('cases_page.columns.actions')}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const a = c.last_analysis;
                const where = [jurisdictionOf(a), a?.target_patent_no].filter(Boolean).join(' · ');
                return (
                  <tr key={c.case_id}>
                    <th scope="row" className="whitespace-nowrap">
                      <span className="font-mono font-semibold text-fg">{c.case_id}</span>
                      {where && <span className="block text-xs font-normal text-fg-muted">{where}</span>}
                    </th>
                    <td>
                      <SecurityText level={c.security_level} />
                    </td>
                    <td>
                      <RejectionText types={a?.rejection_types} />
                    </td>
                    <td>
                      <DateText iso={a?.statutory_deadline} />
                    </td>
                    <td>
                      <DaysLeftText iso={a?.statutory_deadline} />
                    </td>
                    <td>
                      <StatusText row={c} />
                    </td>
                    <td className="whitespace-nowrap text-fg-secondary">
                      {a ? (
                        <>
                          <DateText iso={a.analyzed_at} />
                          <span className="block text-xs text-fg-muted">{a.analyzed_by}</span>
                        </>
                      ) : (
                        <span className="text-fg-muted">—</span>
                      )}
                    </td>
                    {!readOnly && (
                      <td className="text-right">
                        <Button
                          variant="link"
                          size="sm"
                          className="h-auto whitespace-nowrap px-0"
                          onClick={() => openCase(c.case_id)}
                        >
                          {t('cases_page.open_analysis')}
                        </Button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}
