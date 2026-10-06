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
 *   - the discard question (UX-5): re-analysing, switching case or logging
 *     out with unsaved sentence decisions asks first, and the browser warns
 *     before the tab is closed or reloaded.
 */
const WorkspaceContext = createContext(null);

const WORKSPACE_PATH = '/analyze';

export function WorkspaceProvider({ children }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { caseId, setCaseChangeGuard } = useCurrentCase();
  const [fields, setFields] = useState({});
  const [run, setRun] = useState(null); // { caseId, startedAt } while an analysis is in flight
  const [question, setQuestion] = useState(null); // { kind } — the open discard question

  const controllerRef = useRef(null);
  const aliveRef = useRef(true);
  const caseRef = useRef(caseId);
  const pathRef = useRef(pathname);
  const fieldsRef = useRef(fields);
  const prevCaseRef = useRef(caseId);
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
      // Logout / user switch: stop waiting; nothing may land in a dead tree.
      aliveRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  // The case changed — from anywhere (header, dashboard, case list, the
  // form): the result, preview, error and decisions belong to the old case.
  useEffect(() => {
    if (prevCaseRef.current === caseId) return;
    prevCaseRef.current = caseId;
    setFields(dropCaseBound);
  }, [caseId]);

  const setField = useCallback((name, next, fallback) => {
    setFields((f) => {
      const prev = Object.prototype.hasOwnProperty.call(f, name) ? f[name] : fallback;
      const value = typeof next === 'function' ? next(prev) : next;
      if (Object.prototype.hasOwnProperty.call(f, name) && Object.is(value, f[name])) return f;
      return { ...f, [name]: value };
    });
  }, []);

  // The promise's resolver lives in a ref, not in state: React may run state
  // updaters twice (StrictMode), and resolving belongs outside them.
  const questionRef = useRef(null);
  const ask = useCallback(
    (kind) =>
      new Promise((resolve) => {
        questionRef.current?.resolve(false); // a newer question replaces an unanswered one
        questionRef.current = { resolve };
        // Open on the next tick: the switch / logout usually comes from a
        // Radix DropdownMenu item, and a Dialog opened while the menu is
        // still closing can leave `pointer-events: none` on <body> after it
        // closes (a known Radix interaction).
        setTimeout(() => {
          if (aliveRef.current && questionRef.current?.resolve === resolve) setQuestion({ kind });
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

  /** Resolves true when it is fine to throw the current result away. */
  const confirmDiscard = useCallback(
    (kind) => (hasUnsavedDecisions(fieldsRef.current) ? ask(kind) : Promise.resolve(true)),
    [ask]
  );

  useEffect(() => {
    // Synchronous `true` when there is nothing to lose: the switch then
    // happens exactly as before (see currentCase.jsx).
    setCaseChangeGuard(() => (hasUnsavedDecisions(fieldsRef.current) ? ask('switch_case') : true));
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
      setRun({ caseId: requestedCase, startedAt: Date.now() });
      setFields((f) => ({ ...dropCaseBound(f) }));
      try {
        const r = await api.analyze(token, payload, { signal: controller.signal });
        if (!aliveRef.current) return;
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
          if (controllerRef.current === controller) toast.info(t('workspace.analysis_cancelled'));
          return;
        }
        if (caseRef.current === requestedCase) setFields((f) => ({ ...f, error: e }));
      } finally {
        if (aliveRef.current && controllerRef.current === controller) {
          controllerRef.current = null;
          setRun(null);
        }
      }
    },
    [t]
  );

  const cancelAnalysis = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const value = useMemo(
    () => ({ fields, setField, run, startAnalysis, cancelAnalysis, confirmDiscard }),
    [fields, setField, run, startAnalysis, cancelAnalysis, confirmDiscard]
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
      <Dialog open={question !== null} onOpenChange={(open) => !open && answer(false)}>
        <DialogContent closeLabel={t('workspace.discard.keep')}>
          <DialogHeader>
            <DialogTitle>{t('workspace.discard.title')}</DialogTitle>
            <DialogDescription>{t(`workspace.discard.${question?.kind ?? 'rerun'}`)}</DialogDescription>
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
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return ctx;
}

/**
 * Drop-in for `useState` whose value lives in the workspace (survives
 * navigation). `initial` is used until the field is first set.
 */
export function useWorkspaceField(name, initial) {
  const { fields, setField } = useWorkspace();
  const initialRef = useRef(initial);
  const value = Object.prototype.hasOwnProperty.call(fields, name) ? fields[name] : initial;
  const set = useCallback((next) => setField(name, next, initialRef.current), [name, setField]);
  return [value, set];
}
