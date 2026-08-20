'use client';

import * as React from 'react';
import { Check, ChevronsUpDown, Search, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Badge } from './badge';
import { Button } from './button';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

export interface ComboboxOption {
  value: string;
  label: string;
  /** Secondary line — therapeutic area, region code, event date. */
  hint?: string;
  disabled?: boolean;
}

export interface ComboboxProps {
  options: readonly ComboboxOption[];
  /** Controlled selection. Always an array; single-select just caps it at one. */
  value: readonly string[];
  onChange: (value: string[]) => void;
  multiple?: boolean;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
  /** Accessible name; also used as the visible trigger label prefix. */
  label: string;
  size?: 'sm' | 'md';
}

/**
 * Searchable multi-select.
 *
 * Hand-rolled on Popover rather than pulled from `cmdk` because the taxonomy
 * lists here (brands, topics, regions) are small and server-filtered elsewhere;
 * the command palette is the only place that needs cmdk's fuzzy matching, and
 * duplicating its keyboard model in two places is worse than one modest
 * listbox implementation.
 */
export function Combobox({
  options,
  value,
  onChange,
  multiple = true,
  placeholder = 'All',
  searchPlaceholder = 'Search…',
  emptyMessage = 'No matches',
  disabled,
  className,
  triggerClassName,
  label,
  size = 'md',
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [activeIndex, setActiveIndex] = React.useState(0);
  const listId = React.useId();

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || (o.hint ?? '').toLowerCase().includes(q),
    );
  }, [options, query]);

  React.useEffect(() => setActiveIndex(0), [query, open]);

  const selectedLabels = React.useMemo(
    () => options.filter((o) => value.includes(o.value)).map((o) => o.label),
    [options, value],
  );

  const toggle = (optionValue: string) => {
    if (!multiple) {
      onChange(value[0] === optionValue ? [] : [optionValue]);
      setOpen(false);
      return;
    }
    onChange(
      value.includes(optionValue) ? value.filter((v) => v !== optionValue) : [...value, optionValue],
    );
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const option = filtered[activeIndex];
      if (option && !option.disabled) toggle(option.value);
    }
  };

  return (
    <div className={cn('min-w-0', className)}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="secondary"
            size={size}
            disabled={disabled}
            aria-label={label}
            aria-expanded={open}
            aria-haspopup="listbox"
            className={cn('w-full justify-between font-normal', triggerClassName)}
            iconRight={<ChevronsUpDown className="text-text-subtle" />}
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="shrink-0 text-text-muted">{label}</span>
              {selectedLabels.length === 0 ? (
                <span className="truncate text-text-subtle">{placeholder}</span>
              ) : selectedLabels.length === 1 ? (
                <span className="truncate text-text">{selectedLabels[0]}</span>
              ) : (
                <Badge variant="info">{selectedLabels.length} selected</Badge>
              )}
            </span>
          </Button>
        </PopoverTrigger>

        <PopoverContent className="w-72 p-0">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search aria-hidden="true" className="size-3.5 shrink-0 text-text-subtle" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={searchPlaceholder}
              aria-label={`Search ${label}`}
              aria-controls={listId}
              className="w-full bg-transparent text-sm text-text outline-none placeholder:text-text-subtle"
            />
            {value.length > 0 ? (
              <button
                type="button"
                onClick={() => onChange([])}
                className="shrink-0 rounded-sm text-xs text-text-muted hover:text-text"
              >
                Clear
              </button>
            ) : null}
          </div>

          <ul
            id={listId}
            role="listbox"
            aria-multiselectable={multiple}
            className="scroll-thin max-h-64 overflow-y-auto p-1"
          >
            {filtered.length === 0 ? (
              <li className="px-2 py-6 text-center text-xs text-text-muted">{emptyMessage}</li>
            ) : (
              filtered.map((option, index) => {
                const selected = value.includes(option.value);
                return (
                  <li key={option.value}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={selected}
                      disabled={option.disabled}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => toggle(option.value)}
                      className={cn(
                        'flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left text-sm text-text',
                        index === activeIndex && 'bg-surface-sunken',
                        option.disabled && 'pointer-events-none opacity-50',
                      )}
                    >
                      <span className="mt-0.5 flex size-3.5 shrink-0 items-center justify-center">
                        {selected ? (
                          <Check aria-hidden="true" className="size-3.5 text-primary" strokeWidth={3} />
                        ) : null}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{option.label}</span>
                        {option.hint ? (
                          <span className="block truncate text-xs text-text-subtle">{option.hint}</span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  );
}

/** Removable chip used by FilterBar's active-filter row. */
export function FilterChip({
  label,
  value,
  onRemove,
}: {
  label: string;
  value: string;
  onRemove?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border border-border bg-surface px-1.5 py-0.5 text-2xs text-text">
      <span className="text-text-subtle">{label}:</span>
      <span className="font-medium">{value}</span>
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove filter ${label} ${value}`}
          className="rounded-sm text-text-subtle hover:text-danger"
        >
          <X aria-hidden="true" className="size-3" />
        </button>
      ) : null}
    </span>
  );
}
