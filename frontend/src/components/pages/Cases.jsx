import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowRight, FolderOpen, Search } from 'lucide-react';

import { useCases } from '../../api/queries.js';
import { useCurrentCase } from '../../lib/currentCase.jsx';
import { CASE_FILTERS, filterCases, formatDate } from '../../lib/cases.js';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button.jsx';
import { Card } from '../ui/card.jsx';
import { Input } from '../ui/field.jsx';
import { Page, PageHeader } from '../ui/page.jsx';
import EmptyState from '../EmptyState.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { Skeleton } from '../Skeleton.jsx';
import { DeadlineCell, RejectionBadges, SecurityBadge, StatusBadge } from '../cases/CaseBits.jsx';

/**
 * Case list. Opening a case sets the in-memory current case and goes to the
 * workspace — the case id never enters the URL (CLAUDE.md §9). Auditors get a
 * read-only view (no "open in workspace").
 */
export default function Cases({ session }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { setCaseId } = useCurrentCase();
  const casesQ = useCases(session.token);
  const readOnly = casesQ.data?.read_only ?? session.role === 'auditor';
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');

  const rows = useMemo(
    () => filterCases(casesQ.data?.cases ?? [], { query, filter }),
    [casesQ.data, query, filter]
  );

  const openCase = (caseId) => {
    setCaseId(caseId);
    navigate('/analyze');
  };

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

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
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
        <div role="group" aria-label={t('cases_page.title')} className="flex flex-wrap gap-1">
          {CASE_FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                'h-9 rounded-brand px-3 text-sm font-medium transition-colors',
                filter === f
                  ? 'bg-primary text-white'
                  : 'border border-line-strong bg-surface-raised text-fg-secondary hover:bg-surface-hover'
              )}
            >
              {t(`cases_page.filters.${f}`)}
            </button>
          ))}
        </div>
        <p className="ml-auto text-sm text-fg-muted" aria-live="polite">
          {t('cases_page.count', { count: rows.length })}
        </p>
      </div>

      <Card className="overflow-hidden">
        {casesQ.isLoading ? (
          <div className="space-y-3 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            bare
            icon={<FolderOpen className="mx-auto h-9 w-9 text-fg-muted" strokeWidth={1.5} aria-hidden="true" />}
            title={t('cases_page.empty')}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="cases-table">
              <thead className="border-b border-line bg-surface-sunken text-xs font-medium text-fg-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.case')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.security')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.rejections')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.deadline')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.status')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('cases_page.columns.last_analysis')}</th>
                  {!readOnly && (
                    <th scope="col" className="px-4 py-2.5">
                      <span className="sr-only">{t('cases_page.columns.actions')}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-line-subtle">
                {rows.map((c) => {
                  const a = c.last_analysis;
                  return (
                    <tr key={c.case_id} className="hover:bg-surface-hover">
                      <th scope="row" className="whitespace-nowrap px-4 py-3 text-left font-normal">
                        <span className="font-mono font-medium text-fg">{c.case_id}</span>
                        {a?.jurisdiction && (
                          <span className="block text-xs text-fg-muted">
                            {t(`jurisdiction.${a.jurisdiction}`, { defaultValue: a.jurisdiction })}
                            {a.target_patent_no ? ` · ${a.target_patent_no}` : ''}
                          </span>
                        )}
                      </th>
                      <td className="px-4 py-3">
                        <SecurityBadge level={c.security_level} size="sm" />
                      </td>
                      <td className="px-4 py-3">
                        <RejectionBadges types={a?.rejection_types} />
                      </td>
                      <td className="px-4 py-3">
                        <DeadlineCell iso={a?.statutory_deadline} />
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge row={c} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-fg-secondary">
                        {a ? (
                          <>
                            <time dateTime={a.analyzed_at} className="font-mono">
                              {formatDate(a.analyzed_at, i18n.language)}
                            </time>
                            <span className="block text-xs text-fg-muted">{a.analyzed_by}</span>
                          </>
                        ) : (
                          <span className="text-fg-muted">—</span>
                        )}
                      </td>
                      {!readOnly && (
                        <td className="px-4 py-3 text-right">
                          <Button variant="outline" size="sm" onClick={() => openCase(c.case_id)}>
                            {t('cases_page.open_analysis')}
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
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
      </Card>
    </Page>
  );
}
