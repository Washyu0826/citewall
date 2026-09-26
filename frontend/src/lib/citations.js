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
