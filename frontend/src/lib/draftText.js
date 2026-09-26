// Pure draft-text helpers for the Q16 sign-off editor (DraftEditor.jsx).
// Kept free of React so the sentence splitter and the accept/edit gates can be
// unit-tested directly (src/lib/draftText.test.js).

export const CITATION_REMOVED = '[CITATION_REMOVED]';
// Q14/Q17: the verifier's sentence-level alignment rewrites a grounded ref
// whose sentence the cited passage does not support to [UNSUPPORTED_REF_n].
export const UNSUPPORTED_REF_RE = /\[UNSUPPORTED_REF_\d+\]/;

/** Does this text still carry a marker that forbids accepting it as-is? */
export function hasBlockingMarker(text) {
  return text.includes(CITATION_REMOVED) || UNSUPPORTED_REF_RE.test(text);
}

// Western abbreviations that end in "." but do not end a sentence in OA prose.
const NON_TERMINAL_ABBREV =
  /(?:\b(?:U\.S\.C|U\.S|C\.F\.R|No|Nos|Fig|Figs|e\.g|i\.e|al|cf|Art|Sec|para|Ser|Pat|Appl)\.)$/i;

/**
 * Split a draft into reviewable sentences (segments).
 *
 * CJK terminators (。！？) end a sentence with or without following whitespace
 * — zh-TW prose rarely puts a space after 。. Western . ! ? need whitespace and
 * must not be a known abbreviation ("35 U.S.C. § 103", "Patent No. X").
 */
export function splitIntoLines(text) {
  if (!text) return [];
  const out = [];
  let buf = '';
  const re = /([。！？]|[.!?](?=\s))\s*/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    const end = m.index + m[1].length;
    const candidate = buf + text.slice(last, end);
    last = m.index + m[0].length;
    if (m[1] === '.' && NON_TERMINAL_ABBREV.test(candidate)) {
      buf = candidate + text.slice(end, last);
      continue;
    }
    out.push(candidate);
    buf = '';
  }
  out.push(buf + text.slice(last));
  return out
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s, i) => ({
      segment_id: `seg-${i}`,
      text: s,
      source: 'ai_generated',
      status: 'pending',
      ts: null,
    }));
}

/**
 * UX_REVIEW T3: a sentence still carrying [CITATION_REMOVED] cannot be
 * accepted as-is — the verifier stripped a fabricated citation out of it, so
 * the prose around the hole needs a human rewrite (or exclusion).
 */
export function isAcceptBlocked(line) {
  return hasBlockingMarker(line.text);
}

/**
 * Apply a human edit to one segment (DraftEditor commitEdit).
 *
 * - Re-editing an *_added line keeps its "added" provenance; editing any other
 *   line marks it edited BY THE CURRENT ROLE (`editedSource`).
 * - The first AI original is kept in `edited_from`.
 * - An edit that still carries [CITATION_REMOVED] or [UNSUPPORTED_REF_n] stays
 *   pending — editing must not be a way around the accept gate.
 */
export function applyEdit(line, newText, editedSource, now = new Date()) {
  return {
    ...line,
    source: line.source.endsWith('_added') ? line.source : editedSource,
    edited_from: line.edited_from ?? (line.source === 'ai_generated' ? line.text : undefined),
    text: newText,
    status: hasBlockingMarker(newText) ? 'pending' : 'accepted',
    ts: now.toISOString(),
  };
}
