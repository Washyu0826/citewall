import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Loader2, RefreshCw, ScrollText, ShieldAlert, ShieldCheck, X } from 'lucide-react';

import { useAuditRecent, useAuditVerify } from '../api/queries.js';
import { cn } from '../lib/utils';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card } from './ui/card.jsx';
import { Page, PageHeader, Stat } from './ui/page.jsx';
import EmptyState from './EmptyState.jsx';
import ErrorBanner from './ErrorBanner.jsx';
import { Skeleton } from './Skeleton.jsx';

// Gate outcomes recorded per request. For *_passed a true value is the good
// outcome; cache_hit / circuit_open are informational (true = notable).
const POLICY_KEYS = ['authz_passed', 'rate_limit_passed', 'quota_passed', 'cache_hit', 'circuit_open'];
const INFORMATIONAL = new Set(['cache_hit', 'circuit_open']);

/**
 * Append-only audit log + tamper-evident hash chain.
 *
 * Auditors verify the global (cross-tenant) chain; IT admins their own
 * tenant's. Each row shows who called what, the masking rules that fired
 * before anything reached a model, and every gate decision — so the log
 * itself is the evidence that redaction and access control ran.
 */
export default function AuditView({ session, onLogout }) {
  const { t } = useTranslation();
  const scope = session?.role === 'auditor' ? 'global' : 'tenant';

  // The verify query shares its key with the shell's chain chip, so the two
  // never issue duplicate verify requests.
  const recentQ = useAuditRecent(session.token);
  const verifyQ = useAuditVerify(session.token, scope, { poll: false });
  const [dismissed, setDismissed] = useState(false);

  const rows = recentQ.data ?? [];
  const verify = verifyQ.data ?? null;
  const verifying = verifyQ.isFetching;
  const error = dismissed ? null : recentQ.error || verifyQ.error || null;

  const summary = useMemo(() => {
    const verified = verify?.verified ?? 0;
    const broken = Array.isArray(verify?.broken) ? verify.broken.length : 0;
    return {
      totalRows: verified + broken,
      mismatches: broken,
      lastVerified: verifyQ.dataUpdatedAt ? new Date(verifyQ.dataUpdatedAt) : null,
      allPass: broken === 0,
    };
  }, [verify, verifyQ.dataUpdatedAt]);

  function refresh() {
    setDismissed(false);
    recentQ.refetch();
  }
  function runVerify() {
    setDismissed(false);
    verifyQ.refetch();
  }

  return (
    <Page>
      <PageHeader
        title={t('audit_page.title')}
        description={t('audit_page.desc')}
        actions={
          <>
            <Button variant="outline" onClick={refresh}>
              <RefreshCw className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
              {t('audit_table.refresh')}
            </Button>
            <Button onClick={runVerify} disabled={verifying} data-testid="audit-verify-now">
              {verifying ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ShieldCheck className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
              )}
              {verifying ? t('audit.verifying') : t('audit.verify_now')}
            </Button>
          </>
        }
      />

      <section aria-label={t('audit_page.summary')} className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat
          label={t('audit.hero.rows_label')}
          value={summary.totalRows.toLocaleString()}
          hint={t(scope === 'global' ? 'audit_page.scope_global' : 'audit_page.scope_tenant')}
        />
        <Stat
          label={t('audit.hero.mismatches_label')}
          value={summary.mismatches.toLocaleString()}
          tone={verify ? (summary.allPass ? 'success' : 'danger') : 'neutral'}
        />
        <Stat
          label={t('audit.hero.last_verified_label')}
          value={
            <span className="font-mono text-lg">
              {summary.lastVerified ? formatUtc(summary.lastVerified.toISOString()) : t('audit.hero.never_verified')}
            </span>
          }
          hint={summary.lastVerified ? 'UTC' : undefined}
        />
      </section>

      {verify && (
        <div
          className={cn(
            'mb-4 flex items-start gap-2 rounded-brand border px-4 py-3 text-sm',
            summary.allPass
              ? 'border-success/40 bg-success-soft text-success'
              : 'border-danger/40 bg-danger-soft text-danger'
          )}
        >
          {summary.allPass ? (
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
          )}
          <span>
            {summary.allPass
              ? t('audit.verify_passed', { rows: summary.totalRows })
              : t('audit.verify_failed', { count: summary.mismatches, rows: brokenRowsLabel(verify.broken) })}
          </span>
        </div>
      )}

      {error && (
        <div className="mb-4">
          <ErrorBanner error={error} onRetry={refresh} onDismiss={() => setDismissed(true)} onLogin={onLogout} />
        </div>
      )}

      <Card className="overflow-hidden">
        {recentQ.isPending ? (
          <div className="space-y-3 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            bare
            icon={<ScrollText className="mx-auto h-9 w-9 text-fg-muted" strokeWidth={1.5} aria-hidden="true" />}
            title={t('empty.no_audit_title')}
            description={t('empty.no_audit_desc')}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" aria-label={t('audit_page.title')}>
              <thead className="whitespace-nowrap border-b border-line bg-surface-sunken text-xs font-medium text-fg-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.time')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.user')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.case')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.endpoint')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.model')}</th>
                  <th scope="col" className="px-4 py-2.5 text-right">{t('audit_page.col.tokens')}</th>
                  <th scope="col" className="px-4 py-2.5 text-right">{t('audit_page.col.latency')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.masking')}</th>
                  <th scope="col" className="px-4 py-2.5">{t('audit_page.col.gates')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-subtle">
                {rows.map((r) => (
                  <tr key={r.audit_id} className="align-top hover:bg-surface-hover">
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-fg-secondary">
                      <time dateTime={r.timestamp_utc}>{formatUtc(r.timestamp_utc)}</time>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-fg">{r.user_id}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-fg">{r.case_id || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-fg">{r.endpoint}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-fg-secondary">{r.model_used || '—'}</td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-secondary">
                      {((r.prompt_tokens || 0) + (r.completion_tokens || 0)).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-secondary">{r.latency_ms}</td>
                    <td className="px-4 py-3">
                      {(r.masked_field_rules || []).length === 0 ? (
                        <span className="text-fg-muted">—</span>
                      ) : (
                        <div className="flex max-w-56 flex-wrap gap-1">
                          {r.masked_field_rules.map((m, i) => (
                            <Badge key={i} tone="warning" size="sm" className="font-mono">
                              {m}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <PolicyChips decisions={r.policy_decisions} t={t} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Page>
  );
}

/** One chip per gate decision: localized name + ✓/✗, raw key=value on hover. */
function PolicyChips({ decisions, t }) {
  const entries = Object.entries(decisions || {}).sort(
    ([a], [b]) => rank(a) - rank(b) || a.localeCompare(b)
  );
  if (entries.length === 0) return <span className="text-fg-muted">—</span>;
  return (
    <div className="flex min-w-56 max-w-72 flex-wrap gap-1">
      {entries.map(([k, v]) => {
        const info = INFORMATIONAL.has(k);
        const tone = info ? (v ? 'warning' : 'neutral') : v ? 'success' : 'error';
        const Icon = v ? Check : X;
        return (
          <Badge key={k} tone={tone} size="sm" title={`${k}=${v}`}>
            {t(`audit_page.gate.${k}`, { defaultValue: k })}
            <Icon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
            <span className="sr-only">{v ? t('audit_page.yes') : t('audit_page.no')}</span>
          </Badge>
        );
      })}
    </div>
  );
}

function rank(key) {
  const i = POLICY_KEYS.indexOf(key);
  return i === -1 ? POLICY_KEYS.length : i;
}

/** "2025-04-15T10:30:00.123Z" → "2025-04-15 10:30:00" (the log is in UTC). */
function formatUtc(iso) {
  return typeof iso === 'string' ? iso.replace('T', ' ').slice(0, 19) : '';
}

function brokenRowsLabel(broken) {
  if (!Array.isArray(broken)) return '';
  // verify_global_chain → list[tuple[tenant_id, audit_id]]; per-tenant → list[str]
  return broken
    .slice(0, 5)
    .map((b) => (Array.isArray(b) ? b[1] : b))
    .join(', ');
}
