import { useTranslation } from 'react-i18next';
import { AlertTriangle, EyeOff, FileCheck2, Play } from 'lucide-react';

import OAUpload from '../OAUpload.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { SkeletonText } from '../Skeleton.jsx';
import { Button } from '../ui/button.jsx';
import { Field, Input, Select, Textarea } from '../ui/field.jsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs.jsx';
import { SecurityText } from '../cases/CaseBits.jsx';
import { DOMICILE_OPTIONS } from '../../lib/deadlineInputs.js';
import { cn } from '../../lib/utils';

/**
 * Step 1–2 of the workspace, laid out like a form on paper: which case, the
 * office action (upload or paste), optional deadline facts, then the actions
 * and the masking preview. Sections are separated by rules, not boxed.
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
    <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="flex min-w-0 flex-col gap-10">
        <FormSection
          title={t('workspace.case_card')}
          aside={caseId ? <SecurityText level={row?.security_level} /> : null}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('workspace.case_label')} hint={!caseId ? t('workspace.no_case') : undefined}>
              <Select id="analyze-case-id" value={caseId} onChange={(e) => onChangeCase(e.target.value)} className="font-mono">
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
          </div>
        </FormSection>

        <FormSection title={t('workspace.oa_card')}>
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
            <p className="mt-3 flex items-center gap-2 text-sm text-success">
              <FileCheck2 className="h-4 w-4" aria-hidden="true" />
              {t('upload.loaded_chip', { filename: loadedMeta.fileName, pages: loadedMeta.pages ?? 0 })}
            </p>
          )}
          {uploadWarnings.length > 0 && (
            <ul className="mt-3 space-y-1">
              {uploadWarnings.map((w, i) => (
                <li key={i} className="flex items-start gap-2 border-l-4 border-warning py-1 pl-3 text-sm text-warning">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </FormSection>

        <FormSection title={t('workspace.deadline_card')} testId="deadline-inputs" description={t('deadline_input.hint')}>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('deadline_input.domicile')}>
              <Select id="analyze-applicant-domicile" value={domicile} onChange={(e) => setDomicile(e.target.value)}>
                {DOMICILE_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {t(`deadline_input.domicile_${opt}`)}
                  </option>
                ))}
              </Select>
            </Field>
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
        </FormSection>

        <div className="flex flex-col gap-3 border-t-2 border-fg pt-5">
          <p className="text-sm text-fg-secondary">{t('workspace.actions_hint')}</p>
          <div className="flex flex-wrap gap-3">
            <Button onClick={onAnalyze} disabled={running || !oaText.trim() || !caseId} data-testid="analyze-submit" size="lg">
              <Play className="h-4 w-4" aria-hidden="true" />
              {running ? t('analyze.input.analyzing') : t('analyze.input.analyze_oa')}
            </Button>
            <Button variant="outline" size="lg" onClick={onPreviewRedaction} disabled={previewing || !oaText.trim()}>
              <EyeOff className="h-4 w-4" aria-hidden="true" />
              {t('analyze.input.preview_redaction')}
            </Button>
          </div>
          {error && <ErrorBanner error={error} onRetry={onAnalyze} onDismiss={() => setError(null)} onLogin={onLogout} />}
        </div>

        {redactPreview && (
          <FormSection testId="redaction-preview" title={t('workspace.redaction_title')} description={t('workspace.redaction_desc')}>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-l-4 border-line-strong bg-surface-sunken p-3 font-mono text-sm leading-6 text-fg">
              {redactPreview.redacted}
            </pre>
            <p className="mt-3 text-sm">
              <span className="text-fg-muted">{t('workspace.redaction_rules')}：</span>
              {redactPreview.rules_triggered.length === 0 ? (
                <span className="text-fg-muted">—</span>
              ) : (
                <span className="font-mono text-warning">{redactPreview.rules_triggered.join(', ')}</span>
              )}
            </p>
          </FormSection>
        )}
      </div>

      {/* Usage is reference information, not a task — a quiet side note. */}
      <aside className="self-start border-l-4 border-line pl-4 lg:sticky lg:top-6">
        <h2 className="text-base font-bold text-fg">{t('analyze.input.quota')}</h2>
        <div className="mt-3 space-y-3">
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
        </div>
      </aside>
    </div>
  );
}

/** A form part: heavy rule, bold heading, optional lead text. */
function FormSection({ title, description, aside, testId, children }) {
  return (
    <section data-testid={testId} className="border-t-2 border-fg pt-4">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold text-fg">{title}</h2>
        {aside}
      </div>
      {description && <p className={cn('-mt-2 mb-4 max-w-2xl text-sm text-fg-muted')}>{description}</p>}
      {children}
    </section>
  );
}

function UsageBar({ label, used, total }) {
  const pct = total ? Math.min(100, (used / total) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex flex-wrap justify-between gap-x-2 text-sm">
        <span className="text-fg-secondary">{label}</span>
        <span className="font-mono text-fg-muted">
          {used.toLocaleString()} / {total.toLocaleString()}
        </span>
      </div>
      <div className="h-1 bg-line" aria-hidden="true">
        <div className={pct > 80 ? 'h-full bg-danger' : 'h-full bg-fg-secondary'} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
