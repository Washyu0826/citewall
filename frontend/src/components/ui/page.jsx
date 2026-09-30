import { cn } from '../../lib/utils';

/**
 * Page scaffolding shared by every top-level route: a max-width container, a
 * header with title / description / actions, and a stat tile. Keeps page
 * rhythm (sp.lg between sections, sp.xl around the page) in one place.
 */
export function Page({ className, children, width = 'app' }) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 py-6 sm:px-6 lg:py-8',
        width === 'app' ? 'max-w-[1440px]' : width === 'form' ? 'max-w-2xl' : '',
        className
      )}
    >
      {children}
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow, className }) {
  return (
    <div className={cn('mb-6 flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-sm font-medium text-fg-muted">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const STAT_TONE = {
  neutral: 'text-fg',
  brand: 'text-brand-fg',
  warning: 'text-warning',
  danger: 'text-danger',
  success: 'text-success',
};

/** Dashboard number tile — the number is the headline, the label explains it. */
export function Stat({ label, value, hint, tone = 'neutral', icon: Icon }) {
  return (
    <div className="rounded-brand border border-line bg-surface-raised p-4 shadow-elev-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-fg-muted">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-fg-muted" strokeWidth={1.75} aria-hidden="true" />}
      </div>
      <p className={cn('mt-2 text-3xl font-semibold tabular-nums', STAT_TONE[tone])}>{value}</p>
      {hint && <p className="mt-1 text-sm text-fg-muted">{hint}</p>}
    </div>
  );
}

/** Keyboard shortcut hint. */
export function Kbd({ children }) {
  return (
    <kbd className="inline-flex min-w-6 items-center justify-center rounded border border-line-strong bg-surface-sunken px-1.5 font-mono text-xs text-fg-secondary">
      {children}
    </kbd>
  );
}
