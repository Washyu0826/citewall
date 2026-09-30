/* eslint-disable react-refresh/only-export-components */
import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';

import { cn } from '../../lib/utils';

// DESIGN_SYSTEM §5.1: 6px radius, 40px default height, navy primary, rose
// destructive, borders over shadows. Colours come from semantic tokens so dark
// mode needs no per-variant `dark:` pairs.
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-brand text-sm font-medium transition-colors duration-75 disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        // `primary` and `default` are aliases so existing call sites keep working.
        primary: 'bg-primary text-white shadow-elev-1 hover:bg-primary-hover',
        default: 'bg-primary text-white shadow-elev-1 hover:bg-primary-hover',
        destructive: 'bg-rose-700 text-white shadow-elev-1 hover:bg-rose-800',
        confidential: 'bg-purple-800 text-white shadow-elev-1 hover:bg-purple-900',
        outline:
          'border border-line-strong bg-surface-raised text-fg-secondary hover:bg-surface-hover hover:text-fg',
        secondary: 'bg-surface-sunken text-fg hover:bg-surface-hover',
        ghost: 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
        link: 'text-fg-link underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4',
        sm: 'h-9 px-3',
        lg: 'h-11 px-6 text-base',
        xs: 'h-7 px-2.5 text-xs',
        icon: 'h-10 w-10',
        'icon-sm': 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
});
Button.displayName = 'Button';

export { Button, buttonVariants };
