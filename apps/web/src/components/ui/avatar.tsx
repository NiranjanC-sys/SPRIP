'use client';

import * as React from 'react';
import * as AvatarPrimitive from '@radix-ui/react-avatar';

import { cn } from '@/lib/utils';

const SIZES = { sm: 'size-6 text-2xs', md: 'size-8 text-xs', lg: 'size-10 text-sm' } as const;

export interface AvatarProps extends React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root> {
  name: string;
  src?: string | null;
  size?: keyof typeof SIZES;
}

/** Initials from the first and last word — "Marta L. Halvorsen" → "MH". */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase();
}

export function Avatar({ className, name, src, size = 'md', ...props }: AvatarProps) {
  return (
    <AvatarPrimitive.Root
      className={cn(
        'relative flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full',
        SIZES[size],
        className,
      )}
      {...props}
    >
      {src ? <AvatarPrimitive.Image src={src} alt="" className="size-full object-cover" /> : null}
      <AvatarPrimitive.Fallback
        // The name is carried by the surrounding control (menu trigger, table
        // cell), so the initials themselves are decorative.
        aria-hidden="true"
        className="flex size-full items-center justify-center bg-primary/12 font-semibold text-primary"
        delayMs={src ? 300 : 0}
      >
        {initials(name)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
}
