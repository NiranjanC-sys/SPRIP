'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';
import { Monitor, Moon, Sun } from 'lucide-react';

import { IconButton } from '@/components/ui/icon-button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/**
 * Three states, not two: light, dark, and "follow the system".
 *
 * A binary toggle silently overrides the OS preference the first time it is
 * touched, and there is then no way back — which is why `system` is the default
 * and stays selectable. `next-themes` persists the explicit choice and writes
 * `data-theme` in a blocking script before first paint, so there is no flash;
 * the `prefers-color-scheme` block in globals.css covers the unchosen case.
 */

const OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const;

export function ThemeToggle({ variant = 'ghost' }: { variant?: 'ghost' | 'nav' }) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // The server cannot know the OS preference, so the icon would necessarily be
  // wrong for half of users on first paint. Rendering the neutral monitor glyph
  // until mount avoids a visible swap without blocking anything.
  React.useEffect(() => setMounted(true), []);

  const Icon = !mounted ? Monitor : resolvedTheme === 'dark' ? Moon : Sun;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <IconButton
          label={mounted ? `Appearance: ${theme ?? 'system'}` : 'Appearance'}
          variant={variant}
          size="sm"
        >
          <Icon />
        </IconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme ?? 'system'} onValueChange={setTheme}>
          {OPTIONS.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              <option.icon aria-hidden="true" className="size-3.5 text-text-subtle" />
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
