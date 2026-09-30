// Strip every content-bearing field from a Sentry event before it leaves the
// browser. sendDefaultPii: false only covers IP / cookies / user identity; the
// SDK still attaches exception messages (which can quote OA text), console /
// fetch breadcrumbs, request data and `extra`. The backend applies the same
// policy (backend/shared/observability.py scrub_sentry_event).
//
// Kept: exception TYPE, stack frames (file / function / line), tags, level,
// transaction name, span ops. Routes never carry a case_id (CLAUDE.md §9).

export const SCRUBBED = '[scrubbed]';

function scrubStacktrace(stacktrace) {
  for (const frame of stacktrace?.frames ?? []) delete frame.vars;
}

export function scrubSentryEvent(event) {
  if (!event || typeof event !== 'object') return event;

  if (event.request && typeof event.request === 'object') {
    const kept = {};
    if (event.request.method) kept.method = event.request.method;
    if (typeof event.request.url === 'string') kept.url = event.request.url.split('?')[0];
    event.request = kept;
  }

  for (const exc of event.exception?.values ?? []) {
    if (exc.value) exc.value = SCRUBBED;
    scrubStacktrace(exc.stacktrace);
  }

  if (typeof event.message === 'string') event.message = SCRUBBED;
  if (event.logentry && typeof event.logentry === 'object') {
    delete event.logentry.params;
    delete event.logentry.formatted;
  }

  const crumbs = Array.isArray(event.breadcrumbs) ? event.breadcrumbs : event.breadcrumbs?.values;
  for (const crumb of crumbs ?? []) {
    delete crumb.message;
    delete crumb.data;
  }

  for (const span of event.spans ?? []) delete span.data;

  delete event.extra;
  delete event.user;
  return event;
}
