import { useTranslation } from 'react-i18next';
import { Cloud, Lock } from 'lucide-react';

import { Badge } from '../ui/badge.jsx';
import { caseStatus, daysUntil, deadlineTone, formatDate, isConfidentialLevel } from '../../lib/cases.js';

/** Server-resolved confidentiality — purple lock for anything but "public". */
export function SecurityBadge({ level, size = 'md' }) {
  const { t } = useTranslation();
  const confidential = isConfidentialLevel(level);
  const key = level === 'public' || level === 'confidential' || level === 'top_secret' ? level : 'confidential';
  return (
    <Badge
      tone={confidential ? 'confidential' : 'success'}
      size={size}
      title={confidential ? t('security.confidential_hint') : t('security.public_hint')}
    >
      {confidential ? (
        <Lock className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
      ) : (
        <Cloud className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
      )}
      {t(`security.${key}`)}
    </Badge>
  );
}

/** Date plus a days-left badge coloured by urgency. */
export function DeadlineCell({ iso }) {
  const { t, i18n } = useTranslation();
  const days = daysUntil(iso);
  if (days === null) return <span className="text-sm text-fg-muted">{t('deadline.none')}</span>;
  const label =
    days < 0
      ? t('deadline.overdue', { count: -days })
      : days === 0
        ? t('deadline.today')
        : t('deadline.days_left', { count: days });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <time dateTime={iso} className="font-mono text-sm text-fg">
        {formatDate(iso, i18n.language)}
      </time>
      <Badge tone={deadlineTone(days)} size="sm">
        {label}
      </Badge>
    </div>
  );
}

export function RejectionBadges({ types }) {
  const { t } = useTranslation();
  if (!types?.length) return <span className="text-sm text-fg-muted">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {types.map((type) => (
        <Badge key={type} tone="neutral" size="sm">
          {t(`rejection.${type}`, { defaultValue: type })}
        </Badge>
      ))}
    </div>
  );
}

const STATUS_TONE = { not_analyzed: 'neutral', analyzed: 'success', degraded: 'warning' };

export function StatusBadge({ row }) {
  const { t } = useTranslation();
  const status = caseStatus(row);
  return (
    <Badge tone={STATUS_TONE[status]} size="sm">
      {t(`case_status.${status}`)}
    </Badge>
  );
}
