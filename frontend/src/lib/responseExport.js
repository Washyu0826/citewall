/**
 * Whole-response export (POST /v1/oa/export_response) — pure helpers,
 * unit-tested in responseExport.test.js.
 *
 * `progress` is the workspace's {rejection_id: {total, decided, accepted,
 * segments}} map, filled by each DraftEditor's onProgress.
 */

/** Can the whole response be exported, and if not, why not? */
export function exportReadiness(rejections, progress) {
  let pending = 0;
  let accepted = 0;
  let missing = 0;
  for (const r of rejections || []) {
    const p = progress?.[r.rejection_id];
    if (!p) {
      missing += 1;
      continue;
    }
    pending += p.total - p.decided;
    accepted += p.accepted;
  }
  return {
    ready: (rejections || []).length > 0 && missing === 0 && pending === 0 && accepted > 0,
    pending,
    accepted,
    missing,
  };
}

/** Request body: one section per rejection, in OA order. */
export function buildResponsePayload({ caseId, title, rejections, progress, headingFor }) {
  return {
    case_id: caseId,
    title,
    attorney_signoff: true,
    sections: (rejections || []).map((r, i) => ({
      rejection_id: r.rejection_id,
      heading: headingFor(r, i),
      segments: progress?.[r.rejection_id]?.segments || [],
    })),
  };
}

/** Save a base64 payload as a file (client-side only — nothing re-uploaded). */
export function downloadBase64(base64, filename, mime) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
