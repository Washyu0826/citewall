import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CalendarPlus } from 'lucide-react';
import { Button } from './ui/button.jsx';

// Static deadline-urgency tone classes (light + dark). Kept as a literal map so
// the Tailwind JIT scanner sees every class string at build time — this lets us
// drop the `bg-${tone}` interpolation that previously forced a safelist entry
// AND adds the dark-mode variants the old `bg-${tone}-100` chips were missing.
const DEADLINE_TONE = {
  rose: {
    text: 'text-rose-700 dark:text-rose-300',
    pill: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  },
  amber: {
    text: 'text-amber-700 dark:text-amber-300',
    pill: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  },
  emerald: {
    text: 'text-emerald-700 dark:text-emerald-300',
    pill: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  },
};
import { api } from '../api/client.js';
import { useQuota, useAnalyze } from '../api/queries.js';
import { useDebouncedValue } from '../lib/useDebouncedValue.js';
import { toast } from '../lib/toast.jsx';
import { downloadDeadlineIcs } from '../lib/ics.js';
import { buildCitationLookup } from '../lib/citations.js';
import { formatDate } from '../lib/format.js';
import { jurisdictionForPatent } from '../lib/jurisdiction.js';
import {
  buildDeadlineRequestFields,
  showNotReviewedNote,
  startBasisKey,
} from '../lib/deadlineInputs.js';
import InputPane from './analyze/InputPane.jsx';
import DraftsPane from './analyze/DraftsPane.jsx';
import ReferencesPane from './analyze/ReferencesPane.jsx';

const SAMPLE_OA = `UNITED STATES PATENT AND TRADEMARK OFFICE
Office Action

Application No.: 17/123,456
Applicant: NCCU Apex Patent Law Firm (file ref: APEX-2025-0314, client: CL-EVCO12)
Examiner: J. Smith
Mailing Date: 2025-04-15

Claims 1-3 are rejected under 35 U.S.C. § 103 as being obvious over US7654321
in view of US6543210. The combination of microchannels with non-uniform
cross-section and copper construction yields predictable results.

Claims 4-5 are rejected under 35 U.S.C. § 102 as anticipated by US7654321.

Attorney contact: alice.chen@apex-ip.com (mobile: 0912-345-678)
`;

// Day 9C: emoji-free chip labels. The visual cue is the chip color tone
// (emerald / rose / amber) computed below, not a glyph prefix. Labels live in
// i18n under `security_badge.<policy key>.{ok,no}`.
const SECURITY_BADGE_KEYS = new Set([
  'rate_limit_passed',
  'quota_passed',
  'authz_passed',
  'cache_hit',
  'circuit_open',
]);

/**
 * Three-pane analyze workspace (UX_RESEARCH §4.4, §5 #1 must-have).
 *
 * Desktop (≥ xl / 1280px): InputPane (30%) | DraftsPane (40%) | ReferencesPane (30%).
 * Each pane scrolls independently. Active rejection is lifted to this parent
 * so the tab strip in DraftsPane and the filter in ReferencesPane stay in sync.
 *
 * Tablet / mobile (< xl): single column, top tab strip swaps which pane renders.
 *
 * Day 9C — embedded mode. When mounted inside `<AppShell>` (the default for
 * all authenticated routes after CHUNK-1), the in-component `<Header>` and
 * tenant chip are suppressed: the shell owns the chrome. The three-pane
 * grid (`xl:grid-cols-[3fr_4fr_3fr]`) is preserved exactly. `onTrustChange`
 * lets the shell's trust band react to per-analysis context (case id +
 * masked-entity count). All optional / default no-op so older callers /
 * tests that don't pass `embedded` keep rendering the standalone header.
 */
