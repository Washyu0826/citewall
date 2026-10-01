import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, CheckCheck, ExternalLink, Pencil, ShieldX, Undo2, X } from 'lucide-react';
import { api, ApiError } from '../api/client.js';
import { toast } from '../lib/toast.jsx';
import { cn } from '../lib/utils';
import { Button } from './ui/button.jsx';
import { Kbd } from './ui/page.jsx';
import { Popover, PopoverContent, PopoverTrigger } from './ui/overlay.jsx';
import { CITATION_REMOVED, applyEdit, isAcceptBlocked, splitIntoLines } from '../lib/draftText.js';

/**
 * Sentence-level review + sign-off export (responsibility boundary).
 *
 * Every line (segment) carries provenance:
 *   - source: 'ai_generated' | 'attorney_edited' | 'attorney_added'
 *             | 'paralegal_edited' | 'paralegal_added'
 *   - status: 'pending' | 'accepted' | 'excluded'. Excluded lines are still
 *     sent in the export payload (accepted=false) so provenance stays complete,
 *     but never reach the final document.
 *
 * Export gate: every line decided + "I have reviewed each item" ticked, and the
 * result must not be DEGRADED; the backend 409s without attorney_signoff. A line
 * carrying [CITATION_REMOVED] or [UNSUPPORTED_REF_n] cannot be accepted as-is.
 *
 * Keyboard on a focused line: A accept · E edit · X exclude · U undo; while
 * editing Ctrl+Enter saves, Esc cancels. IME composition never triggers them.
 *
 * `onProgress` reports {total, decided, accepted, excluded, exported} so the
 * workspace can show whole-OA progress across rejections.
 */
