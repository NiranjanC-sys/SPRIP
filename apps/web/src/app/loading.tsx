import { Spinner } from '@/components/ui/spinner';

/**
 * Boot fallback: shown while the root segment resolves, which is before we know
 * whether the user is signed in and therefore whether a shell or a login panel
 * is coming.
 *
 * Deliberately neutral. A page-shaped dashboard skeleton here would flash a
 * dashboard silhouette at someone about to be redirected to `/login`, which is
 * both wrong and briefly alarming. The page-shaped skeleton lives one level
 * down, in `(app)/loading.tsx`, where we know a page is actually coming.
 */
export default function RootLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas">
      <Spinner size="xl" label="Loading" className="text-text-subtle" />
    </div>
  );
}
