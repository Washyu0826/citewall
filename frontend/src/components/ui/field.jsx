import * as React from 'react';

import { cn } from '../../lib/utils';

// DESIGN_SYSTEM §5.3 / §5.16 — 40px fields, 4px radius, visible label, hint and
// error wired to the control via aria-describedby.
const control =
  'w-full rounded border border-line-strong bg-surface-raised px-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-75 hover:border-fg-muted focus-visible:border-navy-700 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:opacity-70 aria-invalid:border-danger';

const Input = React.forwardRef(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(control, 'h-10', className)} {...props} />
));
Input.displayName = 'Input';

const Textarea = React.forwardRef(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(control, 'min-h-24 py-2 leading-relaxed', className)} {...props} />
));
Textarea.displayName = 'Textarea';

const Select = React.forwardRef(({ className, children, ...props }, ref) => (
  <select ref={ref} className={cn(control, 'h-10 pr-8', className)} {...props}>
    {children}
  </select>
));
Select.displayName = 'Select';

const Label = React.forwardRef(({ className, ...props }, ref) => (
  <label ref={ref} className={cn('text-sm font-medium text-fg-secondary', className)} {...props} />
));
Label.displayName = 'Label';

/**
 * Label + control + hint/error, with the ids wired for screen readers.
 * The single child control receives id / aria-describedby / aria-invalid.
 */
function Field({ label, hint, error, children, className, optional, optionalLabel }) {
  const autoId = React.useId();
  const child = React.Children.only(children);
  const id = child.props.id || autoId;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <Label htmlFor={id}>
          {label}
          {optional && <span className="ml-1 font-normal text-fg-muted">{optionalLabel}</span>}
        </Label>
      )}
      {React.cloneElement(child, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
      })}
      {hint && !error && (
        <p id={hintId} className="text-sm text-fg-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-sm text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export { Field, Input, Label, Select, Textarea };
