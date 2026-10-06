import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, FileText, ShieldCheck } from 'lucide-react';

import { api, ApiError } from '../../api/client.js';
import { DOCX_MIME, buildResponsePayload, downloadBase64, exportReadiness } from '../../lib/responseExport.js';
import { toast } from '../../lib/toast.jsx';
import { Button } from '../ui/button.jsx';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card.jsx';

const ZH_NUMERALS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];

/**
 * The whole OA response as one Word file (UX_REVIEW W1/W2): every rejection's
 * reviewed sentences, accepted ones only, under the same sign-off gate as the
 * per-rejection export — every sentence decided, "I have reviewed" ticked,
 * attorney role, not a degraded result. The server re-checks all of it.
 */
export default function ResponseExportCard({
  session,
  caseId,
  rejections,
  progress,
  degraded,
  onExported,
  savedResult,
  inFlight = false,
  onExportState,
}) {
  const { t, i18n } = useTranslation();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  // The receipt lives in the workspace (research 09 FE-L1): coming back to
  // the page shows it again. A receipt that lands after this card mounted
  // (the export was started by an earlier mount) is adopted too, and an
  // export in flight anywhere disables the button — no unintended second
  // sign-off (review W2b-R2). A deliberate re-export stays possible.
  const [result, setResult] = useState(savedResult ?? null);
  useEffect(() => {
    if (savedResult) setResult(savedResult);
  }, [savedResult]);
  const isAttorney = session?.role === 'attorney';
  const { ready, pending, accepted, missing } = exportReadiness(rejections, progress);
  const zh = (i18n.language || '').startsWith('zh');

  const headingFor = (r, i) =>
    t('response_export.section_heading', {
      n: zh ? (ZH_NUMERALS[i] ?? i + 1) : i + 1,
      type: t(`rejection.${r.rejection_type}`, { defaultValue: r.rejection_type }),
      claims: r.affected_claims.join(zh ? '、' : ', '),
    });

  let blocker = null;
  if (!isAttorney) blocker = t('response_export.attorney_only');
  else if (degraded) blocker = t('response_export.degraded');
  else if (missing > 0) blocker = t('response_export.waiting');
  else if (pending > 0) blocker = t('response_export.pending', { count: pending });
  else if (accepted === 0) blocker = t('response_export.nothing_accepted');

  async function doExport() {
    if (!ready || !confirmed || !isAttorney || degraded || busy || inFlight) return;
    setBusy(true);
    onExportState?.(true);
    try {
      const res = await api.exportResponse(
        session.token,
        buildResponsePayload({ caseId, title: t('response_export.doc_title'), rejections, progress, headingFor })
      );
      setResult(res);
      downloadBase64(res.docx_base64, res.filename, DOCX_MIME);
      toast.success(t('response_export.done'));
      onExported?.(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast.error(t('signoff.signoff_required'));
      else toast.error(`${t('response_export.failed')}: ${e.message}`);
    } finally {
      setBusy(false);
      onExportState?.(false);
    }
  }

  return (
    <Card data-testid="response-export">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-fg-muted" aria-hidden="true" />
            {t('response_export.title')}
          </CardTitle>
          <p className="mt-0.5 text-sm text-fg-muted">{t('response_export.desc')}</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isAttorney && (
          <label className="flex items-start gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              disabled={!ready}
              className="mt-0.5 h-4 w-4 rounded border-line-strong accent-navy-900"
              data-testid="response-export-confirm"
            />
            <span>{t('response_export.confirm')}</span>
          </label>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-fg-muted" aria-live="polite">
            {blocker}
          </p>
          {isAttorney && (
            <Button onClick={doExport} disabled={!ready || !confirmed || busy || inFlight} data-testid="response-export-submit">
              <Download className="h-4 w-4" aria-hidden="true" />
              {busy || inFlight ? t('response_export.exporting') : t('response_export.export')}
            </Button>
          )}
        </div>
        {result && (
          <div className="space-y-2 rounded-brand border border-success/40 bg-success-soft p-3" data-testid="response-export-result">
            <p className="flex items-center gap-2 text-sm font-medium text-success">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              {t('response_export.done')} · {t('signoff.signed_off_by')} {result.signed_off_by}
            </p>
            <p className="break-all font-mono text-xs text-fg-muted">
              {t('response_export.hash')}: {result.content_sha256}
            </p>
            <Button
              variant="outline"
              size="xs"
              onClick={() => downloadBase64(result.docx_base64, result.filename, DOCX_MIME)}
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              {t('response_export.download_again')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
