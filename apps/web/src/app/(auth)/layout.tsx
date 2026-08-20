import { ProductMark } from '@/components/layout/ProductMark';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { env } from '@/lib/env';

/**
 * The unauthenticated frame: a split panel, form left, brand right.
 *
 * The right panel is decorative and disappears below `lg` — on a phone it would
 * push the password field below the fold, and there is no worse place for a
 * marketing panel than above the thing the user came to do.
 *
 * `.auth-visual` / `.auth-grid` are pure CSS (globals.css). No hero image: this
 * is deployed inside pharma networks that frequently sit behind an egress proxy
 * with no CDN reach, and a login screen that half-loads reads as compromised.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh grid-cols-1 bg-canvas lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="relative flex flex-col">
        <header className="flex items-center justify-between px-6 py-5 sm:px-10">
          <div className="flex items-center gap-2.5">
            <ProductMark className="size-7" />
            <span className="text-sm font-semibold tracking-tight text-text">Speaker ROI</span>
            {env.environmentLabel ? (
              <span className="rounded-sm border border-border bg-surface-sunken px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wide text-text-muted">
                {env.environmentLabel}
              </span>
            ) : null}
          </div>
          {/* Present on the login screen because the theme choice is stored per
              browser, not per account — a user on a shared workstation should be
              able to fix a painful contrast before they type a password. */}
          <ThemeToggle />
        </header>

        <main className="flex flex-1 items-center justify-center px-6 pb-16 sm:px-10">
          <div className="w-full max-w-sm">{children}</div>
        </main>

        <footer className="px-6 pb-6 text-2xs text-text-subtle sm:px-10">
          Access is monitored and audited. Use is restricted to authorised personnel.
        </footer>
      </div>

      <aside aria-hidden="true" className="auth-visual relative hidden overflow-hidden lg:block">
        <div className="auth-grid absolute inset-0" />
        <div className="relative flex h-full flex-col justify-end gap-4 p-12 text-nav-fg">
          <p className="max-w-md text-2xl font-medium leading-snug tracking-tight text-nav-fg-active">
            Every number carries the evidence behind it — the cohort, the control, and the reason to
            believe it.
          </p>
          <p className="max-w-md text-sm leading-relaxed text-nav-fg">
            Speaker programme impact and return on investment, measured against a matched control
            and reported with the confidence it actually earns.
          </p>
        </div>
      </aside>
    </div>
  );
}
