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
  'responseExported',
  'activeRejectionId',
];

export function dropCaseBound(fields) {
  if (!CASE_BOUND_FIELDS.some((k) => k in fields)) return fields;
  const next = { ...fields };
  for (const k of CASE_BOUND_FIELDS) delete next[k];
  return next;
}

/**
 * Whether throwing the result away would lose the attorney's work (research
 * 09 UX-5): any sentence accepted, excluded, edited or added in a rejection
 * not exported yet. Nothing decided, or everything exported → nothing to lose.
 */
export function hasUnsavedDecisions(fields) {
  if (!fields?.result || fields.responseExported) return false;
  const editors = fields.editors && typeof fields.editors === 'object' ? Object.values(fields.editors) : [];
  return editors.some(
    (e) =>
      e &&
      !e.exportResult &&
      Array.isArray(e.lines) &&
      e.lines.some((l) => l?.status !== 'pending' || (l?.source && l.source !== 'ai_generated'))
  );
}
