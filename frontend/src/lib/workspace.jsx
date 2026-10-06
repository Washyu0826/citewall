/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router';

import { api } from '../api/client.js';
import { Button } from '../components/ui/button.jsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../components/ui/overlay.jsx';
import { useCurrentCase } from './currentCase.jsx';
import { queryClient } from './queryClient.js';
import { toast } from './toast.jsx';
import { dropCaseBound, hasUnsavedDecisions } from './workspaceState.js';

/**
 * The analysis workspace's state, held ABOVE the routes (research 09 FE-L1).
 *
 * It used to live in the workspace page itself: going to the dashboard and
 * back dropped the result, every sentence decision and the running analysis
 * (whose result then landed nowhere), and the form invited a second submit.
 * Here it survives navigation for the whole session — in memory only, like
 * the current case (never the URL or localStorage: shared workstations).
 * The provider is keyed by user in App.jsx, so a logout clears it.
 *
 * Also owns:
 *   - the running analysis, with cancel (an AbortSignal into `call()`);
 *   - the case binding: everything here belongs to ONE case. A case switch
 *     drops it in the same render as the switch, and late answers for the
 *     old case (analysis, preview, export) are dropped, not stored under the
 *     new one (`setCaseBound`);
 *   - the discard question (UX-5): re-analysing, switching case or logging
 *     out with unsaved sentence decisions — or switching away from a running
 *     analysis — asks first; the browser warns before the tab is closed.
 *
 * Two contexts: the actions are stable, so components that only act (the
 * shell's logout) do not re-render on every keystroke in the workspace.
 */
const WorkspaceStateContext = createContext(null);
const WorkspaceActionsContext = createContext(null);

const WORKSPACE_PATH = '/analyze';

