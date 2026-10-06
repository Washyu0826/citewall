/**
 * Pure helpers for the analysis workspace state (lib/workspace.jsx).
 * Unit tested in workspaceState.test.js.
 */

/**
 * Fields that belong to one case's analysis: dropped when the case changes
 * or a new analysis starts. The typed inputs (OA text, patent number, deadline
 * facts) are deliberately NOT here — the workspace always kept them across a
 * case switch, so picking the wrong case first costs nothing.
 */
export const CASE_BOUND_FIELDS = [
  'result',
  'error',
  'redactPreview',
  'editing',
  'progress',
  'editors',
  'responseExport',
  'exportsInFlight',
  'activeRejectionId',
];

export function dropCaseBound(fields) {
  if (!CASE_BOUND_FIELDS.some((k) => k in fields)) return fields;
  const next = { ...fields };
  for (const k of CASE_BOUND_FIELDS) delete next[k];
  return next;
}

const touched = (lines) =>
  lines.some((l) => l?.status !== 'pending' || (l?.source && l.source !== 'ai_generated'));

/**
 * Whether throwing the result away would lose the attorney's work (research
 * 09 UX-5): a rejection with any sentence accepted, excluded, edited or added
 * whose CURRENT sentences were not exported — neither by that rejection's own
 * export nor by the whole-response export. Sentences changed after an export
 * count again (the exported snapshot is compared by identity: every change
 * makes a new `lines` array).
 */
export function hasUnsavedDecisions(fields) {
  if (!fields?.result) return false;
  const editors = fields.editors && typeof fields.editors === 'object' ? Object.entries(fields.editors) : [];
  const responseLines = fields.responseExport?.linesByRejection ?? null;
  return editors.some(([rid, e]) => {
    if (!e || !Array.isArray(e.lines) || !touched(e.lines)) return false;
    const exportedAlone = e.exportedLines != null && e.exportedLines === e.lines;
    const exportedInResponse = responseLines != null && responseLines[rid] === e.lines;
    return !(exportedAlone || exportedInResponse);
  });
}

/**
 * A per-rejection export receipt, merged into the editors map (review
 * W2b-R1): only the receipt and the sentences it covered are set on the
 * CURRENT entry — sentences the attorney changed while the export ran stay,
 * and count as unsaved (they are not the exported array). An entry for a
 * DIFFERENT draft is newer work than the export and is never overwritten
 * (review W2b-S1); with no entry at all, what was exported is recorded.
 */
export function mergeReceipt(editors, rejectionId, { draft, exportResult, exportedLines }) {
  const cur = editors?.[rejectionId];
  if (cur && cur.draft !== draft) return editors;
  const merged = cur
    ? { ...cur, exportResult, exportedLines }
    : { draft, lines: exportedLines, reviewed: true, exportResult, exportedLines };
  return { ...(editors ?? {}), [rejectionId]: merged };
}
