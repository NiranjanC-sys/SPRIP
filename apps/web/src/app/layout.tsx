import type { Metadata, Viewport } from 'next';

import '@/styles/globals.css';
import { fontVariables } from '@/lib/fonts';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: {
    default: 'Speaker ROI',
    template: '%s · Speaker ROI',
  },
  description:
    'Measure the prescribing impact and return on investment of HCP speaker programmes, with the evidence behind every number.',
  // The portal is behind auth and contains regulated commercial data; there is
  // nothing here a crawler should ever hold.
  robots: { index: false, follow: false, nocache: true },
  icons: { icon: '/favicon.svg' },
  applicationName: 'Speaker ROI',
  formatDetection: { telephone: false, address: false, email: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Both entries so the browser paints its own chrome (scrollbars, form
  // controls, the address bar) to match whichever theme resolves.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f6f8fb' },
    { media: '(prefers-color-scheme: dark)', color: '#0a1020' },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning` is required and only here: next-themes writes
    // `data-theme` on <html> in a blocking script before React hydrates, so the
    // server and client markup legitimately differ on this one element. That
    // script is what prevents the flash of the wrong theme.
    <html lang="en" suppressHydrationWarning className={fontVariables}>
      <body className="min-h-dvh bg-canvas font-sans text-text antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