export function WorkspaceProvider({ children }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { caseId, setCaseChangeGuard } = useCurrentCase();
  const [fields, setFields] = useState({});
  const [run, setRun] = useState(null); // { caseId, startedAt } while an analysis is in flight
  const [question, setQuestion] = useState(null); // { id, kind } — the open discard question

  const controllerRef = useRef(null);
  const runRef = useRef(null);
  const aliveRef = useRef(true);
  const caseRef = useRef(caseId);
  const pathRef = useRef(pathname);
  const fieldsRef = useRef(fields);
  const questionRef = useRef(null); // { id, resolve } — kept out of state (see `ask`)
  const questionSeq = useRef(0);
  // Layout effects: they run in the same commit as the change, before any
  // network continuation reads them (the B-12 lesson, review V-F1).
  useLayoutEffect(() => {
    caseRef.current = caseId;
  }, [caseId]);
  useLayoutEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);
  useLayoutEffect(() => {
    fieldsRef.current = fields;
  }, [fields]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      // Logout / user switch: stop waiting; nothing may land in a dead tree,
      // and an open question must not leave its caller waiting forever.
      aliveRef.current = false;
      controllerRef.current?.abort();
      questionRef.current?.resolve(false);
      questionRef.current = null;
    };
  }, []);

  const setField = useCallback((name, next, fallback) => {
    setFields((f) => {
      const prev = Object.prototype.hasOwnProperty.call(f, name) ? f[name] : fallback;
      const value = typeof next === 'function' ? next(prev) : next;
      if (Object.prototype.hasOwnProperty.call(f, name) && Object.is(value, f[name])) return f;
      return { ...f, [name]: value };
    });
  }, []);

  /** Set a field only if `forCase` is still the open case — for answers
   * that arrive after an await (redaction preview, export receipt). */
  const setCaseBound = useCallback(
    (forCase, name, value) => {
      if (aliveRef.current && caseRef.current === forCase) setField(name, value);
    },
    [setField]
  );

  // The promise's resolver lives in a ref, not in state: React may run state
  // updaters twice (StrictMode), and resolving belongs outside them.
  const ask = useCallback(
    (kind) =>
      new Promise((resolve) => {
        questionRef.current?.resolve(false); // a newer question replaces an unanswered one
        questionSeq.current += 1;
        const id = questionSeq.current;
        questionRef.current = { id, resolve };
        // Open on the next tick: the switch / logout usually comes from a
        // Radix DropdownMenu item, and a Dialog opened while the menu is
        // still closing can leave `pointer-events: none` on <body>.
        setTimeout(() => {
          if (aliveRef.current && questionRef.current?.id === id) setQuestion({ id, kind });
        }, 0);
      }),
    []
  );
  const answer = useCallback((ok) => {
    const open = questionRef.current;
    questionRef.current = null;
    setQuestion(null);
    open?.resolve(ok);
  }, []);

  /** Resolves true when it is fine to throw the current result away. Logging
   * out also abandons a running analysis — asked about too (review W2b-R4). */
  const confirmDiscard = useCallback(
    (kind) => {
      if (hasUnsavedDecisions(fieldsRef.current)) return ask(kind);
      if (kind === 'logout' && runRef.current) return ask('logout_running');
      return Promise.resolve(true);
    },
    [ask]
  );

  useEffect(() => {
    setCaseChangeGuard({
      // Synchronous `true` when there is nothing to lose: the switch then
      // happens exactly as before (see currentCase.jsx).
      guard: (next) => {
        if (runRef.current && runRef.current.caseId !== next) return ask('switch_case_running');
        return hasUnsavedDecisions(fieldsRef.current) ? ask('switch_case') : true;
      },
      // Runs in the same event as the switch, so the old case's result is
      // never rendered under the new case (review W2b-D8).
      onSwitch: (next) => {
        // Now, not at the next commit: a late answer for the old case that
        // arrives between the switch and the render must already be refused
        // by setCaseBound (review W2b-R3).
        caseRef.current = next;
        setFields(dropCaseBound);
        if (runRef.current && runRef.current.caseId !== next) {
          // The analysis belongs to the case being left: stop waiting for it
          // (its result could only be dropped — FAILURE_LOG B-12).
          controllerRef.current?.abort('case_switch');
        }
      },
    });
    return () => setCaseChangeGuard(null);
  }, [setCaseChangeGuard, ask]);

  const unsaved = hasUnsavedDecisions(fields);
  useEffect(() => {
    if (!unsaved) return undefined;
    // The browser shows its own generic "leave site?" prompt.
    const onBeforeUnload = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [unsaved]);

  const startAnalysis = useCallback(
    async (token, payload) => {
      const requestedCase = payload.case_id;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      runRef.current = { caseId: requestedCase, startedAt: Date.now() };
      setRun(runRef.current);
      setFields((f) => ({ ...dropCaseBound(f) }));
      const current = () => aliveRef.current && controllerRef.current === controller;
      try {
        const r = await api.analyze(token, payload, { signal: controller.signal });
        if (!current()) return; // superseded, cancelled after the answer arrived, or logged out
        queryClient.invalidateQueries({ queryKey: ['quota'] });
        queryClient.invalidateQueries({ queryKey: ['cases'] });
        // The case was switched while the analysis ran: this result belongs
        // to the old case. Showing it would let it be signed off and exported
        // under the new case id (FAILURE_LOG B-12) — drop it and say so.
        if (caseRef.current !== requestedCase) {
          toast.info(t('workspace.result_discarded', { id: requestedCase }));
          return;
        }
        setFields((f) => ({ ...f, result: r }));
        if (pathRef.current !== WORKSPACE_PATH) {
          toast.success(t('workspace.analysis_done', { id: requestedCase }));
        }
      } catch (e) {
        if (!aliveRef.current) return;
        if (e?.cancelled) {
          if (controllerRef.current !== controller) return; // superseded by a newer run
          // The server still finishes (and counts) it: refresh the usage.
          queryClient.invalidateQueries({ queryKey: ['quota'] });
          queryClient.invalidateQueries({ queryKey: ['cases'] });
          toast.info(
            controller.signal.reason === 'case_switch'
              ? t('workspace.result_discarded', { id: requestedCase })
              : t('workspace.analysis_cancelled')
          );
          return;
        }
        if (current() && caseRef.current === requestedCase) setFields((f) => ({ ...f, error: e }));
      } finally {
        if (aliveRef.current && controllerRef.current === controller) {
          controllerRef.current = null;
          runRef.current = null;
          setRun(null);
        }
      }
    },
    [t]
  );

  const cancelAnalysis = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const actions = useMemo(
    () => ({ setField, setCaseBound, startAnalysis, cancelAnalysis, confirmDiscard }),
    [setField, setCaseBound, startAnalysis, cancelAnalysis, confirmDiscard]
  );
  const state = useMemo(() => ({ fields, run }), [fields, run]);

  return (
    <WorkspaceActionsContext.Provider value={actions}>
      <WorkspaceStateContext.Provider value={state}>
        {children}
        {/* One Dialog instance per question (keyed, unmounted when answered):
            reopening a reused Dialog right after closing it left the previous
            open overlay covering the new one (CI, wave 2b). */}
        {question && (
          <Dialog key={question.id} open onOpenChange={(open) => !open && answer(false)}>
            <DialogContent closeLabel={t('workspace.discard.keep')}>
              <DialogHeader>
                <DialogTitle>{t('workspace.discard.title')}</DialogTitle>
                <DialogDescription>{t(`workspace.discard.${question.kind}`)}</DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => answer(false)} data-testid="discard-keep">
                  {t('workspace.discard.keep')}
                </Button>
                <Button variant="destructive" onClick={() => answer(true)} data-testid="discard-confirm">
                  {t('workspace.discard.confirm')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </WorkspaceStateContext.Provider>
    </WorkspaceActionsContext.Provider>
  );
}

/** Stable actions only — never re-renders the caller on workspace changes. */
export function useWorkspaceActions() {
  const ctx = useContext(WorkspaceActionsContext);
  if (!ctx) throw new Error('useWorkspaceActions must be used inside <WorkspaceProvider>');
  return ctx;
}

/** State and actions (the workspace page). */
export function useWorkspace() {
  const state = useContext(WorkspaceStateContext);
  const actions = useContext(WorkspaceActionsContext);
  if (!state || !actions) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return { ...state, ...actions };
}

/**
 * Drop-in for `useState` whose value lives in the workspace (survives
 * navigation). `initial` is used until the field is first set.
 */
export function useWorkspaceField(name, initial) {
  const { fields } = useContext(WorkspaceStateContext);
  const { setField } = useWorkspaceActions();
  const initialRef = useRef(initial);
  const value = Object.prototype.hasOwnProperty.call(fields, name) ? fields[name] : initialRef.current;
  const set = useCallback((next) => setField(name, next, initialRef.current), [name, setField]);
  return [value, set];
}
