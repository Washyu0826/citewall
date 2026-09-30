/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState } from 'react';

/**
 * The case the user is working on, shared by the shell's case switcher, the
 * dashboard, the case list and the analysis workspace.
 *
 * Held in memory only — deliberately NOT in the URL (CLAUDE.md §9: case ids
 * must not end up in browser history, proxy or server logs) and not in
 * localStorage (the next user of a shared workstation must not inherit it).
 */
const CurrentCaseContext = createContext({ caseId: '', setCaseId: () => {} });

export function CurrentCaseProvider({ children, initial = '' }) {
  const [caseId, setCaseId] = useState(initial);
  const value = useMemo(() => ({ caseId, setCaseId }), [caseId]);
  return <CurrentCaseContext.Provider value={value}>{children}</CurrentCaseContext.Provider>;
}

export function useCurrentCase() {
  return useContext(CurrentCaseContext);
}
