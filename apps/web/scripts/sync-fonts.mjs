// Copies the variable woff2 subsets we actually use out of @fontsource-variable
// and into public/fonts, so next/font/local can hash them into the build.
//
// Why not next/font/google: it fetches from fonts.gstatic.com at build time. The
// plan requires a clean-machine, offline demo, so a build that needs the network
// to produce a font is a build that fails in the room where it matters. The
// fontsource packages are devDependencies — the woff2 bytes are checked in.
//
// Latin + latin-ext only: the portal's UI copy is English, and shipping Cyrillic
// / Greek / Vietnamese subsets would roughly triple the font payload for glyphs
// nothing in the product renders. Add a subset here if that changes.
import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const outDir = join(root, 'public', 'fonts');

/** @type {Array<[string, string]>} [sourceRelativeToNodeModules, destFilename] */
const FILES = [
  ['@fontsource-variable/inter/files/inter-latin-wght-normal.woff2', 'inter-latin-wght-normal.woff2'],
  [
    '@fontsource-variable/inter/files/inter-latin-ext-wght-normal.woff2',
    'inter-latin-ext-wght-normal.woff2',
  ],
  [
    '@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2',
    'jetbrains-mono-latin-wght-normal.woff2',
  ],
];

mkdirSync(outDir, { recursive: true });

let copied = 0;
for (const [src, dest] of FILES) {
  const from = join(root, 'node_modules', src);
  if (!existsSync(from)) {
    console.error(`[fonts] missing source: ${from}\n        run \`npm install\` first.`);
    process.exit(1);
  }
  copyFileSync(from, join(outDir, dest));
  copied += 1;
}

console.log(`[fonts] synced ${copied} variable woff2 file(s) -> public/fonts`);
