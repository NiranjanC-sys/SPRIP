import localFont from 'next/font/local';

/**
 * Self-hosted variable fonts.
 *
 * `next/font/google` downloads from fonts.gstatic.com during `next build`, which
 * breaks on an air-gapped or firewalled machine. The woff2 files are vendored
 * into `public/fonts/` by `npm run fonts:sync` (see scripts/sync-fonts.mjs) and
 * loaded from disk, so the build and the running app are both fully offline.
 *
 * The CSS variables declared here are what `globals.css` composes into
 * `--font-sans` / `--font-mono`.
 */

export const fontSans = localFont({
  src: [
    {
      path: '../../public/fonts/inter-latin-wght-normal.woff2',
      weight: '100 900',
      style: 'normal',
    },
    {
      path: '../../public/fonts/inter-latin-ext-wght-normal.woff2',
      weight: '100 900',
      style: 'normal',
    },
  ],
  variable: '--font-inter',
  display: 'swap',
  // Metric-compatible fallback: reduces the layout shift when the variable font
  // swaps in, which is very visible on a dense table page.
  fallback: ['ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
  preload: true,
});

export const fontMono = localFont({
  src: [
    {
      path: '../../public/fonts/jetbrains-mono-latin-wght-normal.woff2',
      weight: '100 800',
      style: 'normal',
    },
  ],
  variable: '--font-jetbrains-mono',
  display: 'swap',
  fallback: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
  // Mono is used for lineage chips and IDs, not body copy — not worth a
  // render-blocking preload on every route.
  preload: false,
});

export const fontVariables = `${fontSans.variable} ${fontMono.variable}`;
