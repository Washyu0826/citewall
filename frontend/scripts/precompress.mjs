// Pre-gzip the hashed build assets so nginx serves them with `gzip_static on`
// (research 09 FE-L4): the SPA was sent uncompressed — 682 KB of JS on the
// first load instead of ~210 KB. Only /assets is compressed; API responses
// are not (they mix secrets with attacker-influenced text — BREACH).
//   node scripts/precompress.mjs [dir=dist/assets]
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { constants, gzipSync } from 'node:zlib';

const dir = process.argv[2] || 'dist/assets';
const COMPRESSIBLE = /\.(js|css|svg|json|txt)$/;

let files = 0;
let rawBytes = 0;
let gzBytes = 0;
for (const name of readdirSync(dir)) {
  const path = join(dir, name);
  if (!COMPRESSIBLE.test(name) || !statSync(path).isFile()) continue;
  const raw = readFileSync(path);
  if (raw.length < 1024) continue; // not worth a second file
  const gz = gzipSync(raw, { level: constants.Z_BEST_COMPRESSION });
  if (gz.length >= raw.length) continue;
  writeFileSync(`${path}.gz`, gz);
  files += 1;
  rawBytes += raw.length;
  gzBytes += gz.length;
}
console.log(
  `precompress: ${files} files, ${(rawBytes / 1024).toFixed(0)} KB -> ${(gzBytes / 1024).toFixed(0)} KB (.gz)`
);
