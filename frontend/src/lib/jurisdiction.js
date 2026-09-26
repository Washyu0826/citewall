// Mirror of backend/gateway/orchestrator.py::_jurisdiction_for_patent — the
// SPA needs the same derivation to decide which deadline caveats to show
// (the deadline payload itself carries no jurisdiction). Keep in sync.

const KNOWN = new Set(['US', 'TW', 'EP', 'JP', 'CN', 'KR']);

/** Leading ASCII letters (first two) of the patent number; unknown/WO → 'TW'. */
export function jurisdictionForPatent(patentNo) {
  if (!patentNo) return 'TW';
  const code = (String(patentNo).trim().toUpperCase().match(/^[A-Z]+/)?.[0] || '').slice(0, 2);
  return KNOWN.has(code) ? code : 'TW';
}