export default function DraftEditor({
  initialDraft,
  citationLookup,
  caseId,
  rejectionId,
  token,
  canExport = false,
  role,
  onCitationClick,
  degraded = false,
  onProgress,
}) {
  const { t } = useTranslation();
  const isParalegal = role === 'paralegal';
  const editedSource = isParalegal ? 'paralegal_edited' : 'attorney_edited';
  const addedSource = isParalegal ? 'paralegal_added' : 'attorney_added';
  const [lines, setLines] = useState(() => splitIntoLines(initialDraft));
  const [editingIdx, setEditingIdx] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [addingValue, setAddingValue] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState(null);
  const [showOriginalIdx, setShowOriginalIdx] = useState(null);

  useEffect(() => {
    setLines(splitIntoLines(initialDraft));
    setReviewed(false);
    setExportResult(null);
    setEditingIdx(null);
    setAddingValue('');
    setShowOriginalIdx(null);
  }, [initialDraft]);

  const acceptedCount = lines.filter((l) => l.status === 'accepted').length;
  const excludedCount = lines.filter((l) => l.status === 'excluded').length;
  const decidedCount = acceptedCount + excludedCount;
  const pendingCount = lines.length - decidedCount;
  const acceptBlocked = isAcceptBlocked;
  const acceptablePending = lines.filter((l) => l.status === 'pending' && !acceptBlocked(l)).length;

  // Also hands the per-sentence decisions up, so the workspace can export the
  // whole response in one document. Fires only when `lines` / export change.
  useEffect(() => {
    onProgress?.({
      total: lines.length,
      decided: decidedCount,
      accepted: acceptedCount,
      excluded: excludedCount,
      exported: !!exportResult,
      segments: lines.map((l) => ({
        segment_id: l.segment_id,
        text: l.text,
        source: l.source,
        accepted: l.status === 'accepted',
      })),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- counts derive from `lines`
  }, [onProgress, lines, exportResult]);

  function setStatus(i, status) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, status, ts: new Date().toISOString() } : l)));
  }
  function acceptAllPending() {
    const ts = new Date().toISOString();
    setLines((ls) =>
      ls.map((l) => (l.status === 'pending' && !acceptBlocked(l) ? { ...l, status: 'accepted', ts } : l))
    );
  }
  function startEdit(i) {
    setEditingIdx(i);
    setEditValue(lines[i].text);
  }
  function commitEdit() {
    setLines((ls) => ls.map((l, idx) => (idx === editingIdx ? applyEdit(l, editValue, editedSource) : l)));
    setEditingIdx(null);
  }
  function addLine() {
    const text = addingValue.trim();
    if (!text) return;
    setLines((ls) => [
      ...ls,
      {
        segment_id: `seg-add-${ls.length}-${Date.now()}`,
        text,
        source: addedSource,
        status: 'accepted',
        ts: new Date().toISOString(),
      },
    ]);
    setAddingValue('');
  }

  function lineKeyDown(e, i) {
    if (editingIdx !== null) return;
    if (e.target !== e.currentTarget) return; // a pill / button inside the line has focus
    if (e.nativeEvent?.isComposing) return; // A2: zh-TW IME composition
    const k = e.key.toLowerCase();
    const l = lines[i];
    if (k === 'a' && l.status !== 'accepted' && !acceptBlocked(l)) {
      e.preventDefault();
      setStatus(i, 'accepted');
    } else if (k === 'x' && l.status !== 'excluded') {
      e.preventDefault();
      setStatus(i, 'excluded');
    } else if (k === 'e') {
      e.preventDefault();
      startEdit(i);
    } else if (k === 'u' && l.status !== 'pending') {
      e.preventDefault();
      setStatus(i, 'pending');
    }
  }

  async function doExport() {
    if (!reviewed || !canExport || !token || !caseId || pendingCount > 0 || degraded) return;
    const segments = lines.map((l) => ({
      segment_id: l.segment_id,
      text: l.text,
      source: l.source,
      accepted: l.status === 'accepted',
    }));
    setExporting(true);
    try {
      const res = await api.exportDraft(token, {
        case_id: caseId,
        rejection_id: rejectionId,
        segments,
        attorney_signoff: true,
      });
      setExportResult(res);
      toast.success(t('signoff.export_success'));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error(t('signoff.signoff_required'));
      } else {
        toast.error(`${t('signoff.export_failed')}: ${e.message}`);
      }
    } finally {
      setExporting(false);
    }
  }

  function downloadTxt() {
    if (!exportResult?.document) return;
    const blob = new Blob([exportResult.document], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${caseId || 'response'}${rejectionId ? '-' + rejectionId : ''}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const progressPct = lines.length ? Math.round((decidedCount / lines.length) * 100) : 0;

  return (
    <div className="space-y-3">
      {/* Progress + legend. aria-live so screen readers hear progress. */}
      <div className="space-y-2 rounded-brand border border-line-subtle bg-surface-sunken px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-medium text-fg" aria-live="polite">
            {t('signoff.decided_count', { decided: decidedCount, total: lines.length })}
          </span>
          {acceptedCount > 0 && <span className="text-success">{t('signoff.accepted_count', { count: acceptedCount })}</span>}
          {excludedCount > 0 && <span className="text-danger">{t('signoff.excluded_count', { count: excludedCount })}</span>}
          <span className="ml-auto flex items-center gap-3 text-xs text-fg-muted">
            <span className="ai-line px-1">{t('signoff.source_ai')}</span>
            <span className="attorney-line px-1">{t('signoff.source_edited')}</span>
          </span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-valuenow={decidedCount}
          aria-valuemin={0}
          aria-valuemax={lines.length}
          aria-label={t('signoff.decided_count', { decided: decidedCount, total: lines.length })}
        >
          <div className="h-full rounded-full bg-brand-fg transition-all" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-muted">
          <span className="flex flex-wrap items-center gap-1.5">
            <Kbd>A</Kbd> {t('signoff.accept')} <Kbd>E</Kbd> {t('signoff.edit')} <Kbd>X</Kbd> {t('signoff.exclude')}{' '}
            <Kbd>U</Kbd> {t('signoff.undo')}
          </span>
          {acceptablePending > 1 && (
            <Button size="xs" variant="outline" onClick={acceptAllPending} data-testid="signoff-accept-all">
              <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {t('signoff.accept_all_rest', { count: acceptablePending })}
            </Button>
          )}
        </div>
      </div>

      <ol className="space-y-1">
        {lines.map((l, i) => (
          <li
            key={l.segment_id}
            data-testid="draft-line"
            data-status={l.status}
            tabIndex={0}
            onKeyDown={(e) => lineKeyDown(e, i)}
            aria-label={`${i + 1}. ${l.text}`}
            className={cn(
              'group flex items-start gap-2 rounded-brand border-l-2 py-1 pl-2 pr-1 transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover',
              l.status === 'pending' ? 'border-accent' : 'border-transparent'
            )}
          >
            <span className="w-6 shrink-0 pt-1 text-right font-mono text-xs text-fg-muted">{i + 1}</span>
            {editingIdx === i ? (
              <div className="flex-1">
                <textarea
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => {
                    // A2: Esc during IME composition cancels the COMPOSITION, not the edit.
                    if (e.nativeEvent?.isComposing) return;
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) commitEdit();
                    if (e.key === 'Escape') setEditingIdx(null);
                  }}
                  autoFocus
                  className="w-full rounded border border-success/50 bg-surface-raised p-2 font-serif text-base leading-8 text-fg"
                  rows={3}
                />
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <Button size="xs" onClick={commitEdit} className="bg-emerald-700 hover:bg-emerald-800">
                    {t('signoff.save')}
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setEditingIdx(null)}>
                    {t('signoff.cancel')}
                  </Button>
                  <span className="text-xs text-fg-muted">{t('signoff.edit_kbd_hint')}</span>
                </div>
              </div>
            ) : (
              <>
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      'px-1 font-serif text-base leading-8 text-fg',
                      l.source === 'ai_generated' ? 'ai-line' : 'attorney-line',
                      l.status === 'excluded' && 'text-fg-muted line-through decoration-rose-400/60'
                    )}
                  >
                    <CitationText text={l.text} citationLookup={citationLookup} onCitationClick={onCitationClick} />
                    {l.status === 'accepted' && (
                      <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-medium text-success">
                        <Check className="h-3.5 w-3.5" aria-hidden="true" />
                        {sourceLabel(l.source, t)}
                      </span>
                    )}
                    {l.status === 'excluded' && (
                      <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-medium text-danger no-underline">
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                        {t('signoff.excluded')}
                      </span>
                    )}
                  </p>
                  {l.edited_from && (
                    <div className="px-1">
                      <button
                        type="button"
                        onClick={() => setShowOriginalIdx(showOriginalIdx === i ? null : i)}
                        aria-expanded={showOriginalIdx === i}
                        className="text-xs text-fg-muted underline decoration-dotted underline-offset-2 hover:text-fg"
                      >
                        {showOriginalIdx === i ? t('signoff.hide_original') : t('signoff.view_original')}
                      </button>
                      {showOriginalIdx === i && (
                        <p className="mt-1 rounded border border-line bg-surface-sunken px-2 py-1 text-sm text-fg-muted line-through decoration-slate-400/60">
                          {l.edited_from}
                        </p>
                      )}
                    </div>
                  )}
                </div>
                {/* Always visible (touch + keyboard), subdued until hover / focus. */}
                <div className="flex shrink-0 gap-0.5 opacity-70 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  {l.status !== 'accepted' &&
                    (acceptBlocked(l) ? (
                      <span
                        title={blockedReason(l.text, t)}
                        aria-label={blockedReason(l.text, t)}
                        data-testid="line-accept-blocked"
                        className="inline-flex cursor-not-allowed items-center gap-1 rounded px-1.5 py-1 text-xs font-medium text-fg-muted opacity-50"
                      >
                        <Check className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="hidden sm:inline">{t('signoff.accept')}</span>
                      </span>
                    ) : (
                      <LineAction label={t('signoff.accept')} testid="line-accept" onClick={() => setStatus(i, 'accepted')} className="text-success hover:bg-success-soft">
                        <Check className="h-3.5 w-3.5" aria-hidden="true" />
                      </LineAction>
                    ))}
                  <LineAction label={t('signoff.edit')} testid="line-edit" onClick={() => startEdit(i)} className="text-fg-secondary hover:bg-surface-sunken">
                    <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  </LineAction>
                  {l.status !== 'excluded' && (
                    <LineAction label={t('signoff.exclude')} testid="line-exclude" onClick={() => setStatus(i, 'excluded')} className="text-danger hover:bg-danger-soft">
                      <X className="h-3.5 w-3.5" aria-hidden="true" />
                    </LineAction>
                  )}
                  {l.status !== 'pending' && (
                    <LineAction label={t('signoff.undo')} testid="line-undo" onClick={() => setStatus(i, 'pending')} className="text-fg-muted hover:bg-surface-sunken">
                      <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </LineAction>
                  )}
                </div>
              </>
            )}
          </li>
        ))}
      </ol>

      {/* Human-added line */}
      <div className="flex items-start gap-2 pl-10">
        <div className="flex-1">
          <label className="sr-only" htmlFor={`add-line-${rejectionId}`}>
            {t('signoff.new_line_placeholder')}
          </label>
          <textarea
            id={`add-line-${rejectionId}`}
            value={addingValue}
            onChange={(e) => setAddingValue(e.target.value)}
            placeholder={t('signoff.new_line_placeholder')}
            className="w-full rounded border border-line-strong bg-surface-raised p-2 text-sm text-fg placeholder:text-fg-muted"
            rows={2}
          />
          <Button size="xs" variant="outline" onClick={addLine} disabled={!addingValue.trim()} className="mt-1.5">
            {t('signoff.add_line')}
          </Button>
        </div>
      </div>

      {/* Sign-off gate */}
      {canExport && (
        <div className="space-y-3 rounded-brand border border-line bg-surface-sunken p-3">
          <label className="flex items-start gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-line-strong accent-navy-900"
              data-testid="signoff-checkbox"
            />
            <span>{t('signoff.review_each')}</span>
          </label>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-fg-muted" aria-live="polite">
              {degraded
                ? t('signoff.degraded_export_blocked')
                : pendingCount > 0
                  ? t('signoff.undecided_hint', { count: pendingCount })
                  : acceptedCount === 0
                    ? t('signoff.no_accepted')
                    : reviewed
                      ? null
                      : t('signoff.export_hint')}
            </p>
            <Button
              type="button"
              variant="primary"
              disabled={!reviewed || exporting || acceptedCount === 0 || pendingCount > 0 || degraded}
              onClick={doExport}
              data-testid="signoff-export"
            >
              {exporting ? t('signoff.exporting') : t('signoff.export')}
            </Button>
          </div>
        </div>
      )}

      {exportResult && (
        <ExportResultPanel result={exportResult} onDownload={downloadTxt} onClose={() => setExportResult(null)} t={t} />
      )}
    </div>
  );
}

