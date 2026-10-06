/**
 * How an API error is shown: one localised sentence plus whether a retry or a
 * re-login makes sense. Pure — unit tested in errorInfo.test.js.
 */

// Only ever render strings: a structured error body rendered as a React child
// crashes the whole tree (FAILURE_LOG B-9).
export const asText = (v) => (typeof v === 'string' ? v : '');

export function classifyError(err, t) {
  if (!err) return null;
  const status = err.status ?? null;

  // A slow model is the most likely failure — it must offer a retry and a
  // readable sentence, not a raw "request timed out after 420s".
  if (status === 408 || status === 504) {
    return { message: t('errors.timeout'), retryable: true };
  }
  if (status === 402) {
    return { message: t('errors.quota_exceeded'), retryable: false };
  }
  if (status === 401) {
    return { message: t('errors.session_expired'), retryable: false, requiresLogin: true };
  }
  if (status === 403) {
    return { message: t('errors.no_access'), retryable: false };
  }
  if (status === 413) {
    return { message: t('errors.file_too_large'), retryable: false };
  }
  if (status === 429) {
    return { message: t('errors.rate_limited'), retryable: true, countdown: true };
  }
  if (status === 500 || status === 502 || status === 503) {
    return { message: t('errors.server_busy'), retryable: true };
  }
  if (status === null || status === undefined || status === 0) {
    return { message: t('errors.network'), retryable: true };
  }
  if (status >= 400 && status < 500) {
    return { message: asText(err.message) || t('errors.request_failed'), retryable: false };
  }
  return { message: t('errors.unexpected'), retryable: false, showDetails: true };
}

/**
 * A lazily loaded page whose JS chunk could not be downloaded (research 09
 * FE-L4/FE-5): usually a redeploy replaced the hashed files the open tab still
 * references, or the connection dropped. React.lazy caches the failed import,
 * so only a full reload helps — never a "try again" re-render. Browsers word it
 * differently: Chromium "Failed to fetch dynamically imported module", Safari
 * "Importing a module script failed", Firefox "error loading dynamically
 * imported module"; Vite itself "Unable to preload CSS for …" when a page
 * chunk has its own stylesheet.
 */
export function isChunkLoadError(err) {
  const msg = typeof err?.message === 'string' ? err.message : '';
  return (
    err?.name === 'ChunkLoadError' ||
    /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i.test(
      msg
    )
  );
}
