/**
 * Pure helpers over the GET /v1/cases payload — shared by the dashboard and
 * the case list, unit-tested in cases.test.js.
 *
 * A case row: { case_id, security_level, last_activity, last_analysis|null }
 * last_analysis: { statutory_deadline, recommended_deadline, jurisdiction,
 *                  rejection_types[], affected_claims[], rejection_count,
 *                  draft_count, analyzed_at, analyzed_by, model_used, degraded }
 */

/** Deadlines within this many days are flagged "due soon". */
export const DUE_SOON_DAYS = 14;

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Whole calendar days from `now` to `iso` (negative = past). null if no date. */
export function daysUntil(iso, now = new Date()) {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  return Math.round((startOfDay(target) - startOfDay(now)) / DAY_MS);
}

/** Badge tone for a deadline `days` away. */
export function deadlineTone(days) {
  if (days === null || days === undefined) return 'neutral';
  if (days < 0) return 'error';
  if (days <= DUE_SOON_DAYS) return 'warning';
  return 'neutral';
}

/** Anything other than an explicit "public" stays on-prem (fail-closed, Q22). */
export function isConfidentialLevel(level) {
  return level !== 'public';
}

/** 'not_analyzed' | 'degraded' | 'analyzed' */
export function caseStatus(row) {
  if (!row?.last_analysis) return 'not_analyzed';
  if (row.last_analysis.degraded) return 'degraded';
  return 'analyzed';
}

export function statutoryDeadline(row) {
  return row?.last_analysis?.statutory_deadline || null;
}

/** Cases that have a deadline, soonest first (overdue ones lead). */
export function upcomingDeadlines(cases, now = new Date()) {
  return (cases || [])
    .filter((c) => statutoryDeadline(c))
    .map((c) => ({ ...c, days: daysUntil(statutoryDeadline(c), now) }))
    .sort((a, b) => a.days - b.days);
}

export function dashboardStats(cases, now = new Date()) {
  const rows = cases || [];
  let dueSoon = 0;
  let overdue = 0;
  for (const c of rows) {
    const d = daysUntil(statutoryDeadline(c), now);
    if (d === null) continue;
    if (d < 0) overdue += 1;
    else if (d <= DUE_SOON_DAYS) dueSoon += 1;
  }
  return {
    total: rows.length,
    dueSoon,
    overdue,
    confidential: rows.filter((c) => isConfidentialLevel(c.security_level)).length,
    notAnalyzed: rows.filter((c) => caseStatus(c) === 'not_analyzed').length,
  };
}

export const CASE_FILTERS = ['all', 'due_soon', 'not_analyzed', 'confidential'];

export function filterCases(cases, { query = '', filter = 'all' } = {}, now = new Date()) {
  const q = query.trim().toLowerCase();
  return (cases || []).filter((c) => {
    if (q && !c.case_id.toLowerCase().includes(q)) return false;
    switch (filter) {
      case 'due_soon': {
        const d = daysUntil(statutoryDeadline(c), now);
        return d !== null && d <= DUE_SOON_DAYS;
      }
      case 'not_analyzed':
        return caseStatus(c) === 'not_analyzed';
      case 'confidential':
        return isConfidentialLevel(c.security_level);
      default:
        return true;
    }
  });
}

/** Local calendar date, e.g. 2025/07/28 — dates only, never times, in lists. */
export function formatDate(iso, locale = 'zh-TW') {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(locale, { year: 'numeric', month: '2-digit', day: '2-digit' });
}
