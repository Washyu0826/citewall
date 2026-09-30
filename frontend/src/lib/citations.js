// Q14 citation-pill resolution.
//
// The backend numbers [GROUNDED_REF_n] PER REJECTION (1-based into that
// rejection's grounded set) and tags each hit in `related_prior_art` with
// metadata.rejection_id / metadata.ref_index. The lookup therefore has to be
// per rejection: indexing the flattened list resolves every rejection after
// the first to the wrong patent. Hits without the tag (an older gateway) are
// indexed by position under the '*' fallback key, capped at 20 like before.

export const FALLBACK_KEY = '*';

/** @returns {{[rejectionId: string]: {[ref: string]: object}}} */
export function buildCitationLookup(relatedPriorArt) {
  const out = {};
  const fallback = {};
  (relatedPriorArt || []).forEach((h, i) => {
    const rid = h?.metadata?.rejection_id;
    const n = h?.metadata?.ref_index;
    if (rid && n) {
      (out[rid] ||= {})[`[GROUNDED_REF_${n}]`] = h;
    } else if (i < 20) {
      fallback[`[GROUNDED_REF_${i + 1}]`] = h;
    }
  });
  out[FALLBACK_KEY] = fallback;
  return out;
}

/** The {[GROUNDED_REF_n]: hit} map for one rejection (falls back to '*'). */
export function lookupForRejection(lookup, rejectionId) {
  return lookup?.[rejectionId] || lookup?.[FALLBACK_KEY] || {};
}

/**
 * The retrieval hits that ground ONE rejection's draft, in [GROUNDED_REF_n]
 * order, each flagged with whether the examiner also cited that patent.
 *
 * The references panel used to show only hits whose patent the examiner had
 * cited — so a draft's [GROUNDED_REF_n] often pointed at a passage the panel
 * never displayed. Grounding is per rejection (metadata.rejection_id), so the
 * panel must be too. Untagged hits (older gateway) fall back to the cited
 * filter.
 */
export function hitsForRejection(result, rejectionId) {
  const rejection = (result?.oa?.rejections || []).find((r) => r.rejection_id === rejectionId);
  const cited = new Set(rejection?.cited_prior_art || []);
  const all = result?.related_prior_art || [];
  const tagged = all.some((h) => h?.metadata?.rejection_id);
  const hits = tagged
    ? all
        .filter((h) => h?.metadata?.rejection_id === rejectionId)
        .sort((a, b) => (a.metadata.ref_index || 0) - (b.metadata.ref_index || 0))
    : all.filter((h) => cited.has(h.patent_no));
  return hits.map((h) => ({ ...h, examinerCited: cited.has(h.patent_no) }));
}
