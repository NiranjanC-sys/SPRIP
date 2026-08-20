'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Command } from 'cmdk';
import {
  ArrowRight,
  CalendarDays,
  FileText,
  Loader2,
  Moon,
  Search,
  Sun,
  Workflow,
} from 'lucide-react';
import { useTheme } from 'next-themes';

import type { Role } from '@/lib/api/enums';
import { useEntitySearch } from '@/lib/api/queries/shell';
import { debounce } from '@/lib/utils';
import { flatNavigation } from './navigation';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Kbd } from '@/components/ui/kbd';
import { VisuallyHidden } from '@/components/ui/visually-hidden';

/**
 * ⌘K / Ctrl-K palette.
 *
 * Navigation entries come from the *filtered* nav tree, so the palette can never
 * offer a destination the shell decided not to show. Entity results come from
 * the server (`/search`) rather than a client index for the stronger reason:
 * a client-side index would have to contain every event title in the tenant, and
 * the existence of an out-of-scope event is itself information.
 *
 * The search term is debounced, not throttled — an analyst types "cardio" in
 * 300ms and only the settled string is worth a round trip.
 */

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: readonly Role[];
}

const KIND_ICON = {
  EVENT: CalendarDays,
  CAMPAIGN: Workflow,
  BRAND: FileText,
  UPLOAD: FileText,
  RUN: Workflow,
  SCENARIO: FileText,
  PAGE: ArrowRight,
} as const;

export function CommandPalette({ open, onOpenChange, roles }: CommandPaletteProps) {
  const router = useRouter();
  const { setTheme } = useTheme();
  const [input, setInput] = React.useState('');
  const [term, setTerm] = React.useState('');

  const navItems = React.useMemo(() => flatNavigation(roles), [roles]);

  const pushTerm = React.useMemo(() => debounce((value: string) => setTerm(value), 220), []);
  React.useEffect(() => () => pushTerm.cancel(), [pushTerm]);

  const onInput = (value: string) => {
    setInput(value);
    pushTerm(value);
  };

  const search = useEntitySearch(term, open);
  const results = search.data?.results ?? [];

  const go = (href: string) => {
    onOpenChange(false);
    setInput('');
    setTerm('');
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" hideClose className="top-24 translate-y-0 gap-0 p-0">
        <VisuallyHidden>
          <DialogTitle>Search and commands</DialogTitle>
          <DialogDescription>
            Jump to a page, or search events, campaigns, uploads and scenarios you are entitled to
            see.
          </DialogDescription>
        </VisuallyHidden>

        {/* `shouldFilter` stays on so nav items fuzzy-match locally; server
            results are pre-matched and are given a constant score of 1 via
            `value`, so they are never filtered out a second time. */}
        <Command loop label="Search and commands">
          <div className="flex items-center gap-2.5 border-b border-border px-3.5">
            <Search aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
            <Command.Input
              value={input}
              onValueChange={onInput}
              placeholder="Search pages, events, campaigns…"
              className="h-12 w-full bg-transparent text-sm text-text outline-none placeholder:text-text-subtle"
            />
            {search.isFetching ? (
              <Loader2 aria-hidden="true" className="size-3.5 animate-spin text-text-subtle" />
            ) : (
              <Kbd>Esc</Kbd>
            )}
          </div>

          <Command.List className="scroll-thin max-h-96 overflow-y-auto p-1.5">
            <Command.Empty className="px-3 py-8 text-center text-sm text-text-muted">
              {term.trim().length < 2
                ? 'Type at least two characters to search records.'
                : 'No matches you have access to.'}
            </Command.Empty>

            <Command.Group
              heading="Go to"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-text-subtle"
            >
              {navItems.map((item) => (
                <Command.Item
                  key={item.id}
                  value={`${item.label} ${item.description ?? ''}`}
                  onSelect={() => go(item.href)}
                  className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-sm text-text data-[selected=true]:bg-surface-sunken"
                >
                  <item.icon aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.description ? (
                    <span className="hidden min-w-0 max-w-64 truncate text-xs text-text-subtle sm:block">
                      {item.description}
                    </span>
                  ) : null}
                </Command.Item>
              ))}
            </Command.Group>

            {results.length > 0 ? (
              <Command.Group
                heading="Records"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-text-subtle"
              >
                {results.map((result) => {
                  const Icon = KIND_ICON[result.kind];
                  return (
                    <Command.Item
                      key={`${result.kind}-${result.id}`}
                      value={`${result.title} ${result.subtitle ?? ''} ${result.id}`}
                      onSelect={() => go(result.href)}
                      className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-sm text-text data-[selected=true]:bg-surface-sunken"
                    >
                      <Icon aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{result.title}</span>
                        {result.subtitle ? (
                          <span className="block truncate text-xs text-text-subtle">
                            {result.subtitle}
                          </span>
                        ) : null}
                      </span>
                      <span className="shrink-0 text-2xs uppercase tracking-wide text-text-subtle">
                        {result.kind}
                      </span>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            ) : null}

            <Command.Group
              heading="Appearance"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-text-subtle"
            >
              <Command.Item
                value="Switch to light theme appearance"
                onSelect={() => {
                  setTheme('light');
                  onOpenChange(false);
                }}
                className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-sm text-text data-[selected=true]:bg-surface-sunken"
              >
                <Sun aria-hidden="true" className="size-4 text-text-subtle" />
                Switch to light theme
              </Command.Item>
              <Command.Item
                value="Switch to dark theme appearance"
                onSelect={() => {
                  setTheme('dark');
                  onOpenChange(false);
                }}
                className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-sm text-text data-[selected=true]:bg-surface-sunken"
              >
                <Moon aria-hidden="true" className="size-4 text-text-subtle" />
                Switch to dark theme
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Registers the global shortcut. Lives in a hook so the shell owns the open
 * state and the palette itself stays a controlled component.
 */
export function useCommandPalette(): {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
} {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return { open, setOpen, toggle: () => setOpen((prev) => !prev) };
}
