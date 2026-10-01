import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Loader2, RefreshCw, ShieldAlert, ShieldCheck, X } from 'lucide-react';

import { useAuditRecent, useAuditVerify } from '../api/queries.js';
import { cn } from '../lib/utils';
import { Button } from './ui/button.jsx';
import { KeyFigures, Page, PageHeader, Section } from './ui/page.jsx';
import ErrorBanner from './ErrorBanner.jsx';
import { Skeleton } from './Skeleton.jsx';

// Gate outcomes recorded per request. For *_passed a true value is the good
// outcome; cache_hit / circuit_open are informational and only worth a word
// when they happened.
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

      <KeyFigures
        label={t('audit_page.summary')}
        className="mb-6"
        items={[
          {
            label: t('audit.hero.rows_label'),
            value: summary.totalRows.toLocaleString(),
            hint: t(scope === 'global' ? 'audit_page.scope_global' : 'audit_page.scope_tenant'),
          },
          {
            label: t('audit.hero.mismatches_label'),
            value: summary.mismatches.toLocaleString(),
            tone: verify ? (summary.allPass ? 'success' : 'danger') : undefined,
          },
          {
            label: t('audit.hero.last_verified_label'),
            value: (
              <span className="font-mono text-xl">
                {summary.lastVerified ? formatUtc(summary.lastVerified.toISOString()) : t('audit.hero.never_verified')}
              </span>
            ),
            hint: summary.lastVerified ? 'UTC' : undefined,
          },
        ]}
      />

      {verify && (
        <div
          className={cn(
            'mb-8 flex items-start gap-2 border-l-4 py-2 pl-4 text-base',
            summary.allPass ? 'border-success text-success' : 'border-danger font-semibold text-danger'
          )}
        >
          {summary.allPass ? (
            <ShieldCheck className="mt-1 h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <ShieldAlert className="mt-1 h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
          )}
          <span>
            {summary.allPass
              ? t('audit.verify_passed', { rows: summary.totalRows })
              : t('audit.verify_failed', { count: summary.mismatches, rows: brokenRowsLabel(verify.broken) })}
          </span>
        </div>
      )}

      {error && (
        <div className="mb-6">
          <ErrorBanner error={error} onRetry={refresh} onDismiss={() => setDismissed(true)} onLogin={onLogout} />
        </div>
      )}

      <Section id="audit-records" title={t('audit_page.records')}>
        {recentQ.isPending ? (
          <div className="space-y-3 border-t-2 border-fg pt-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="border-t-2 border-fg py-6">
            <p className="font-medium text-fg">{t('empty.no_audit_title')}</p>
            <p className="mt-1 text-sm text-fg-muted">{t('empty.no_audit_desc')}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="doc-table" aria-label={t('audit_page.title')}>
              <thead>
                <tr>
                  <th scope="col">{t('audit_page.col.time')}</th>
                  <th scope="col">{t('audit_page.col.user')}</th>
                  <th scope="col">{t('audit_page.col.case')}</th>
                  <th scope="col">{t('audit_page.col.endpoint')}</th>
                  <th scope="col">{t('audit_page.col.model')}</th>
                  <th scope="col" className="text-right">{t('audit_page.col.tokens')}</th>
                  <th scope="col" className="text-right">{t('audit_page.col.latency')}</th>
                  <th scope="col">{t('audit_page.col.masking')}</th>
                  <th scope="col">{t('audit_page.col.gates')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.audit_id}>
                    <td className="whitespace-nowrap font-mono text-fg-secondary">
                      <time dateTime={r.timestamp_utc}>{formatUtc(r.timestamp_utc)}</time>
                    </td>
                    <td className="whitespace-nowrap">{r.user_id}</td>
                    <td className="whitespace-nowrap font-mono">{r.case_id || '—'}</td>
                    <td className="whitespace-nowrap font-mono">{r.endpoint}</td>
                    <td className="whitespace-nowrap font-mono text-fg-secondary">{r.model_used || '—'}</td>
                    <td className="text-right font-mono tabular-nums text-fg-secondary">
                      {((r.prompt_tokens || 0) + (r.completion_tokens || 0)).toLocaleString()}
                    </td>
                    <td className="text-right font-mono tabular-nums text-fg-secondary">{r.latency_ms}</td>
                    <td>
                      <MaskingRules rules={r.masked_field_rules} />
                    </td>
                    <td>
                      <GateDecisions decisions={r.policy_decisions} t={t} />
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

/** "CASE_REF, EMAIL, PHONE" — rule names as text, one span each. */
function MaskingRules({ rules }) {
  if (!rules?.length) return <span className="text-fg-muted">—</span>;
  return (
    <span className="flex max-w-56 flex-wrap gap-x-1.5 font-mono text-xs leading-6 text-warning">
      {rules.map((m, i) => (
        <span key={i}>
          <span>{m}</span>
          {i < rules.length - 1 && <span className="text-fg-muted">,</span>}
        </span>
      ))}
    </span>
  );
}

/**
 * Gate decisions in words: "權限 ✓ 頻率限制 ✓ 配額 ✓". A failed gate is the
 * only thing in red; cache hit / open breaker appear only when they happened.
 * The raw key=value stays on hover for auditors.
 */
function GateDecisions({ decisions, t }) {
  const entries = Object.entries(decisions || {})
    .filter(([k, v]) => !INFORMATIONAL.has(k) || v)
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  if (entries.length === 0) return <span className="text-fg-muted">—</span>;
  return (
    <span className="flex min-w-40 max-w-64 flex-wrap gap-x-3 gap-y-0.5 text-sm">
      {entries.map(([k, v]) => {
        const info = INFORMATIONAL.has(k);
        const failed = !info && !v;
        const Icon = v ? Check : X;
        return (
          <span
            key={k}
            title={`${k}=${v}`}
            className={cn(
              'inline-flex items-center gap-0.5 whitespace-nowrap',
              failed ? 'font-semibold text-danger' : info ? 'text-warning' : 'text-fg-secondary'
            )}
          >
            {t(`audit_page.gate.${k}`, { defaultValue: k })}
            {!info && <Icon className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />}
            {!info && <span className="sr-only">{v ? t('audit_page.yes') : t('audit_page.no')}</span>}
          </span>
        );
      })}
    </span>
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
