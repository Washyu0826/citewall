import * as React from 'react';

import { cn } from '../../lib/utils';

/**
 * Status badge / chip — the single source of truth for tone→class mapping.
 *
 * Tones are semantic (DESIGN_SYSTEM §2.2), backed by the CSS tokens in
 * index.css so dark mode needs no per-tone `dark:` classes:
 *   success      → verified / clean
 *   warning      → pending / cascade risk / deadline soon
 *   error        → rejected / failed
 *   info         → neutral information
 *   brand        → brand accent (e.g. redaction on)
 *   confidential → confidential-case routing — the ONLY use of purple
 *   neutral      → default
 *
 * Every class string is static so the Tailwind scanner sees it.
 */
const STATUS_TONE = {
  success: {
    soft: 'bg-success-soft text-success ring-success/30',
    solid: 'bg-emerald-700 text-white ring-emerald-800',
    outline: 'bg-transparent text-success ring-success/40',
  },
  warning: {
    soft: 'bg-warning-soft text-warning ring-warning/30',
    solid: 'bg-amber-600 text-white ring-amber-700',
    outline: 'bg-transparent text-warning ring-warning/40',
  },
  error: {
    soft: 'bg-danger-soft text-danger ring-danger/30',
    solid: 'bg-rose-700 text-white ring-rose-800',
    outline: 'bg-transparent text-danger ring-danger/40',
  },
  info: {
    soft: 'bg-info-soft text-info ring-info/30',
    solid: 'bg-sky-700 text-white ring-sky-800',
    outline: 'bg-transparent text-info ring-info/40',
  },
  brand: {
    soft: 'bg-brand-soft text-brand-fg ring-brand-fg/25',
    solid: 'bg-primary text-white ring-primary-hover',
    outline: 'bg-transparent text-brand-fg ring-brand-fg/40',
  },
  confidential: {
    soft: 'bg-confidential-soft text-confidential ring-confidential/30',
    solid: 'bg-purple-700 text-white ring-purple-800',
    outline: 'bg-transparent text-confidential ring-confidential/40',
  },
  neutral: {
    soft: 'bg-surface-sunken text-fg-secondary ring-line',
    solid: 'bg-slate-600 text-white ring-slate-700',
    outline: 'bg-transparent text-fg-secondary ring-line-strong',
  },
};

/**
 * @param {object}  props
 * @param {keyof typeof STATUS_TONE} [props.tone='neutral']
 * @param {'soft'|'solid'|'outline'} [props.variant='soft']
 * @param {'sm'|'md'} [props.size='md']
 */
const Badge = React.forwardRef(
  ({ className, tone = 'neutral', variant = 'soft', size = 'md', ...props }, ref) => {
    const toneMap = STATUS_TONE[tone] || STATUS_TONE.neutral;
    const toneClasses = toneMap[variant] || toneMap.soft;
    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center gap-1.5 whitespace-nowrap rounded font-medium ring-1 ring-inset',
          size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-0.5 text-xs leading-5',
          toneClasses,
          className
        )}
        {...props}
      />
    );
  }
);
Badge.displayName = 'Badge';

// eslint-disable-next-line react-refresh/only-export-components -- tone map is shared with legacy call sites
export { Badge, STATUS_TONE };
export default Badge;
