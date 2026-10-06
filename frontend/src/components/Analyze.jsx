import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { ApiError, api } from '../api/client.js';
import { useCases, useQuota } from '../api/queries.js';
import { buildCitationLookup, lookupForRejection } from '../lib/citations.js';
import { useCurrentCase } from '../lib/currentCase.jsx';
import { buildDeadlineRequestFields } from '../lib/deadlineInputs.js';
import { tablesForRejection } from '../lib/elementTable.js';
import { normalizeRedactionPreview } from '../lib/normalize.js';
import { toast } from '../lib/toast.jsx';
import { useMediaQuery } from '../lib/useMediaQuery.js';
import { useWorkspace, useWorkspaceField } from '../lib/workspace.jsx';
import { mergeReceipt } from '../lib/workspaceState.js';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card.jsx';
import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle } from './ui/overlay.jsx';
import { Page, PageHeader } from './ui/page.jsx';
import ReferencesPanel from './analyze/ReferencesPanel.jsx';
import RejectionRail from './analyze/RejectionRail.jsx';
import RejectionReview from './analyze/RejectionReview.jsx';
import ResponseExportCard from './analyze/ResponseExportCard.jsx';
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
const DEFAULT_CASE = 'CASE-2025-001';

/**
 * The analysis workspace: 輸入 OA → 確認遮罩 → 分析 → 逐句審閱 → 簽核匯出.
 *
 * Setup mode (no result, or "edit input"): case, office action, deadline facts,
 * masking preview. Review mode: result header, rejection list with per-rejection
 * sign-off progress, the active rejection's review, and its prior art.
 *
 * The case comes from the shell (in-memory current case — never the URL);
 * `initialCaseId` changes when the user switches case.
 *
 * The workspace's state — inputs, result, sentence decisions, the running
 * analysis — lives above the routes (lib/workspace.jsx, research 09 FE-L1),
 * so leaving this page loses nothing; only transient UI state is local here.
 */
