import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import * as MenuPrimitive from '@radix-ui/react-dropdown-menu';
import { X } from 'lucide-react';

import { cn } from '../../lib/utils';

/*
 * Overlays (DESIGN_SYSTEM §5.9). Radix handles focus trapping, Esc, outside
 * click, portal and ARIA; we only style. Motion stays ≤ 150ms and is removed
 * under prefers-reduced-motion by the global rule in index.css.
 */

const panel =
  'z-50 rounded-md border border-line bg-surface-raised text-fg shadow-elev-2 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0';

/* ------------------------------- Dialog -------------------------------- */

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;

const DialogContent = React.forwardRef(
  ({ className, children, closeLabel = 'Close', wide = false, ...props }, ref) => (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/50 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          panel,
          'fixed left-1/2 top-1/2 flex max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col shadow-elev-3',
          wide ? 'max-w-3xl' : 'max-w-lg',
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute right-3 top-3 rounded p-1 text-fg-muted hover:bg-surface-hover hover:text-fg"
          aria-label={closeLabel}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
);
DialogContent.displayName = 'DialogContent';

function DialogHeader({ className, ...props }) {
  return <div className={cn('border-b border-line-subtle px-5 py-4 pr-12', className)} {...props} />;
}

const DialogTitle = React.forwardRef(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn('text-lg font-semibold text-fg', className)} {...props} />
));
DialogTitle.displayName = 'DialogTitle';

const DialogDescription = React.forwardRef(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('mt-1 text-sm text-fg-muted', className)}
    {...props}
  />
));
DialogDescription.displayName = 'DialogDescription';

function DialogBody({ className, ...props }) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', className)} {...props} />;
}

function DialogFooter({ className, ...props }) {
  return (
    <div
      className={cn('flex justify-end gap-2 border-t border-line-subtle px-5 py-3', className)}
      {...props}
    />
  );
}

/* ------------------------------- Popover ------------------------------- */

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;

const PopoverContent = React.forwardRef(
  ({ className, align = 'start', sideOffset = 6, ...props }, ref) => (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={12}
        className={cn(panel, 'w-80 max-w-[calc(100vw-2rem)] p-4', className)}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
);
PopoverContent.displayName = 'PopoverContent';

/* ------------------------------- Tooltip ------------------------------- */
// Tooltips only ever repeat information available elsewhere (never the sole
// carrier of meaning) — they are unreachable on touch.

const TooltipProvider = TooltipPrimitive.Provider;

function Tooltip({ content, children, side = 'top' }) {
  if (!content) return children;
  return (
    <TooltipPrimitive.Root delayDuration={300}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className="z-50 max-w-xs rounded bg-slate-900 px-2.5 py-1.5 text-xs leading-relaxed text-white shadow-elev-2 dark:bg-slate-100 dark:text-slate-900"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/* ---------------------------- Dropdown menu ---------------------------- */

const DropdownMenu = MenuPrimitive.Root;
const DropdownMenuTrigger = MenuPrimitive.Trigger;

const DropdownMenuContent = React.forwardRef(
  ({ className, align = 'end', sideOffset = 6, ...props }, ref) => (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={12}
        className={cn(panel, 'min-w-48 p-1', className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
);
DropdownMenuContent.displayName = 'DropdownMenuContent';

const DropdownMenuItem = React.forwardRef(({ className, ...props }, ref) => (
  <MenuPrimitive.Item
    ref={ref}
    className={cn(
      'flex cursor-default select-none items-center gap-2 rounded px-2.5 py-2 text-sm text-fg-secondary outline-none data-[highlighted]:bg-surface-hover data-[highlighted]:text-fg data-[disabled]:opacity-50',
      className
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = 'DropdownMenuItem';

function DropdownMenuLabel({ className, ...props }) {
  return (
    <MenuPrimitive.Label className={cn('px-2.5 py-1.5 text-xs text-fg-muted', className)} {...props} />
  );
}

function DropdownMenuSeparator({ className, ...props }) {
  return <MenuPrimitive.Separator className={cn('my-1 h-px bg-line', className)} {...props} />;
}

export {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Popover,
  PopoverAnchor,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipProvider,
};
