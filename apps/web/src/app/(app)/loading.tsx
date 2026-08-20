import { Skeleton, SkeletonText } from '@/components/ui/skeleton';

/**
 * In-shell route transition.
 *
 * Deliberately the *shape* of a page — header band, filter row, KPI strip, chart
 * card — rather than a spinner. A spinner says "something is happening"; a
 * skeleton in the final layout means the content lands without the page
 * reflowing under the pointer, which matters on surfaces where the first thing a
 * user does is click a row.
 *
 * Exactly one `role="status"` for the whole screen (the labelled Skeleton). A
 * screen reader announcing "loading" fifteen times is not more accessible.
 */
export default function AppLoading() {
  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 border-b border-border bg-surface px-4 py-4">
        <Skeleton className="h-3 w-40" label="Loading page" />
        <div className="flex items-center justify-between gap-4">
          <Skeleton className="h-7 w-72" />
          <Skeleton className="h-8 w-32" />
        </div>
        <SkeletonText lines={1} className="max-w-xl" />
      </div>

      <div className="flex flex-col gap-4 p-4">
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-8 w-36" />
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-7 w-32" />
              <Skeleton className="h-3 w-40" />
            </div>
          ))}
        </div>

        <div className="rounded-lg border border-border bg-surface p-4">
          <Skeleton className="mb-4 h-4 w-48" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    </div>
  );
}
