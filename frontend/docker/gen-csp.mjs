// Emit the nginx security-header snippet for the built SPA.
//
// Usage: node docker/gen-csp.mjs dist/index.html > security-headers.conf
//
// The CSP is strict: no 'unsafe-inline' scripts. index.html carries one inline
// pre-React script (dark-mode / lang attribute, avoids a flash on reload), so
// its sha256 is computed from the BUILT file and pinned in script-src.
// object-src/frame-src allow blob: only — OAUpload previews the chosen PDF from
// a blob: URL via <object>/<iframe>. connect-src is same-origin: the SPA talks
// to /api through this nginx; the dev-only StackStatus port probes (8011,
// 18080, 8088) are intentionally blocked in production and show "not detected".
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const html = readFileSync(process.argv[2], 'utf8');
const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(
  (m) => m[1]
);
const hashes = inline.map(
  (body) => `'sha256-${createHash('sha256').update(body, 'utf8').digest('base64')}'`
);

// frame-ancestors: 'none' (plus X-Frame-Options DENY) everywhere, except the
// public demo image (docker/demo.Dockerfile): Hugging Face Spaces shows the
// app inside an iframe on huggingface.co, so that build passes
// CSP_FRAME_ANCESTORS="https://huggingface.co". X-Frame-Options cannot list
// an origin, so it is left out then; current browsers honour frame-ancestors.
const frameAncestors = process.env.CSP_FRAME_ANCESTORS || "'none'";
if (!/^('none'|https:\/\/[a-z0-9.-]+(?: https:\/\/[a-z0-9.-]+)*)$/.test(frameAncestors)) {
  throw new Error(`CSP_FRAME_ANCESTORS must be 'none' or https origins: ${frameAncestors}`);
}

const csp = [
  "default-src 'self'",
  `script-src 'self' ${hashes.join(' ')}`.trim(),
  // React style={...} attributes + Tailwind's runtime-free CSS file.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  'object-src blob:',
  'frame-src blob:',
  "worker-src 'self' blob:",
  "base-uri 'none'",
  "form-action 'self'",
  `frame-ancestors ${frameAncestors}`,
].join('; ');

const lines = [
  `add_header Content-Security-Policy "${csp}" always;`,
  'add_header X-Content-Type-Options "nosniff" always;',
  'add_header Referrer-Policy "no-referrer" always;',
  ...(frameAncestors === "'none'" ? ['add_header X-Frame-Options "DENY" always;'] : []),
  'add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;',
  'add_header Cross-Origin-Opener-Policy "same-origin" always;',
];
process.stdout.write(lines.join('\n') + '\n');
