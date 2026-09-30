// UX_REVIEW（業界對照 · S 級最高 CP 建議）— 法定期日匯出 .ics。
//
// 期限錯過 = 專利權失效，但律師的真實行事曆在 Outlook / Google Calendar，
// 不在本系統。與其要求他們抄日期，不如給一個標準 .ics：兩個全天事件
// （法定期限 + 內部建議完成日，各帶 7 天 / 3 天提醒），點開即匯入任何
// 行事曆軟體。
//
// 純前端生成（Blob 下載）：日期資料本來就在分析回應裡，不需要任何後端
// 呼叫，也沒有任何資料離開瀏覽器 — 符合 on-prem 承諾。
// RFC 5545 注意：行尾必須 CRLF；TEXT 值要跳脫 \ ; , 換行。

function icsEscape(text) {
  return String(text)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

function toDateValue(iso) {
  // All-day events use VALUE=DATE (no time, no TZ ambiguity across the
  // firm's machines). ISO input may carry a time component — strip it.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}${m}${day}`;
}

function nextDay(dateValue) {
  // DTEND on all-day events is EXCLUSIVE per RFC 5545.
  const y = Number(dateValue.slice(0, 4));
  const m = Number(dateValue.slice(4, 6)) - 1;
  const d = Number(dateValue.slice(6, 8));
  const next = new Date(Date.UTC(y, m, d + 1));
  return toDateValue(next.toISOString());
}

function vevent({ uid, dateValue, summary, description, alarmDays }) {
  const lines = [
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`,
    `DTSTART;VALUE=DATE:${dateValue}`,
    `DTEND;VALUE=DATE:${nextDay(dateValue)}`,
    `SUMMARY:${icsEscape(summary)}`,
    `DESCRIPTION:${icsEscape(description)}`,
    'TRANSP:OPAQUE',
  ];
  if (alarmDays) {
    lines.push(
      'BEGIN:VALARM',
      `TRIGGER:-P${alarmDays}D`,
      'ACTION:DISPLAY',
      `DESCRIPTION:${icsEscape(summary)}`,
      'END:VALARM'
    );
  }
  lines.push('END:VEVENT');
  return lines;
}

/**
 * Build the .ics text for one analysis result's deadlines.
 *
 * @param {object} args
 * @param {string} args.caseId
 * @param {object} args.deadline  AnalysisResponse.deadline_summary
 * @param {(key: string, opts?: object) => string} args.t  i18n translator
 * @returns {string|null} ics text, or null when no parsable deadline exists
 */
export function buildDeadlineIcs({ caseId, deadline, t }) {
  const statutory = toDateValue(deadline?.statutory_deadline);
  if (!statutory) return null;
  const internal = deadline?.recommended_internal_deadline
    ? toDateValue(deadline.recommended_internal_deadline)
    : null;

  const meta = [
    t('analyze.ics.generated_by'),
    deadline?.holiday_calendar_version
      ? t('analyze.result.calendar') + ' ' + deadline.holiday_calendar_version
      : null,
    ...(Array.isArray(deadline?.warnings) ? deadline.warnings : []),
  ]
    .filter(Boolean)
    .join('\n');

  const events = vevent({
    uid: `${caseId}-statutory@citewall.local`,
    dateValue: statutory,
    summary: t('analyze.ics.statutory_summary', { caseId }),
    description: meta,
    alarmDays: 7,
  });
  if (internal) {
    events.push(
      ...vevent({
        uid: `${caseId}-internal@citewall.local`,
        dateValue: internal,
        summary: t('analyze.ics.internal_summary', { caseId }),
        description: meta,
        alarmDays: 3,
      })
    );
  }

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//CiteWall//OA Deadline//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    ...events,
    'END:VCALENDAR',
    '',
  ].join('\r\n');
}

/** Trigger a browser download of the deadlines as `<caseId>-deadlines.ics`. */
export function downloadDeadlineIcs({ caseId, deadline, t }) {
  const ics = buildDeadlineIcs({ caseId, deadline, t });
  if (!ics) return false;
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${caseId || 'case'}-deadlines.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return true;
}