function LineAction({ label, onClick, testid, className = '', children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-label={label}
      title={label}
      className={cn('inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium transition-colors', className)}
    >
      {children}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function ExportResultPanel({ result, onDownload, onClose, t }) {
  const s = result.provenance_summary || {};
  return (
    <div className="space-y-2 rounded-brand border border-success/40 bg-success-soft p-3" data-testid="export-result">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-success">{t('signoff.result_title')}</h4>
        <Button type="button" variant="link" size="xs" onClick={onClose} className="text-fg-muted">
          {t('signoff.close')}
        </Button>
      </div>
      <p className="text-sm text-fg-secondary">
        {t('signoff.signed_off_by')}: <span className="font-medium text-fg">{result.signed_off_by}</span>
      </p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface-raised p-2 text-sm text-fg">
        {result.document}
      </pre>
      <div className="flex flex-wrap gap-3 text-xs text-fg-muted">
        <span>{t('signoff.source_ai')}: {s.ai_generated ?? 0}</span>
        <span>{t('signoff.source_edited')}: {s.attorney_edited ?? 0}</span>
        <span>{t('signoff.source_added')}: {s.attorney_added ?? 0}</span>
        {(s.paralegal_edited ?? 0) > 0 && (
          <span>{t('signoff.source_paralegal_edited')}: {s.paralegal_edited}</span>
        )}
        {(s.paralegal_added ?? 0) > 0 && <span>{t('signoff.source_paralegal_added')}: {s.paralegal_added}</span>}
      </div>
      <p className="break-all font-mono text-xs text-fg-muted">
        {t('signoff.content_hash')}: {result.content_sha256}
      </p>
      <Button type="button" size="xs" onClick={onDownload} className="bg-emerald-700 hover:bg-emerald-800">
        {t('signoff.download')}
      </Button>
    </div>
  );
}

function sourceLabel(source, t) {
  if (source === 'attorney_added') return t('signoff.source_added');
  if (source === 'attorney_edited') return t('signoff.source_edited');
  if (source === 'paralegal_added') return t('signoff.source_paralegal_added');
  if (source === 'paralegal_edited') return t('signoff.source_paralegal_edited');
  return t('signoff.accepted');
}

function blockedReason(text, t) {
  return text.includes(CITATION_REMOVED) ? t('signoff.citation_removed_no_accept') : t('alignment.no_accept');
}

/**
 * Renders a draft sentence with its citations as pills. Each pill opens an
 * accessible popover (focus / tap / Enter — not hover-only; UX_REVIEW T7) with
 * the source passage and a jump to the references panel. Also used for the
 * rejection's strategy paragraph, so no raw [GROUNDED_REF_n] marker is shown.
 */
export function CitationText({ text, citationLookup, onCitationClick }) {
  const parts = useMemo(
    () => text.split(/(\[GROUNDED_REF_\d+\]|\[UNSUPPORTED_REF_\d+\]|\[CITATION_REMOVED\])/g),
    [text]
  );
  return (
    <>
      {parts.map((p, i) => {
        const grounded = /^\[GROUNDED_REF_(\d+)\]$/.exec(p);
        if (grounded) {
          return (
            <CitationPill
              key={i}
              n={grounded[1]}
              hit={citationLookup?.[p]}
              onCitationClick={onCitationClick}
            />
          );
        }
        const unsupported = /^\[UNSUPPORTED_REF_(\d+)\]$/.exec(p);
        if (unsupported) {
          return (
            <CitationPill
              key={i}
              n={unsupported[1]}
              hit={citationLookup?.[`[GROUNDED_REF_${unsupported[1]}]`]}
              onCitationClick={onCitationClick}
              unsupported
            />
          );
        }
        if (p === CITATION_REMOVED) return <RemovedPill key={i} />;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

function CitationPill({ n, hit, onCitationClick, unsupported = false }) {
  const { t } = useTranslation();
  const label = unsupported ? `${t('alignment.unsupported_pill')} ${n}` : `${t('citation.pill')} ${n}`;
  return (
    <Popover>
      <PopoverTrigger
        data-testid={unsupported ? 'unsupported-ref' : 'grounded-ref'}
        className={cn(
          'mx-0.5 inline-flex items-center gap-1 rounded border px-1.5 align-baseline font-mono text-xs leading-5 transition-colors',
          unsupported
            ? 'border-warning/50 bg-warning-soft text-warning hover:bg-warning-soft/70'
            : 'border-brand-fg/30 bg-brand-soft text-brand-fg hover:border-brand-fg/60'
        )}
      >
        {unsupported && <AlertTriangle className="h-3 w-3" aria-hidden="true" />}
        {label}
      </PopoverTrigger>
      <PopoverContent className="w-96">
        {unsupported && (
          <p className="mb-2 flex items-start gap-1.5 rounded bg-warning-soft px-2 py-1.5 text-sm text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {t('alignment.no_accept')}
          </p>
        )}
        {hit ? (
          <>
            <p className="text-xs text-fg-muted">{t('citation.source')}</p>
            <p className="mt-0.5 font-mono text-sm font-medium text-fg">
              {hit.patent_no}
              <span className="ml-1 font-sans font-normal text-fg-muted">· {hit.section}</span>
            </p>
            <blockquote className="mt-2 max-h-48 overflow-y-auto border-l-2 border-line-strong pl-3 font-serif text-sm leading-relaxed text-fg-secondary">
              {hit.text}
            </blockquote>
            {onCitationClick && (
              <Button
                variant="outline"
                size="xs"
                className="mt-3"
                onClick={() => onCitationClick({ patentNo: hit.patent_no, nonce: Date.now() })}
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                {t('citation.open_in_panel')}
              </Button>
            )}
          </>
        ) : (
          <p className="text-sm text-fg-muted">{t('citation.no_source')}</p>
        )}
      </PopoverContent>
    </Popover>
  );
}

function RemovedPill() {
  const { t } = useTranslation();
  return (
    <Popover>
      <PopoverTrigger
        data-testid="citation-removed"
        className="mx-0.5 inline-flex items-center gap-1 rounded border border-danger/40 bg-danger-soft px-1.5 align-baseline font-mono text-xs leading-5 text-danger"
      >
        <ShieldX className="h-3 w-3" aria-hidden="true" />
        {t('citation.removed_pill')}
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <p className="text-sm font-medium text-danger">{t('citation.removed_title')}</p>
        <p className="mt-1 text-sm text-fg-secondary">{t('citation.removed_body')}</p>
      </PopoverContent>
    </Popover>
  );
}
