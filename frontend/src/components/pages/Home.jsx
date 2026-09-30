import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  AlarmClock,
  ArrowRight,
  CalendarClock,
  FileSearch,
  FolderOpen,
  Lock,
  ScrollText,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import { useCases } from '../../api/queries.js';
import { useCurrentCase } from '../../lib/currentCase.jsx';
import { caseStatus, dashboardStats, upcomingDeadlines } from '../../lib/cases.js';
import { Button } from '../ui/button.jsx';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card.jsx';
import { Page, PageHeader, Stat } from '../ui/page.jsx';
import EmptyState from '../EmptyState.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { SkeletonCard } from '../Skeleton.jsx';
import { DeadlineCell, RejectionBadges, SecurityBadge } from '../cases/CaseBits.jsx';

/**
 * Attorney / paralegal home: what is due, what has not been looked at, and a
 * one-line reminder of how the workspace protects client data (P1 trust-first).
 */
export default function Home({ session }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { setCaseId } = useCurrentCase();
  const casesQ = useCases(session.token);
  const cases = useMemo(() => casesQ.data?.cases ?? [], [casesQ.data]);
  const stats = useMemo(() => dashboardStats(cases), [cases]);
  const upcoming = useMemo(() => upcomingDeadlines(cases).slice(0, 6), [cases]);
  const pending = useMemo(() => cases.filter((c) => caseStatus(c) === 'not_analyzed'), [cases]);

  const openCase = (caseId) => {
    setCaseId(caseId);
    navigate('/analyze');
  };
  const firstName = (session.display_name || '').split(' (')[0];

  return (
    <Page>
      <PageHeader
        title={t('home.greeting', { name: firstName })}
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

      <section aria-label={t('home.stats.total')} className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t('home.stats.total')} value={casesQ.isLoading ? '—' : stats.total} icon={FolderOpen} />
        <Stat
          label={t('home.stats.due_soon')}
          value={casesQ.isLoading ? '—' : stats.dueSoon}
          tone={stats.dueSoon ? 'warning' : 'neutral'}
          icon={CalendarClock}
        />
        <Stat
          label={t('home.stats.overdue')}
          value={casesQ.isLoading ? '—' : stats.overdue}
          tone={stats.overdue ? 'danger' : 'neutral'}
          icon={AlarmClock}
        />
        <Stat label={t('home.stats.confidential')} value={casesQ.isLoading ? '—' : stats.confidential} icon={Lock} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t('home.deadlines_title')}</CardTitle>
              <p className="mt-0.5 text-sm text-fg-muted">{t('home.deadlines_hint')}</p>
            </div>
          </CardHeader>
          {casesQ.isLoading ? (
            <CardContent>
              <SkeletonCard className="border-0 p-0 shadow-none" />
            </CardContent>
          ) : upcoming.length === 0 ? (
            <EmptyState
              bare
              icon={<CalendarClock className="mx-auto h-9 w-9 text-fg-muted" strokeWidth={1.5} aria-hidden="true" />}
              title={t('home.deadlines_empty')}
            />
          ) : (
            <ul className="divide-y divide-line-subtle" data-testid="home-deadlines">
              {upcoming.map((c) => (
                <li key={c.case_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                  <div className="min-w-40">
                    <p className="font-mono text-sm font-medium text-fg">{c.case_id}</p>
                    <p className="text-sm text-fg-muted">
                      {t(`jurisdiction.${c.last_analysis.jurisdiction}`, {
                        defaultValue: c.last_analysis.jurisdiction || '—',
                      })}
                    </p>
                  </div>
                  <div className="min-w-0 flex-1">
                    <RejectionBadges types={c.last_analysis.rejection_types} />
                  </div>
                  <DeadlineCell iso={c.last_analysis.statutory_deadline} />
                  <Button variant="outline" size="sm" onClick={() => openCase(c.case_id)}>
                    {t('home.open')}
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>{t('home.pending_title')}</CardTitle>
            </CardHeader>
            {pending.length === 0 ? (
              <p className="px-4 py-6 text-sm text-fg-muted">
                {casesQ.isLoading ? '…' : t('home.pending_empty')}
              </p>
            ) : (
              <ul className="divide-y divide-line-subtle">
                {pending.map((c) => (
                  <li key={c.case_id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-sm font-medium text-fg">{c.case_id}</span>
                      <SecurityBadge level={c.security_level} size="sm" />
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => openCase(c.case_id)}>
                      {t('home.analyze')}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t('home.protection_title')}</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3 text-sm text-fg-secondary">
                {[
                  { Icon: ShieldCheck, key: 'redaction' },
                  { Icon: Lock, key: 'routing' },
                  { Icon: Sparkles, key: 'citations' },
                  { Icon: ScrollText, key: 'audit' },
                ].map(({ Icon, key }) => (
                  <li key={key} className="flex gap-3">
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-brand-fg" strokeWidth={1.75} aria-hidden="true" />
                    <span>{t(`home.protection.${key}`)}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </Page>
  );
}
