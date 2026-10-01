import { cn } from '../../lib/utils';

/** One content width for the header, the navigation and every page, so their left edges line up. */
export const CONTAINER = 'mx-auto w-full max-w-[1440px] px-4 sm:px-6 lg:px-8';

/**
 * Page scaffolding in the official-document style: a heading with an optional
 * caption above it, then sections separated by headings and rules — not a grid
 * of floating cards.
 */
export function Page({ className, children }) {
  return <div className={cn(CONTAINER, 'py-8 lg:py-10', className)}>{children}</div>;
}

export function PageHeader({ title, description, actions, eyebrow, className }) {
  return (
    <div className={cn('mb-8 flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-base text-fg-muted">{eyebrow}</p>}
        <h1 className="text-3xl font-bold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-base text-fg-secondary">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A titled part of a page: heading, optional lead text, then content. */
export function Section({ id, title, description, actions, children, className }) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section aria-labelledby={headingId} className={cn('mb-10', className)}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id={headingId} className="text-xl font-bold text-fg">
            {title}
          </h2>
          {description && <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

const FIGURE_TONE = {
  neutral: 'text-fg',
  warning: 'text-warning',
  danger: 'text-danger',
  success: 'text-success',
  confidential: 'text-confidential',
};

/**
 * Key figures as one ruled strip (label over number), not a row of boxed
 * tiles. `items`: [{ label, value, tone?, hint? }].
 */
export function KeyFigures({ items, label, className }) {
  return (
    <dl
      aria-label={label}
      className={cn(
        'mb-10 grid grid-cols-2 border-y border-line sm:flex sm:divide-x sm:divide-line',
        className
      )}
    >
      {items.map((it) => (
        <div key={it.label} className="px-0 py-4 sm:flex-1 sm:px-6 sm:first:pl-0">
          <dt className="text-sm text-fg-muted">{it.label}</dt>
          <dd className={cn('mt-1 text-3xl font-bold tabular-nums', FIGURE_TONE[it.tone || 'neutral'])}>
            {it.value}
          </dd>
          {it.hint && <dd className="mt-1 text-sm text-fg-muted">{it.hint}</dd>}
        </div>
      ))}
    </dl>
  );
}

/** Dashboard number tile — kept for the design-system page; pages use KeyFigures. */
export function Stat({ label, value, hint, tone = 'neutral', icon: Icon }) {
  return (
    <div className="rounded-brand border border-line bg-surface-raised p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-fg-muted">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-fg-muted" strokeWidth={1.75} aria-hidden="true" />}
      </div>
      <p className={cn('mt-2 text-3xl font-semibold tabular-nums', FIGURE_TONE[tone] || FIGURE_TONE.neutral)}>
        {value}
      </p>
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
