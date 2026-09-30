import { FileText } from 'lucide-react';

import { cn } from '../lib/utils';

/**
 * Presentational empty state (DESIGN_SYSTEM §5.15): an icon, a title that says
 * what is missing, a sentence on why, and the one action that fixes it. No
 * illustrations (P2). `icon` accepts a React node, or a string for legacy
 * callers.
 */
export default function EmptyState({ icon, title, description, hint, action, className = '', bare = false }) {
  const iconNode =
    icon === undefined ? (
      <FileText className="mx-auto h-10 w-10 text-fg-muted" strokeWidth={1.5} aria-hidden="true" />
    ) : typeof icon === 'string' ? (
      <span className="select-none text-4xl" aria-hidden="true">
        {icon}
      </span>
    ) : (
      icon
    );
  return (
    <div
      className={cn(
        'px-6 py-10 text-center',
        !bare && 'rounded-brand border border-line bg-surface-raised',
        className
      )}
    >
      <div className="mb-3">{iconNode}</div>
      {title && <h2 className="mb-1 text-base font-semibold text-fg">{title}</h2>}
      {description && <p className="mx-auto max-w-md text-sm text-fg-muted">{description}</p>}
      {hint && <p className="mx-auto mt-2 max-w-md text-sm text-fg-muted">{hint}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}
