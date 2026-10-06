/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

/**
 * The case the user is working on, shared by the shell's case switcher, the
 * dashboard, the case list and the analysis workspace.
 *
 * Held in memory only — deliberately NOT in the URL (CLAUDE.md §9: case ids
 * must not end up in browser history, proxy or server logs) and not in
 * localStorage (the next user of a shared workstation must not inherit it).
 *
 * A switch can be vetoed (research 09 UX-5): the workspace registers
 * `{ guard, onSwitch }` — `guard(next)` returns true (synchronously, when
 * nothing would be lost) or a Promise<boolean> (it asks first); `onSwitch`
 * runs with the switch itself. Every switch — header, dashboard, case list,
 * workspace form — goes through `setCaseId`, so one registration covers them
 * all. `setCaseId` resolves to whether it switched.
 */
const CurrentCaseContext = createContext({
  caseId: '',
  setCaseId: () => Promise.resolve(true),
  setCaseChangeGuard: () => {},
});

export function CurrentCaseProvider({ children, initial = '' }) {
  const [caseId, setCaseIdState] = useState(initial);
  const caseRef = useRef(initial);
  const guardRef = useRef(null);

  const setCaseId = useCallback((next) => {
    if (next === caseRef.current) return Promise.resolve(true);
    const apply = () => {
      caseRef.current = next;
      // The workspace drops the old case's analysis in the SAME update, so it
      // is never rendered under the new case id.
      guardRef.current?.onSwitch?.(next);
      setCaseIdState(next);
    };
    const verdict = guardRef.current?.guard ? guardRef.current.guard(next) : true;
    // Nothing to protect (the usual case): switch synchronously, exactly as
    // before the guard existed — callers often navigate right after.
    if (verdict === true) {
      apply();
      return Promise.resolve(true);
    }
    return Promise.resolve(verdict).then((ok) => {
      if (ok) apply();
      return ok === true;
    });
  }, []);

  const setCaseChangeGuard = useCallback((guard) => {
    guardRef.current = guard;
  }, []);

  const value = useMemo(() => ({ caseId, setCaseId, setCaseChangeGuard }), [caseId, setCaseId, setCaseChangeGuard]);
  return <CurrentCaseContext.Provider value={value}>{children}</CurrentCaseContext.Provider>;
}

export function useCurrentCase() {
  return useContext(CurrentCaseContext);
}
