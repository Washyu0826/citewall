import { useTranslation } from 'react-i18next';
import { AlertTriangle, EyeOff, FileCheck2, Gauge, Play } from 'lucide-react';

import OAUpload from '../OAUpload.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { SkeletonText } from '../Skeleton.jsx';
import { Button } from '../ui/button.jsx';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card.jsx';
import { Field, Input, Select, Textarea } from '../ui/field.jsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs.jsx';
import { SecurityBadge } from '../cases/CaseBits.jsx';
import { DOMICILE_OPTIONS } from '../../lib/deadlineInputs.js';

/**
 * Step 1–2 of the workspace: which case, the office action (upload or paste),
 * optional deadline facts, and the masking preview before anything is sent.
 * All state lives in <Analyze>; this is presentational.
 */
export default function SetupPanel({
  caseId,
  cases,
  onChangeCase,
  targetPatent,
  setTargetPatent,
  domicile,
  setDomicile,
  oaSequence,
  setOaSequence,
  serviceDate,
  setServiceDate,
  oaText,
  setOaText,
  sourceTab,
  setSourceTab,
  loadedMeta,
  uploadWarnings,
  onExtractSuccess,
  session,
  onPreviewRedaction,
  previewing,
  onAnalyze,
  running,
  error,
  setError,
  onLogout,
  redactPreview,
  quota,
}) {
  const { t } = useTranslation();
  const row = cases?.find((c) => c.case_id === caseId);
  const caseOptions = cases?.length ? cases : caseId ? [{ case_id: caseId }] : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>{t('workspace.oa_card')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs value={sourceTab} onValueChange={setSourceTab}>
              <TabsList>
                <TabsTrigger value="upload">{t('workspace.tab_upload')}</TabsTrigger>
                <TabsTrigger value="paste">{t('workspace.tab_paste')}</TabsTrigger>
              </TabsList>
              <TabsContent value="upload" className="pt-4">
                <OAUpload
                  caseId={caseId}
                  token={session.token}
                  onExtractSuccess={onExtractSuccess}
                  onError={(err) => setError(err?.message ? err : new Error(String(err)))}
                />
              </TabsContent>
              <TabsContent value="paste" className="pt-4">
                <Field label={t('workspace.oa_text')}>
                  <Textarea
                    id="analyze-oa-text"
                    value={oaText}
                    onChange={(e) => setOaText(e.target.value)}
                    rows={14}
                    className="font-mono text-sm leading-6"
                  />
                </Field>
              </TabsContent>
            </Tabs>

            {loadedMeta && (
              <p className="flex items-center gap-2 text-sm text-success">
                <FileCheck2 className="h-4 w-4" aria-hidden="true" />
                {t('upload.loaded_chip', { filename: loadedMeta.fileName, pages: loadedMeta.pages ?? 0 })}
              </p>
            )}
            {uploadWarnings.length > 0 && (
              <ul className="space-y-1">
                {uploadWarnings.map((w, i) => (
                  <li key={i} className="flex items-start gap-2 rounded-brand bg-warning-soft px-3 py-2 text-sm text-warning">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {w}
                  </li>
                ))}
              </ul>
            )}

            <div className="flex flex-col gap-3 border-t border-line-subtle pt-4 sm:flex-row sm:items-center">
              <p className="text-sm text-fg-muted sm:mr-auto">{t('workspace.actions_hint')}</p>
              <Button variant="outline" onClick={onPreviewRedaction} disabled={previewing || !oaText.trim()}>
                <EyeOff className="h-4 w-4" aria-hidden="true" />
                {t('analyze.input.preview_redaction')}
              </Button>
              <Button onClick={onAnalyze} disabled={running || !oaText.trim() || !caseId} data-testid="analyze-submit">
                <Play className="h-4 w-4" aria-hidden="true" />
                {running ? t('analyze.input.analyzing') : t('analyze.input.analyze_oa')}
              </Button>
            </div>
            {error && <ErrorBanner error={error} onRetry={onAnalyze} onDismiss={() => setError(null)} onLogin={onLogout} />}
          </CardContent>
        </Card>

        {redactPreview && (
          <Card data-testid="redaction-preview">
            <CardHeader>
              <div>
                <CardTitle>{t('workspace.redaction_title')}</CardTitle>
                <p className="mt-0.5 text-sm text-fg-muted">{t('workspace.redaction_desc')}</p>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-brand border border-line bg-surface-sunken p-3 font-mono text-sm leading-6 text-fg">
                {redactPreview.redacted}
              </pre>
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-fg-muted">{t('workspace.redaction_rules')}</span>
                {redactPreview.rules_triggered.length === 0 && <span className="text-fg-muted">—</span>}
                {redactPreview.rules_triggered.map((r) => (
                  <span key={r} className="rounded bg-warning-soft px-1.5 py-0.5 font-mono text-xs text-warning">
                    {r}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      <aside className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>{t('workspace.case_card')}</CardTitle>
            {caseId && <SecurityBadge level={row?.security_level} size="sm" />}
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label={t('workspace.case_label')} hint={!caseId ? t('workspace.no_case') : undefined}>
              <Select id="analyze-case-id" value={caseId} onChange={(e) => onChangeCase(e.target.value)}>
                {!caseId && <option value="">{t('case_switcher.none')}</option>}
                {caseOptions.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.case_id}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('workspace.target_patent')}>
              <Input
                id="analyze-target-patent"
                value={targetPatent}
                onChange={(e) => setTargetPatent(e.target.value)}
                className="font-mono"
              />
            </Field>
          </CardContent>
        </Card>

        <Card data-testid="deadline-inputs">
          <CardHeader>
            <CardTitle>{t('workspace.deadline_card')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label={t('deadline_input.domicile')}>
              <Select id="analyze-applicant-domicile" value={domicile} onChange={(e) => setDomicile(e.target.value)}>
                {DOMICILE_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {t(`deadline_input.domicile_${opt}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('deadline_input.oa_sequence')}>
                <Input
                  id="analyze-oa-sequence"
                  type="number"
                  min={1}
                  max={50}
                  step={1}
                  inputMode="numeric"
                  value={oaSequence}
                  onChange={(e) => setOaSequence(e.target.value)}
                />
              </Field>
              <Field label={t('deadline_input.service_date')}>
                <Input id="analyze-service-date" type="date" value={serviceDate} onChange={(e) => setServiceDate(e.target.value)} />
              </Field>
            </div>
            <p className="text-sm text-fg-muted">{t('deadline_input.hint')}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-fg-muted" aria-hidden="true" />
              {t('analyze.input.quota')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!quota ? (
              <SkeletonText lines={3} />
            ) : (
              <>
                <UsageBar label={t('analyze.input.token_today')} used={quota.user_daily_used} total={quota.user_daily_limit} />
                <UsageBar label={t('analyze.input.token_month')} used={quota.tenant_monthly_used} total={quota.tenant_monthly_cap} />
                <p className="text-sm text-fg-muted">
                  {t('analyze.input.cost_breaker')}：${quota.circuit_breaker.current_usd} / ${quota.circuit_breaker.threshold_usd}
                  {quota.circuit_breaker.tripped && (
                    <span className="ml-2 font-medium text-danger">{t('analyze.input.cost_breaker_tripped')}</span>
                  )}
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}

function UsageBar({ label, used, total }) {
  const pct = total ? Math.min(100, (used / total) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span className="text-fg-secondary">{label}</span>
        <span className="font-mono text-fg-muted">
          {used.toLocaleString()} / {total.toLocaleString()}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true">
        <div className={pct > 80 ? 'h-full bg-rose-600' : 'h-full bg-brand-fg'} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
