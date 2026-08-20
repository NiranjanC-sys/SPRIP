/**
 * Route group for the analytical modules: Portfolio, Events, Finance, Reviews,
 * Simulator, Budget, Ask-the-data and Data health.
 *
 * It adds no chrome and no padding. That is the point — every one of these pages
 * renders a full-bleed `<PageHeader>` (which owns its own border and padding)
 * followed by its own content region, and a wrapper with padding here would
 * inset the header band and break the flush rule the shell depends on.
 *
 * The group exists so those eight routes share one URL-less segment: a future
 * cross-cutting concern for the analytical surfaces (an evidence-mode toggle, a
 * shared Suspense boundary for the ECharts bundle) lands here rather than being
 * copy-pasted into eight files.
 *
 * Access control is *not* here. These eight routes have five different role
 * sets — see ROUTE_RULES — so each page calls `requireAccess('/its-own-path')`.
 */
export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-full flex-col">{children}</div>;
}
