import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, Link2 } from 'lucide-react';

import { hitsForRejection } from '../../lib/citations.js';
import { cn } from '../../lib/utils';
import EmptyState from '../EmptyState.jsx';
import { Badge } from '../ui/badge.jsx';
import { Button } from '../ui/button.jsx';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../ui/overlay.jsx';

/**
 * Prior art for the active rejection: the passages the draft cites
 * ([GROUNDED_REF_n], in ref order) and the examiner's own citations, flagged
 * when they were not in the retrievable corpus. A citation click elsewhere
 * scrolls to and highlights the matching card.
 */
export default function ReferencesPanel({ result, activeRejectionId, selectedCitation }) {
  const { t } = useTranslation();
  const [openHit, setOpenHit] = useState(null);
  const [highlight, setHighlight] = useState(null);
  const cardRefs = useRef({});

  const rejection = (result?.oa?.rejections || []).find((r) => r.rejection_id === activeRejectionId);
  const hits = useMemo(() => hitsForRejection(result, activeRejectionId), [result, activeRejectionId]);
  const retrieved = useMemo(() => new Set(hits.map((h) => h.patent_no)), [hits]);
  const cited = rejection?.cited_prior_art || [];

  useEffect(() => {
    if (!selectedCitation?.patentNo) return undefined;
    const idx = hits.findIndex((h) => h.patent_no === selectedCitation.patentNo);
    if (idx === -1) return undefined;
    const el = cardRefs.current[idx];
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    setHighlight(idx);
    const id = window.setTimeout(() => setHighlight((cur) => (cur === idx ? null : cur)), 2200);
    return () => window.clearTimeout(id);
    // nonce re-fires repeated clicks on the same pill.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCitation?.nonce, selectedCitation?.patentNo]);

  if (!result) {
    return (
      <EmptyState
        bare
        icon={<Link2 className="mx-auto h-9 w-9 text-fg-muted" strokeWidth={1.5} aria-hidden="true" />}
        title={t('analyze.refs.empty_title')}
        description={t('analyze.refs.empty_desc')}
      />
    );
  }

  return (
    <div className="space-y-5" data-testid="references-panel">
      {cited.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-fg-muted">{t('analyze.refs.cited_title')}</h3>
          <ul className="flex flex-wrap gap-1.5">
            {cited.map((p) => (
              <li key={p}>
                <Badge tone={retrieved.has(p) ? 'brand' : 'neutral'} className="font-mono" title={retrieved.has(p) ? undefined : t('workspace.not_retrieved')}>
                  {p}
                  {!retrieved.has(p) && <span className="font-sans text-fg-muted">· {t('workspace.not_retrieved')}</span>}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-medium text-fg-muted">{t('analyze.refs.rag_title')}</h3>
        {hits.length === 0 ? (
          <p className="rounded-brand border border-dashed border-line-strong bg-surface-sunken p-3 text-sm text-fg-muted">
            {t('analyze.refs.no_hits')}
          </p>
        ) : (
          <ol className="space-y-3">
            {hits.map((h, i) => {
              const n = h.metadata?.ref_index || i + 1;
              return (
                <li
                  key={`${h.patent_no}-${i}`}
                  ref={(el) => (cardRefs.current[i] = el)}
                  className={cn(
                    'rounded-brand border bg-surface-raised p-3 transition-colors',
                    highlight === i ? 'border-brand-fg ring-2 ring-brand-fg/30' : 'border-line'
                  )}
                  data-testid="reference-card"
                >
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <Badge tone="brand" size="sm" className="font-mono">
                      {t('citation.pill')} {n}
                    </Badge>
                    <span className="font-mono text-sm font-medium text-fg">{h.patent_no}</span>
                    {h.examinerCited && (
                      <Badge tone="info" size="sm">
                        {t('workspace.cited_badge')}
                      </Badge>
                    )}
                    <span className="ml-auto text-xs text-fg-muted">
                      {t('analyze.refs.score')} {Number(h.score ?? 0).toFixed(2)}
                    </span>
                  </div>
                  <p className="mb-1 text-xs text-fg-muted">{h.section}</p>
                  <p className="line-clamp-4 text-sm leading-6 text-fg-secondary">{h.text}</p>
                  <Button variant="link" size="xs" className="mt-1 h-auto px-0" onClick={() => setOpenHit(h)}>
                    <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('analyze.refs.open_full')}
                  </Button>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <Dialog open={!!openHit} onOpenChange={(o) => !o && setOpenHit(null)}>
        <DialogContent wide closeLabel={t('signoff.close')}>
          {openHit && (
            <>
              <DialogHeader>
                <DialogTitle className="font-mono">{openHit.patent_no}</DialogTitle>
                <DialogDescription>
                  {openHit.section} · {t('analyze.refs.score')} {Number(openHit.score ?? 0).toFixed(2)}
                </DialogDescription>
              </DialogHeader>
              <DialogBody>
                <p className="whitespace-pre-wrap text-[15px] leading-7 text-fg">{openHit.text}</p>
              </DialogBody>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
