// Bundle-size budget (research 09 FE-L4), run in CI after `npm run build`.
// Measures what the browser downloads BEFORE the first page renders — the
// entry script plus every chunk index.html preloads, and the stylesheet — as
// gzip bytes, and fails when a budget is exceeded. Lazily loaded pages are
// reported but only the largest is budgeted.
//   node scripts/check-bundle.mjs [dist]
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

// Budgets in KB of gzip. Raise them deliberately, in review, never silently.
// Measured 2026-10-06 after lazy-loading every page: initial JS 183.4 KB
// (was ~213 KB with every page in the entry chunk), CSS 11.9 KB, largest lazy
// chunk (Analyze) 22.7 KB. What remains up front is what the shell itself
// uses: React, router, i18n strings, TanStack Query, the Radix menus/dialogs,
// tailwind-merge.
export const BUDGET_KB = {
  initialJs: 190,
  initialCss: 16,
  largestLazyChunk: 30,
};

const dist = process.argv[2] || 'dist';
const html = readFileSync(join(dist, 'index.html'), 'utf8');
const gzKb = (file) => gzipSync(readFileSync(join(dist, file))).length / 1024;

const refs = (re) => [...html.matchAll(re)].map((m) => m[1].replace(/^\//, ''));
const initialJs = [
  ...refs(/<script[^>]+type="module"[^>]+src="([^"]+\.js)"/g),
  ...refs(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+\.js)"/g),
];
const initialCss = refs(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+\.css)"/g);
const initialSet = new Set(initialJs);
const lazy = readdirSync(join(dist, 'assets'))
  .filter((f) => f.endsWith('.js') && !initialSet.has(`assets/${f}`))
  .map((f) => ({ file: `assets/${f}`, kb: gzKb(`assets/${f}`) }))
  .sort((a, b) => b.kb - a.kb);

const total = (files) => files.reduce((sum, f) => sum + gzKb(f), 0);
const measured = {
  initialJs: total(initialJs),
  initialCss: total(initialCss),
  largestLazyChunk: lazy[0]?.kb ?? 0,
};

let failed = false;
for (const [name, kb] of Object.entries(measured)) {
  const limit = BUDGET_KB[name];
  const ok = kb <= limit;
  failed ||= !ok;
  console.log(`${ok ? 'ok  ' : 'OVER'} ${name.padEnd(17)} ${kb.toFixed(1).padStart(6)} KB gzip (budget ${limit} KB)`);
}
console.log(`initial JS: ${initialJs.join(', ')}`);
console.log(`lazy chunks: ${lazy.map((c) => `${c.file} ${c.kb.toFixed(1)} KB`).join(', ')}`);
// A parser that finds nothing would pass vacuously.
if (initialJs.length === 0 || initialCss.length === 0) {
  console.error('no entry script / stylesheet found in index.html — the parser needs updating');
  failed = true;
}
process.exit(failed ? 1 : 0);
