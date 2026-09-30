import { useTranslation } from 'react-i18next';
import { AlertTriangle, BookOpen, ShieldAlert, ShieldCheck } from 'lucide-react';

import DraftEditor, { CitationText } from '../DraftEditor.jsx';
import ConfidencePips from '../ui/ConfidencePips.jsx';
import { Badge } from '../ui/badge.jsx';
import { Button } from '../ui/button.jsx';
import { Card, CardContent, CardHeader } from '../ui/card.jsx';
import { cn } from '../../lib/utils';
import ElementTable from './ElementTable.jsx';

/**
 * One rejection: the examiner's argument, the citation-wall result, the
 * claim-element comparison, the strategy and the sentence-by-sentence review.
 */
export default function RejectionReview({
  rejection,
  draft,
  citationLookup,
  elementTables,
  caseId,
  session,
  onCitationClick,
  degraded,
  onProgress,
  onShowReferences,
}) {
  const { t } = useTranslation();
  // Export (sign-off) is an ATTORNEY act — the backend 403s a paralegal.
  const canExport = session?.role === 'attorney';

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-fg">
            {t(`rejection.${rejection.rejection_type}`, { defaultValue: rejection.rejection_type })}
          </h2>
          <Badge tone="neutral" size="sm" className="font-mono">
            {rejection.rejection_type}
          </Badge>
          <span className="text-sm text-fg-muted">
            {t('claims_list', { list: rejection.affected_claims.join(', ') })}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ConfidencePips score={rejection.confidence} labelKey="confidence.kind.parse" />
          {onShowReferences && (
            <Button variant="outline" size="sm" onClick={onShowReferences} className="2xl:hidden">
              <BookOpen className="h-4 w-4" aria-hidden="true" />
              {t('workspace.show_references')}
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        <section>
          <h3 className="mb-2 text-sm font-medium text-fg-muted">{t('workspace.examiner_argument')}</h3>
          <blockquote className="rounded-brand border-l-4 border-line-strong bg-surface-sunken px-4 py-3 text-[15px] leading-7 text-fg">
            {rejection.examiner_argument}
          </blockquote>
        </section>

        {draft && <VerificationBanner draft={draft} />}

        <ElementTable tables={elementTables} onCitationClick={onCitationClick} />

        {draft && (
          <>
            <section>
              <h3 className="mb-2 text-sm font-medium text-fg-muted">{t('workspace.strategy')}</h3>
              <p className="text-[15px] leading-7 text-fg">
                <CitationText
                  text={draft.strategy || ''}
                  citationLookup={citationLookup}
                  onCitationClick={onCitationClick}
                />
              </p>
            </section>
            <section>
              <h3 className="mb-2 text-sm font-medium text-fg-muted">{t('workspace.draft')}</h3>
              <DraftEditor
                initialDraft={draft.draft_text}
                citationLookup={citationLookup}
                caseId={caseId}
                rejectionId={rejection.rejection_id}
                token={session?.token}
                canExport={canExport}
                role={session?.role}
                onCitationClick={onCitationClick}
                degraded={degraded}
                onProgress={onProgress}
              />
            </section>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * The citation wall, made visible: what passed, what was stripped, which
 * sentences their cited passage does not support, and which model verified.
 * Falls back to counting markers in the text for older backends.
 */
function VerificationBanner({ draft }) {
  const { t } = useTranslation();
  const invalid = Array.isArray(draft?.invalid_citations) ? draft.invalid_citations : null;
  const removedCount = invalid != null ? invalid.length : count(draft?.draft_text, /\[CITATION_REMOVED\]/g);
  const groundedCount = Array.isArray(draft?.grounded_citations) ? draft.grounded_citations.length : null;
  const confidence = Number.isFinite(draft?.verifier_confidence)
    ? draft.verifier_confidence
    : Number.isFinite(draft?.confidence)
      ? draft.confidence
      : null;
  const unsupportedCount = Array.isArray(draft?.unsupported_citations)
    ? draft.unsupported_citations.length
    : count(draft?.draft_text, /\[UNSUPPORTED_REF_\d+\]/g);

  let tone = 'neutral';
  let Icon = AlertTriangle;
  let title = t('analyze.verifier.no_data');
  if (removedCount > 0) {
    tone = 'error';
    Icon = ShieldAlert;
    title = t('analyze.verifier.removed_title', { count: removedCount });
  } else if (groundedCount) {
    tone = 'success';
    Icon = ShieldCheck;
    title = t('analyze.verifier.verified_title', { count: groundedCount });
  }

  return (
    <section
      data-testid="verification-banner"
      className={cn(
        'rounded-brand border px-4 py-3',
        tone === 'error' && 'border-danger/40 bg-danger-soft',
        tone === 'success' && 'border-success/40 bg-success-soft',
        tone === 'neutral' && 'border-line bg-surface-sunken'
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Icon
          className={cn('h-5 w-5 shrink-0', tone === 'error' ? 'text-danger' : tone === 'success' ? 'text-success' : 'text-fg-muted')}
          aria-hidden="true"
        />
        <span className="text-sm font-semibold text-fg">{t('analyze.verifier.heading')}</span>
        <span className="text-sm text-fg-secondary">{title}</span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {groundedCount != null && <Badge tone="success" size="sm">{t('analyze.verifier.grounded', { count: groundedCount })}</Badge>}
          {removedCount > 0 && <Badge tone="error" size="sm">{t('analyze.verifier.removed', { count: removedCount })}</Badge>}
          {unsupportedCount > 0 && (
            <Badge tone="warning" size="sm" data-testid="alignment-banner">
              {t('alignment.banner', { count: unsupportedCount })}
            </Badge>
          )}
          {confidence != null && <ConfidencePips score={confidence} labelKey="confidence.kind.verifier" />}
        </span>
      </div>
      {invalid?.length > 0 && (
        <p className="mt-2 break-words font-mono text-sm text-danger">
          {t('analyze.verifier.removed_list', { items: invalid.join('、') })}
        </p>
      )}
      {draft?.verifier_model && (
        <p className="mt-1 text-xs text-fg-muted">{t('analyze.verifier.verified_by', { model: draft.verifier_model })}</p>
      )}
    </section>
  );
}

function count(text, re) {
  return text ? (text.match(re) || []).length : 0;
}