export default function Analyze({
  session,
  onLogout,
  onSwitchView,
  embedded = false,
  onTrustChange,
}) {
  const { t } = useTranslation();
  const [oaText, setOaText] = useState(SAMPLE_OA);
  const [caseId, setCaseId] = useState('CASE-2025-001');
  const [targetPatent, setTargetPatent] = useState('US17123456');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [redactPreview, setRedactPreview] = useState(null);
  const queryClient = useQueryClient();
  // Server state via TanStack Query (P1③). Quota is a cached query; analyze is
  // a mutation. `running` is derived from the mutation's in-flight state.
  // Debounced: the case-ID input would otherwise fire a quota request per
  // keystroke. The post-analyze invalidation below uses the settled caseId.
  const quotaCaseId = useDebouncedValue(caseId, 400);
  const { data: quota } = useQuota(session.token, quotaCaseId);
  const analyzeMut = useAnalyze(session.token);
  const running = analyzeMut.isPending;
  const [showUpload, setShowUpload] = useState(true);
  // Optional deadline inputs (Q16/Q17/Q19); blank = backend presumptions.
  const [domicile, setDomicile] = useState('unknown');
  const [oaSequence, setOaSequence] = useState('');
  const [serviceDate, setServiceDate] = useState('');
  const [loadedMeta, setLoadedMeta] = useState(null);
  const [uploadWarnings, setUploadWarnings] = useState([]);
  // Shared cross-pane state: which rejection is currently focused.
  const [activeRejectionId, setActiveRejectionId] = useState(null);
  // < xl: which pane is visible. Desktop ignores this.
  const [mobileTab, setMobileTab] = useState('input'); // 'input' | 'drafts' | 'refs'
  const isDesktop = useMediaQuery(XL_QUERY);
  // ★2 跨窗格連動：DraftEditor 點 grounded pill → ReferencesPane 捲動 + 高亮。
  // {patentNo, nonce} — nonce 讓重複點同一顆 pill 也會重新觸發。
  const [selectedCitation, setSelectedCitation] = useState(null);
  const handleCitationClick = (citation) => {
    setSelectedCitation(citation);
    // 行動版 refs pane 沒掛載時先切過去，掛載時 effect 會吃到 selectedCitation。
    setMobileTab('refs');
  };

  const handleExtractSuccess = (payload) => {
    setOaText(payload.extracted_text || '');
    setLoadedMeta({ fileName: payload.fileName, pages: payload.page_count });
    setUploadWarnings(Array.isArray(payload.warnings) ? payload.warnings : []);
    toast.success(t('upload.toast_success', { pages: payload.page_count ?? 0 }));
  };

  // When a new result arrives, default the active rejection to the first one.
  useEffect(() => {
    if (!result) {
      setActiveRejectionId(null);
      return;
    }
    const first = result.oa?.rejections?.[0]?.rejection_id;
    if (first) setActiveRejectionId(first);
  }, [result]);

  // When a new result arrives on mobile, surface the drafts tab so the
  // attorney sees the output without an extra tap.
  useEffect(() => {
    if (result) setMobileTab('drafts');
  }, [result]);

  // Day 9C — feed the AppShell trust band. Fires on every case/result change
  // so the band's `Routing` chip flips between Auto/Confidential and the
  // Redaction chip shows the per-analysis entity count. The default
  // `onTrustChange` is a no-op, so standalone (non-embedded) mounts skip this.
  useEffect(() => {
    if (typeof onTrustChange !== 'function') return;
    onTrustChange({
      caseId,
      maskedEntityCount: result?.redaction_summary?.masked_entity_count ?? 0,
    });
  }, [onTrustChange, caseId, result]);

  const [previewing, setPreviewing] = useState(false);
  async function previewRedaction() {
    setPreviewing(true);
    try {
      const r = await api.redactionPreview(session.token, oaText, caseId);
      setRedactPreview(r);
    } catch (e) {
      setError(e);
    } finally {
      setPreviewing(false);
    }
  }

  async function runAnalyze() {
    setError(null);
    setResult(null);
    try {
      const r = await analyzeMut.mutateAsync({
        oa_text: oaText,
        case_id: caseId,
        target_patent_no: targetPatent,
        ...buildDeadlineRequestFields({ domicile, oaSequence, serviceDate }),
      });
      setResult(r);
      // Refresh quota after a successful analyze (tokens were spent) — replaces
      // the old `result`-in-deps useEffect hack with an explicit invalidation.
      queryClient.invalidateQueries({ queryKey: ['quota', caseId] });
    } catch (e) {
      setError(e);
    }
  }

  // {rejection_id: {[GROUNDED_REF_N]: hit}} for citation hover (Q14) — see
  // lib/citations.js for why the lookup must be per rejection.
  const citationLookup = useMemo(
    () => (result ? buildCitationLookup(result.related_prior_art) : {}),
    [result]
  );

  const inputPaneProps = {
    caseId,
    setCaseId,
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
    showUpload,
    setShowUpload,
    loadedMeta,
    uploadWarnings,
    onExtractSuccess: handleExtractSuccess,
    session,
    onPreviewRedaction: previewRedaction,
    previewing,
    onAnalyze: runAnalyze,
    running,
    error,
    setError,
    onLogout,
    redactPreview,
    quota,
    // UX_RESEARCH §5 #2 — claim dependency tree props. Defaults to empty
    // when there's no result yet; ClaimTree returns null in that case.
    claimTree: result?.claim_tree || [],
    rejections: result?.oa?.rejections || [],
    activeRejectionId,
    setActiveRejectionId,
  };

  const draftsPaneProps = {
    result,
    running,
    activeRejectionId,
    setActiveRejectionId,
    citationLookup,
    caseId,
    session,
    onCitationClick: handleCitationClick,
  };

  const referencesPaneProps = {
    result,
    activeRejectionId,
    selectedCitation,
  };

  return (
    <div
      className={`flex flex-col bg-slate-50 dark:bg-slate-800/50 ${embedded ? 'min-h-0 flex-1' : 'min-h-screen'}`}
    >
      {!embedded && <Header session={session} onLogout={onLogout} onSwitchView={onSwitchView} />}

      {result && (
        <ResultSummaryBar result={result} caseId={caseId} targetPatent={targetPatent} />
      )}

      {/* Render exactly ONE layout (not two CSS-toggled copies): duplicate
          mounts meant duplicate element ids, two <main>s and two independent
          sign-off states. Panes stay mounted across mobile tab switches
          (hidden, not unmounted) so draft review progress survives. */}
      {isDesktop ? (
        <main className="grid flex-1 grid-cols-[3fr_4fr_3fr]">
          <div className="min-h-0 border-r bg-white dark:border-slate-700 dark:bg-slate-900">
            <InputPane {...inputPaneProps} />
          </div>
          <div className="min-h-0 border-r bg-white dark:border-slate-700 dark:bg-slate-900">
            <DraftsPane {...draftsPaneProps} />
          </div>
          <div className="min-h-0 bg-white dark:bg-slate-900">
            <ReferencesPane {...referencesPaneProps} />
          </div>
        </main>
      ) : (
        <main className="flex flex-1 flex-col">
          <MobileTabBar
            activeTab={mobileTab}
            setActiveTab={setMobileTab}
            hasResult={!!result || running}
          />
          <div className="flex flex-1">
            <div className="w-full" hidden={mobileTab !== 'input'}>
              <InputPane {...inputPaneProps} />
            </div>
            <div className="w-full" hidden={mobileTab !== 'drafts'}>
              <DraftsPane {...draftsPaneProps} />
            </div>
            <div className="w-full" hidden={mobileTab !== 'refs'}>
              <ReferencesPane {...referencesPaneProps} />
            </div>
          </div>
        </main>
      )}
    </div>
  );
}