export default function Analyze({ session, onLogout, onTrustChange, initialCaseId }) {
  const { t } = useTranslation();
  const { setCaseId: setCurrentCase } = useCurrentCase();
  const { run, startAnalysis, cancelAnalysis, confirmDiscard, setCaseBound } = useWorkspace();

  const caseId = initialCaseId || DEFAULT_CASE;
  const [oaText, setOaText] = useWorkspaceField('oaText', SAMPLE_OA);
  const [targetPatent, setTargetPatent] = useWorkspaceField('targetPatent', 'US17123456');
  const [result] = useWorkspaceField('result', null);
  const [error, setError] = useWorkspaceField('error', null);
  const [redactPreview] = useWorkspaceField('redactPreview', null);
  const [editing, setEditing] = useWorkspaceField('editing', false);
  const [sourceTab, setSourceTab] = useWorkspaceField('sourceTab', 'paste');
  const [domicile, setDomicile] = useWorkspaceField('domicile', 'unknown');
  const [oaSequence, setOaSequence] = useWorkspaceField('oaSequence', '');
  const [serviceDate, setServiceDate] = useWorkspaceField('serviceDate', '');
  const [loadedMeta, setLoadedMeta] = useWorkspaceField('loadedMeta', null);
  const [uploadWarnings, setUploadWarnings] = useWorkspaceField('uploadWarnings', []);
  const [activeRejectionId, setActiveRejectionId] = useWorkspaceField('activeRejectionId', null);
  const [progress, setProgress] = useWorkspaceField('progress', {});
  const [editors] = useWorkspaceField('editors', {});
  // The whole-response export receipt + the sentences it covered.
  const [responseExport] = useWorkspaceField('responseExport', null);
  const responseExported = responseExport !== null;
  const [previewing, setPreviewing] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [refsOpen, setRefsOpen] = useState(false);
  const isWide = useMediaQuery(WIDE_QUERY);

  const quotaQ = useQuota(session.token);
  const quota = quotaQ.data;
  // Loaded but unusable (or failed): say so instead of a skeleton forever.
  const quotaUnavailable = !quotaQ.isLoading && !quota;
  const casesQ = useCases(session.token);
  const cases = casesQ.data?.cases;
  const securityLevel = cases?.find((c) => c.case_id === caseId)?.security_level;
  // The analysis runs in the workspace provider: it keeps going (and its
  // result is kept) while the attorney is on another page. Shown only for
  // the case it belongs to.
  const running = run !== null && run.caseId === caseId;

  // The analyze button sits at the end of a long form (a screen or two down
  // on a phone); progress and then the result start at the top — show them.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (running && !wasRunning.current) window.scrollTo({ top: 0 });
    wasRunning.current = running;
  }, [running]);

  // Opened with no current case: publish the workspace default so the top-bar
  // switcher, the trust band and this page all name the same case (B-6).
  useEffect(() => {
    if (!initialCaseId) setCurrentCase(DEFAULT_CASE);
  }, [initialCaseId, setCurrentCase]);

  useEffect(() => {
    if (typeof onTrustChange !== 'function') return;
    onTrustChange({ caseId, maskedEntityCount: result?.redaction_summary?.masked_entity_count ?? 0 });
  }, [onTrustChange, caseId, result]);

  const rejections = useMemo(() => result?.oa?.rejections || [], [result]);

  // NB: progress is reset in runAnalyze, BEFORE the new result renders — a
  // reset here would run after the DraftEditors' mount-time reports (child
  // effects fire first) and wipe them.
  // Keep the rejection the attorney was on when they come back to the page;
  // a new result starts at its first rejection.
  useEffect(() => {
    setActiveRejectionId((cur) =>
      rejections.some((r) => r.rejection_id === cur) ? cur : (rejections[0]?.rejection_id ?? null)
    );
  }, [rejections, setActiveRejectionId]);

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
    [rejections, setProgress]
  );

  // Each rejection's sentence decisions, saved in the workspace (FE-L1).
  const saveHandlers = useMemo(
    () =>
      Object.fromEntries(
        // Case-bound: an export that completes after a switch (the editor
        // reports its receipt even when unmounted) must not land in the new
        // case's workspace.
        rejections.map((r) => [
          r.rejection_id,
          (state) => setCaseBound(caseId, 'editors', (prev) => ({ ...(prev ?? {}), [r.rejection_id]: state })),
        ])
      ),
    [rejections, setCaseBound, caseId]
  );

  // A per-rejection export's receipt, merged into the CURRENT entry (the
  // editor that started it may be gone, and sentences changed meanwhile must
  // survive — review W2b-R1), and its in-flight flag, which a remounted editor
  // reads so it cannot start a second sign-off (W2b-R2). Both case-bound.
  const receiptHandlers = useMemo(
    () =>
      Object.fromEntries(
        rejections.map((r) => [
          r.rejection_id,
          (receipt) => setCaseBound(caseId, 'editors', (prev) => mergeReceipt(prev, r.rejection_id, receipt)),
        ])
      ),
    [rejections, setCaseBound, caseId]
  );
  const [exportsInFlight] = useWorkspaceField('exportsInFlight', {});
  const exportStateHandlers = useMemo(
    () =>
      Object.fromEntries(
        rejections.map((r) => [
          r.rejection_id,
          (busy) =>
            setCaseBound(caseId, 'exportsInFlight', (prev) => ({ ...(prev ?? {}), [r.rejection_id]: busy })),
        ])
      ),
    [rejections, setCaseBound, caseId]
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
    const requestedCase = caseId;
    setPreviewing(true);
    try {
      const preview = normalizeRedactionPreview(await api.redactionPreview(session.token, oaText, requestedCase));
      // A preview without the masked text is not "nothing to mask": on the
      // privacy step it must read as a failure (review W2b-E4).
      if (!preview) throw new ApiError(502, 'unexpected redaction preview response');
      // Case-bound, checked in the workspace: the attorney may have opened
      // another case (from any page) while this was in flight (W2b-D1).
      setCaseBound(requestedCase, 'redactPreview', preview);
    } catch (e) {
      setCaseBound(requestedCase, 'error', e);
    } finally {
      setPreviewing(false);
    }
  }

  async function runAnalyze() {
    // UX-5: a new analysis replaces the result and its sentence decisions.
    if (!(await confirmDiscard('rerun'))) return;
    // The provider clears the old result, error and decisions, keeps the
    // inputs, and drops a result that comes back for a case no longer open.
    startAnalysis(session.token, {
      oa_text: oaText,
      case_id: caseId,
      target_patent_no: targetPatent,
      ...buildDeadlineRequestFields({ domicile, oaSequence, serviceDate }),
    });
  }

  const showSetup = !running && (!result || editing);
  const allExported =
    responseExported || (rejections.length > 0 && rejections.every((r) => progress[r.rejection_id]?.exported));
  const step = running ? 'analyze' : !showSetup ? (allExported ? 'export' : 'review') : redactPreview ? 'redact' : 'input';
  const isDegraded = (result?.cost_meta?.model || '').includes('-DEGRADED-');

  return (
    <Page>
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

      {running && <RunningPanel startedAt={run.startedAt} onCancel={cancelAnalysis} />}

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
          quotaUnavailable={quotaUnavailable}
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
                    savedReview={editors[r.rejection_id]}
                    onSaveReview={saveHandlers[r.rejection_id]}
                    onReceipt={receiptHandlers[r.rejection_id]}
                    exportInFlight={exportsInFlight[r.rejection_id] === true}
                    onExportState={exportStateHandlers[r.rejection_id]}
                    onShowReferences={isWide ? null : () => setRefsOpen(true)}
                  />
                </div>
              ))}
              <ResponseExportCard
                session={session}
                caseId={caseId}
                rejections={rejections}
                progress={progress}
                degraded={isDegraded}
                savedResult={responseExport?.result}
                inFlight={exportsInFlight.response === true}
                onExportState={(busy) =>
                  setCaseBound(caseId, 'exportsInFlight', (prev) => ({ ...(prev ?? {}), response: busy }))
                }
                onExported={(res) =>
                  setCaseBound(caseId, 'responseExport', {
                    result: res,
                    linesByRejection: Object.fromEntries(Object.entries(editors).map(([rid, e]) => [rid, e?.lines])),
                  })
                }
              />
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
