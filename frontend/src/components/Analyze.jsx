import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';

import { api } from '../api/client.js';
import { useAnalyze, useCases, useQuota } from '../api/queries.js';
import { buildCitationLookup, lookupForRejection } from '../lib/citations.js';
import { useCurrentCase } from '../lib/currentCase.jsx';
import { buildDeadlineRequestFields } from '../lib/deadlineInputs.js';
import { tablesForRejection } from '../lib/elementTable.js';
import { toast } from '../lib/toast.jsx';
import { useDebouncedValue } from '../lib/useDebouncedValue.js';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card.jsx';
import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle } from './ui/overlay.jsx';
import { Page, PageHeader } from './ui/page.jsx';
import ReferencesPanel from './analyze/ReferencesPanel.jsx';
import RejectionRail from './analyze/RejectionRail.jsx';
import RejectionReview from './analyze/RejectionReview.jsx';
import ResultHeader from './analyze/ResultHeader.jsx';
import RunningPanel from './analyze/RunningPanel.jsx';
import SetupPanel from './analyze/SetupPanel.jsx';
import Stepper from './analyze/Stepper.jsx';

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

// Three columns only when there is room for the drafts to breathe (UX_REVIEW
// W4: 1366×768 was cramped); below this the references open in a dialog.
const WIDE_QUERY = '(min-width: 1536px)';

/**
 * The analysis workspace: 輸入 OA → 確認遮罩 → 分析 → 逐句審閱 → 簽核匯出.
 *
 * Setup mode (no result, or "edit input"): case, office action, deadline facts,
 * masking preview. Review mode: result header, rejection list with per-rejection
 * sign-off progress, the active rejection's review, and its prior art.
 *
 * The case comes from the shell (in-memory current case — never the URL);
 * `initialCaseId` changes when the user switches case.
 */
