import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileSearch } from 'lucide-react';

import { useCases } from '../../api/queries.js';
import { useCurrentCase } from '../../lib/currentCase.jsx';
import { caseStatus, dashboardStats, upcomingDeadlines } from '../../lib/cases.js';
import { Button } from '../ui/button.jsx';
import { KeyFigures, Page, PageHeader, Section } from '../ui/page.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { Skeleton } from '../Skeleton.jsx';
import { DateText, DaysLeftText, RejectionText, SecurityText } from '../cases/CaseBits.jsx';

/**
 * Attorney / paralegal home, written like a register rather than a dashboard:
 * the key figures in one ruled line, then what is due and what has not been
 * analysed yet, as ruled tables.
 */
export default function Home({ session }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { setCaseId } = useCurrentCase();
  const casesQ = useCases(session.token);
  const cases = useMemo(() => casesQ.data?.cases ?? [], [casesQ.data]);
  const stats = useMemo(() => dashboardStats(cases), [cases]);
  const upcoming = useMemo(() => upcomingDeadlines(cases).slice(0, 8), [cases]);
  const pending = useMemo(() => cases.filter((c) => caseStatus(c) === 'not_analyzed'), [cases]);
  const loading = casesQ.isLoading;
  const figure = (n) => (loading ? '—' : n);

  const openCase = (caseId) => {
    setCaseId(caseId);
    navigate('/analyze');
  };

  return (
    <Page>
      <PageHeader
        title={t('home.title')}
        description={t('home.subtitle')}
        actions={
          <Button onClick={() => navigate('/analyze')} data-testid="home-new-analysis">
            <FileSearch className="h-4 w-4" aria-hidden="true" />
            {t('home.new_analysis')}
          </Button>
        }
      />

      {casesQ.error && (
        <div className="mb-6">
          <ErrorBanner error={casesQ.error} onRetry={() => casesQ.refetch()} />
        </div>
      )}

      <KeyFigures
        label={t('home.figures_label')}
        items={[
          { label: t('home.stats.total'), value: figure(stats.total) },
          { label: t('home.stats.due_soon'), value: figure(stats.dueSoon), tone: stats.dueSoon ? 'warning' : undefined },
          { label: t('home.stats.overdue'), value: figure(stats.overdue), tone: stats.overdue ? 'danger' : undefined },
          { label: t('home.stats.not_analyzed'), value: figure(stats.notAnalyzed) },
          { label: t('home.stats.confidential'), value: figure(stats.confidential) },
        ]}
      />

      <Section id="home-due" title={t('home.deadlines_title')} description={t('home.deadlines_hint')}>
        {loading ? (
          <LoadingRows />
        ) : upcoming.length === 0 ? (
          <p className="border-t-2 border-fg py-4 text-fg-muted">{t('home.deadlines_empty')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="doc-table" data-testid="home-deadlines">
              <thead>
                <tr>
                  <th scope="col">{t('cases_page.columns.case')}</th>
                  <th scope="col">{t('cases_page.columns.jurisdiction')}</th>
                  <th scope="col">{t('cases_page.columns.rejections')}</th>
                  <th scope="col">{t('cases_page.columns.deadline')}</th>
                  <th scope="col">{t('home.remaining')}</th>
                  <th scope="col">
                    <span className="sr-only">{t('cases_page.columns.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {upcoming.map((c) => (
                  <tr key={c.case_id}>
                    <th scope="row" className="whitespace-nowrap font-mono">
                      {c.case_id}
                    </th>
                    <td className="whitespace-nowrap">
                      {t(`jurisdiction.${c.last_analysis.jurisdiction}`, {
                        defaultValue: c.last_analysis.jurisdiction || '—',
                      })}
                    </td>
                    <td>
                      <RejectionText types={c.last_analysis.rejection_types} />
                    </td>
                    <td>
                      <DateText iso={c.last_analysis.statutory_deadline} />
                    </td>
                    <td>
                      <DaysLeftText iso={c.last_analysis.statutory_deadline} />
                    </td>
                    <td className="text-right">
                      <Button variant="link" size="sm" className="h-auto px-0" onClick={() => openCase(c.case_id)}>
                        {t('home.open')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="home-pending" title={t('home.pending_title')}>
        {loading ? (
          <LoadingRows />
        ) : pending.length === 0 ? (
          <p className="border-t-2 border-fg py-4 text-fg-muted">{t('home.pending_empty')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="doc-table">
              <thead>
                <tr>
                  <th scope="col">{t('cases_page.columns.case')}</th>
                  <th scope="col">{t('cases_page.columns.security')}</th>
                  <th scope="col">
                    <span className="sr-only">{t('cases_page.columns.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pending.map((c) => (
                  <tr key={c.case_id}>
                    <th scope="row" className="whitespace-nowrap font-mono">
                      {c.case_id}
                    </th>
                    <td className="w-full">
                      <SecurityText level={c.security_level} />
                    </td>
                    <td className="text-right">
                      <Button variant="link" size="sm" className="h-auto px-0" onClick={() => openCase(c.case_id)}>
                        {t('home.analyze')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </Page>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-3 border-t-2 border-fg pt-4">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}