// Tailwind `xl` breakpoint — the three-pane layout threshold.
const XL_QUERY = '(min-width: 1280px)';

function useMediaQuery(query) {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return undefined;
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

// Day 9C: legacy standalone Header retained for `embedded=false` callers
// (a few tests + the placeholder cases route prior to the shell switch).
// The shell's TopBar/NavRail superset this when mounted inside AppShell.
function Header({ session, onLogout, onSwitchView }) {
  const { t } = useTranslation();
  return (
    <header className="border-b bg-white dark:border-slate-700 dark:bg-slate-900">
      <div className="mx-auto flex max-w-[1920px] items-center gap-4 px-6 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-navy-900 text-sm font-bold text-white">
            PM
          </div>
          <span className="font-semibold">{t('app_title')}</span>
        </div>
        <nav className="ml-6 flex gap-1" aria-label={t('nav.analyze')}>
          <button
            onClick={() => onSwitchView('analyze')}
            className="rounded bg-navy-50 px-3 py-1.5 text-sm font-medium text-navy-700 dark:bg-navy-900/40 dark:text-navy-200"
          >
            {t('nav.analyze')}
          </button>
          <button
            onClick={() => onSwitchView('audit')}
            className="rounded px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            {t('nav.audit')}
          </button>
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <div className="text-right">
            <div className="font-medium">{session.display_name}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {session.tenant_id} · {session.role}
            </div>
          </div>
          <Button variant="secondary" size="xs" onClick={onLogout}>
            {t('buttons.logout')}
          </Button>
        </div>
      </div>
    </header>
  );
}

/**
 * Slim band under the header that surfaces the cross-cutting "result metadata"
 * (policy chips + deadline). Visible above all three panes so the context is
 * not duplicated inside each pane.
 */
function ResultSummaryBar({ result, caseId, targetPatent }) {
  const { t, i18n } = useTranslation();
  // UX_REVIEW T1: chips render the backend's REAL per-request gate outcomes
  // (result.policy_decisions — the same dict the audit row records). A chip
  // with no data is hidden, never faked: an older backend / cached payload
  // without the field shows only the cache chip.
  const policyChips = useMemo(() => {
    const pd = result.policy_decisions || {};
    const chips = ['authz_passed', 'rate_limit_passed', 'quota_passed']
      .filter((k) => typeof pd[k] === 'boolean')
      .map((k) => [k, pd[k]]);
    if (typeof result.cost_meta?.cache_hit === 'boolean') {
      chips.push(['cache_hit', result.cost_meta.cache_hit]);
    }
    if (typeof pd.circuit_open === 'boolean') chips.push(['circuit_open', pd.circuit_open]);
    return chips;
  }, [result]);

  // Null-guarded: a degraded / partial payload may omit the deadline block.
  const ds = result.deadline_summary || {};
  const dr = Number.isFinite(ds.days_remaining) ? ds.days_remaining : null;
  const tone = dr == null ? 'amber' : dr < 14 ? 'rose' : dr < 30 ? 'amber' : 'emerald';
  const toneCls = DEADLINE_TONE[tone];

  // ★ deadline 計算依據可解釋：後端已回傳順延理由 / 建議內部完成日 / 假日表版本，
  // 但原本只顯示日期+天數。期日算錯 = 喪失專利權，因此「為何是這天」必須可攤開。
  const [showDeadlineDetail, setShowDeadlineDetail] = useState(false);
  const locale = (i18n.language || 'zh-TW').startsWith('zh') ? 'zh-TW' : 'en-US';
  // formatDate parses a bare 'YYYY-MM-DD' as a LOCAL calendar date (a plain
  // `new Date('2025-04-30')` is UTC midnight → shows 04-29 west of UTC).
  const fmt = (iso) =>
    iso
      ? formatDate(iso, { locale, year: 'numeric', month: 'numeric', day: 'numeric' }) || '—'
      : '—';
  const isTW = jurisdictionForPatent(targetPatent) === 'TW';
  const warnings = Array.isArray(ds.warnings) ? ds.warnings : [];
  const assumptions = Array.isArray(ds.assumptions) ? ds.assumptions : [];
  const basisKey = startBasisKey(ds.start_date_basis);

  return (
    <div className="border-b bg-white dark:border-slate-700 dark:bg-slate-900">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-4 px-6 py-2 text-xs">
        <div className="flex flex-wrap gap-1.5">
          {policyChips.map(([k, v]) => {
            if (!SECURITY_BADGE_KEYS.has(k)) return null;
            // `good` drives the COLOR (an open breaker / blocked gate is bad);
            // the LABEL follows the raw value. These were conflated before,
            // inverting the cache/breaker chip text (miss read "Cache hit",
            // a closed breaker read "Breaker open").
            const good = k === 'cache_hit' || k === 'circuit_open' ? !v : v;
            const label = t(`security_badge.${k}.${v ? 'ok' : 'no'}`);
            return (
              <span
                key={k}
                className={`rounded px-2 py-0.5 font-mono ${
                  k === 'cache_hit'
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
                    : good
                      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300'
                      : 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300'
                }`}
              >
                {label}
              </span>
            );
          })}
        </div>
        <div className={`ml-auto flex items-center gap-2 ${toneCls.text}`}>
          <span className="text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {t('analyze.result.deadline_label')}
          </span>
          <span className="font-mono">{fmt(ds.statutory_deadline)}</span>
          <span className={`rounded px-2 py-0.5 font-semibold ${toneCls.pill}`}>
            {dr ?? '—'} {t('analyze.result.days')}
          </span>
          {warnings.length > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
              title={warnings.join('\n')}
            >
              <AlertTriangle className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
              {warnings.length}
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => setShowDeadlineDetail((s) => !s)}
            aria-expanded={showDeadlineDetail}
            className="px-1.5 py-0.5 text-slate-500 underline-offset-2 hover:underline dark:text-slate-400"
          >
            {showDeadlineDetail ? t('analyze.result.collapse') : t('analyze.result.why')}
          </Button>
        </div>
      </div>

      {/* Q21/Q18: the deadline rules have NOT been reviewed by a patent
          attorney — say so every time a deadline is shown, not only when the
          detail panel is open. */}
      <div
        data-testid="deadline-notice"
        className="mx-auto flex max-w-[1920px] flex-wrap gap-x-4 gap-y-0.5 px-6 pb-1.5 text-2xs text-amber-700 dark:text-amber-300"
      >
        {showNotReviewedNote(ds) && <span>{t('deadline_notice.not_reviewed')}</span>}
        {isTW && <span data-testid="deadline-tw-foreign-hint">{t('deadline_notice.tw_foreign_hint')}</span>}
      </div>

      {/* Assumptions are unknown facts resolved to the EARLIER deadline
          (applicant domicile, OA sequence, service date). They change the
          date itself, so they stay visible — not hidden behind "Why". */}
      {assumptions.length > 0 && (
        <div
          data-testid="deadline-assumptions"
          className="mx-auto max-w-[1920px] px-6 pb-1.5 text-2xs text-amber-800 dark:text-amber-200"
        >
          <span className="font-semibold">{t('deadline_detail.assumptions')}：</span>
          <ul className="inline">
            {assumptions.map((a, i) => (
              <li key={i} className="ml-1 inline after:content-['；'] last:after:content-['']">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {showDeadlineDetail && (
        <div
          data-testid="deadline-details"
          className="mx-auto max-w-[1920px] border-t border-slate-100 bg-slate-50 px-6 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300"
        >
          <dl className="flex flex-wrap gap-x-6 gap-y-1">
            {ds.mailing_date && (
              <div className="flex gap-1">
                <dt className="text-slate-400 dark:text-slate-500">
                  {t('deadline_detail.mailing_date')}
                </dt>
                <dd className="font-mono text-slate-700 dark:text-slate-200">
                  {fmt(ds.mailing_date)}
                </dd>
              </div>
            )}
            {ds.start_date && (
              <div className="flex gap-1" data-testid="deadline-start">
                <dt className="text-slate-400 dark:text-slate-500">
                  {t('deadline_detail.start_date')}
                </dt>
                <dd className="text-slate-700 dark:text-slate-200">
                  <span className="font-mono">{fmt(ds.start_date)}</span>
                  {basisKey && <span className="ml-1">（{t(basisKey)}）</span>}
                </dd>
              </div>
            )}
            {ds.period_applied && (
              <div className="flex gap-1">
                <dt className="text-slate-400 dark:text-slate-500">{t('deadline_detail.period')}</dt>
                <dd className="text-slate-700 dark:text-slate-200">{ds.period_applied}</dd>
              </div>
            )}
            <div className="flex gap-1">
              <dt className="text-slate-400 dark:text-slate-500">{t('analyze.result.received')}</dt>
              <dd className="font-mono text-slate-700 dark:text-slate-200">
                {fmt(ds.received_date)}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-slate-400 dark:text-slate-500">
                {t('analyze.result.statutory')}
              </dt>
              <dd className="font-mono text-slate-700 dark:text-slate-200">
                {fmt(ds.statutory_deadline)}
              </dd>
            </div>
            {ds.recommended_internal_deadline && (
              <div className="flex gap-1">
                <dt className="text-slate-400 dark:text-slate-500">
                  {t('analyze.result.internal')}
                </dt>
                <dd className="font-mono text-slate-700 dark:text-slate-200">
                  {fmt(ds.recommended_internal_deadline)}
                </dd>
              </div>
            )}
            {ds.holiday_calendar_version && (
              <div className="flex gap-1">
                <dt className="text-slate-400 dark:text-slate-500">
                  {t('analyze.result.calendar')}
                </dt>
                <dd className="font-mono text-slate-700 dark:text-slate-200">
                  {ds.holiday_calendar_version}
                </dd>
              </div>
            )}
          </dl>
          {warnings.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-amber-700 dark:text-amber-300">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          {/* 期日 .ics 匯出 — 律師的真實行事曆在 Outlook/Google，不在本系統。
              純前端 Blob 下載，零資料外流。 */}
          <div className="mt-2">
            <Button
              type="button"
              variant="secondary"
              size="xs"
              data-testid="deadline-ics-export"
              onClick={() => {
                const ok = downloadDeadlineIcs({ caseId, deadline: ds, t });
                if (ok) toast.success(t('analyze.ics.downloaded'));
                else toast.error(t('analyze.ics.no_deadline'));
              }}
              className="gap-1.5"
            >
              <CalendarPlus className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
              {t('analyze.ics.button')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function MobileTabBar({ activeTab, setActiveTab, hasResult }) {
  const { t } = useTranslation();
  const tabs = [
    { id: 'input', label: t('analyze.result.tab_input') },
    { id: 'drafts', label: t('analyze.result.tab_drafts'), disabled: !hasResult },
    { id: 'refs', label: t('analyze.result.tab_refs'), disabled: !hasResult },
  ];
  return (
    <div
      className="sticky top-0 z-10 flex border-b bg-white/95 backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900/95"
      role="tablist"
      aria-label={t('analyze.pane_input')}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => !tab.disabled && setActiveTab(tab.id)}
            disabled={tab.disabled}
            className={`flex-1 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-navy-500 ${
              isActive
                ? 'border-navy-600 text-navy-700 dark:text-navy-200'
                : tab.disabled
                  ? 'cursor-not-allowed border-transparent text-slate-300 dark:text-slate-600'
                  : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