export default function Analyze({ session, onLogout, onTrustChange, initialCaseId }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { setCaseId: setCurrentCase } = useCurrentCase();

  const [oaText, setOaText] = useState(SAMPLE_OA);
  const [caseId, setCaseId] = useState(initialCaseId || 'CASE-2025-001');
  const [targetPatent, setTargetPatent] = useState('US17123456');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [redactPreview, setRedactPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [sourceTab, setSourceTab] = useState('paste');
  const [domicile, setDomicile] = useState('unknown');
  const [oaSequence, setOaSequence] = useState('');
  const [serviceDate, setServiceDate] = useState('');
  const [loadedMeta, setLoadedMeta] = useState(null);
  const [uploadWarnings, setUploadWarnings] = useState([]);
  const [activeRejectionId, setActiveRejectionId] = useState(null);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [refsOpen, setRefsOpen] = useState(false);
  const [progress, setProgress] = useState({});
  const isWide = useMediaQuery(WIDE_QUERY);

  const quotaCaseId = useDebouncedValue(caseId, 400);
  const { data: quota } = useQuota(session.token, quotaCaseId);
  const casesQ = useCases(session.token);
  const cases = casesQ.data?.cases;
  const securityLevel = cases?.find((c) => c.case_id === caseId)?.security_level;
  const analyzeMut = useAnalyze(session.token);
  const running = analyzeMut.isPending;

  // The shell switched case: follow it, keep the typed OA, drop the old result.
  useEffect(() => {
    if (!initialCaseId) return;
    setCaseId(initialCaseId);
    setResult(null);
    setRedactPreview(null);
    setEditing(false);
  }, [initialCaseId]);

  useEffect(() => {
    if (typeof onTrustChange !== 'function') return;
    onTrustChange({ caseId, maskedEntityCount: result?.redaction_summary?.masked_entity_count ?? 0 });
  }, [onTrustChange, caseId, result]);

  const rejections = useMemo(() => result?.oa?.rejections || [], [result]);

  useEffect(() => {
    setProgress({});
    setActiveRejectionId(rejections[0]?.rejection_id ?? null);
  }, [rejections]);

  // Stable per-rejection callbacks so DraftEditor's progress effect doesn't loop.
  const progressHandlers = useMemo(
    () =>
      Object.fromEntries(
        rejections.map((r) => [
          r.rejection_id,
          // DraftEditor only reports when its lines / export state change, so
          // storing every report cannot loop.
          (p) => setProgress((prev) => ({ ...prev, [r.rejection_id]: p })),
        ])
      ),
    [rejections]
  );

  const citationLookup = useMemo(() => (result ? buildCitationLookup(result.related_prior_art) : {}), [result]);

  const handleCitationClick = useCallback(
    (citation) => {
      setSelectedCitation(citation);
      if (!isWide) setRefsOpen(true);
    },
    [isWide]
  );

  function handleExtractSuccess(payload) {
    setOaText(payload.extracted_text || '');
    setLoadedMeta({ fileName: payload.fileName, pages: payload.page_count });
    setUploadWarnings(Array.isArray(payload.warnings) ? payload.warnings : []);
    setSourceTab('paste');
    toast.success(t('upload.toast_success', { pages: payload.page_count ?? 0 }));
  }

  async function previewRedaction() {
    setPreviewing(true);
    try {
      setRedactPreview(await api.redactionPreview(session.token, oaText, caseId));
    } catch (e) {
      setError(e);
    } finally {
      setPreviewing(false);
    }
  }

  async function runAnalyze() {
    setError(null);
    setResult(null);
    setEditing(false);
    try {
      const r = await analyzeMut.mutateAsync({
        oa_text: oaText,
        case_id: caseId,
        target_patent_no: targetPatent,
        ...buildDeadlineRequestFields({ domicile, oaSequence, serviceDate }),
      });
      setResult(r);
      queryClient.invalidateQueries({ queryKey: ['quota', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
    } catch (e) {
      setError(e);
    }
  }

  const showSetup = !running && (!result || editing);
  const allExported = rejections.length > 0 && rejections.every((r) => progress[r.rejection_id]?.exported);
  const step = running ? 'analyze' : !showSetup ? (allExported ? 'export' : 'review') : redactPreview ? 'redact' : 'input';
  const isDegraded = (result?.cost_meta?.model || '').includes('-DEGRADED-');

  return (
    <Page className="max-w-[1920px]" width="full">
      <PageHeader
        title={t('workspace.title')}
        actions={
          editing && result ? (
            <button type="button" className="text-sm font-medium text-fg-link hover:underline" onClick={() => setEditing(false)}>
              {t('workspace.back_to_result')}
            </button>
          ) : null
        }
      />
      <div className="mb-6">
        <Stepper current={step} />
      </div>

      {running && <RunningPanel />}

      {showSetup && (
        <SetupPanel
          caseId={caseId}
          cases={cases}
          onChangeCase={(id) => setCurrentCase(id)}
          targetPatent={targetPatent}
          setTargetPatent={setTargetPatent}
          domicile={domicile}
          setDomicile={setDomicile}
          oaSequence={oaSequence}
          setOaSequence={setOaSequence}
          serviceDate={serviceDate}
          setServiceDate={setServiceDate}
          oaText={oaText}
          setOaText={setOaText}
          sourceTab={sourceTab}
          setSourceTab={setSourceTab}
          loadedMeta={loadedMeta}
          uploadWarnings={uploadWarnings}
          onExtractSuccess={handleExtractSuccess}
          session={session}
          onPreviewRedaction={previewRedaction}
          previewing={previewing}
          onAnalyze={runAnalyze}
          running={running}
          error={error}
          setError={setError}
          onLogout={onLogout}
          redactPreview={redactPreview}
          quota={quota}
        />
      )}

      {result && !running && !editing && (
        <div className="space-y-6">
          {isDegraded && (
            <div role="alert" className="flex items-start gap-3 rounded-brand border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              <span>{t('analyze.degraded_banner')}</span>
            </div>
          )}

          <ResultHeader
            result={result}
            caseId={caseId}
            targetPatent={targetPatent}
            securityLevel={securityLevel}
            onEditInput={() => setEditing(true)}
          />

          <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)] 2xl:grid-cols-[280px_minmax(0,1fr)_380px]">
            <aside className="hidden xl:block">
              <div className="sticky top-4">
                <RejectionRail
                  rejections={rejections}
                  activeId={activeRejectionId}
                  onSelect={setActiveRejectionId}
                  progress={progress}
                  claimTree={result.claim_tree}
                />
              </div>
            </aside>

            <div className="min-w-0 space-y-4">
              {rejections.length > 1 && (
                <div className="xl:hidden">
                  <RejectionRail
                    layout="strip"
                    rejections={rejections}
                    activeId={activeRejectionId}
                    onSelect={setActiveRejectionId}
                    progress={progress}
                  />
                </div>
              )}
              {/* Every rejection stays mounted (inactive ones hidden) so each
                  DraftEditor keeps its sentence decisions across switches. */}
              {rejections.map((r) => (
                <div key={r.rejection_id} hidden={r.rejection_id !== activeRejectionId}>
                  <RejectionReview
                    rejection={r}
                    draft={result.drafts.find((d) => d.rejection_id === r.rejection_id)}
                    citationLookup={lookupForRejection(citationLookup, r.rejection_id)}
                    elementTables={tablesForRejection(result, r.rejection_id)}
                    caseId={caseId}
                    session={session}
                    onCitationClick={handleCitationClick}
                    degraded={isDegraded}
                    onProgress={progressHandlers[r.rejection_id]}
                    onShowReferences={isWide ? null : () => setRefsOpen(true)}
                  />
                </div>
              ))}
            </div>

            {isWide && (
              <aside>
                <Card className="sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto">
                  <CardHeader>
                    <CardTitle>{t('workspace.references')}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ReferencesPanel result={result} activeRejectionId={activeRejectionId} selectedCitation={selectedCitation} />
                  </CardContent>
                </Card>
              </aside>
            )}
          </div>
        </div>
      )}

      {!isWide && result && (
        <Dialog open={refsOpen} onOpenChange={setRefsOpen}>
          <DialogContent wide closeLabel={t('signoff.close')}>
            <DialogHeader>
              <DialogTitle>{t('workspace.references')}</DialogTitle>
            </DialogHeader>
            <DialogBody>
              <ReferencesPanel result={result} activeRejectionId={activeRejectionId} selectedCitation={selectedCitation} />
            </DialogBody>
          </DialogContent>
        </Dialog>
      )}
    </Page>
  );
}

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
