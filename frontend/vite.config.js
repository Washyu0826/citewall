import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Q4: Vite for product SPA. SSR is a separate Next.js app (out of POC scope).
//
// API proxy target is env-driven so the whole SPA can be routed through the
// digiRunner API gateway without code changes:
//
//   default (direct to thin gateway):
//     npm run dev                      -> /api/* -> http://localhost:8010/*
//
//   through digiRunner (front-line gateway, see scripts/start_digirunner.sh):
//     VITE_API_TARGET=http://localhost:18080 VITE_API_PATH_PREFIX=dgrc npm run dev
//                                      -> /api/* -> http://localhost:18080/dgrc/*
//
// VITE_API_PATH_PREFIX exists because digiRunner (dgrv4) serves registered
// proxy APIs under its /dgrc context path. Pass it WITHOUT a leading slash
// (`dgrc`, not `/dgrc`) — Git Bash on Windows rewrites leading-slash args
// into `C:/Program Files/Git/...` (MSYS path mangling); the normaliser below
// adds the slash back either way. Do NOT change the default :8010
// (ai_engine is :8011) per scripts/start_backend.sh — do NOT change to :8000.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8010';

// Browsers never assert an identity. The gateway honours these headers from
// its trusted upstream (digiRunner; TRUSTED_UPSTREAM_IPS is loopback by
// default) — and this dev proxy forwards from loopback, so without this any
// visitor (e.g. through scripts/start_ngrok.sh) could log in as anyone by
// adding a header (FAILURE_LOG B-50). Same list as the nginx template.
export const IDENTITY_HEADERS = ['x-user-id', 'x-tenant-id', 'x-user-role', 'x-upstream-auth-token'];
export function stripIdentityHeaders(proxyReq) {
  for (const h of IDENTITY_HEADERS) proxyReq.removeHeader(h);
}
const API_PATH_PREFIX = (() => {
  let p = process.env.VITE_API_PATH_PREFIX || '';
  p = p.replace(/\/+$/, '');                 // no trailing slash
  if (p && !p.startsWith('/')) p = '/' + p;  // ensure leading slash
  return p;
})();

export default defineConfig({
  // Tailwind v4 runs as a first-party Vite plugin (no PostCSS/autoprefixer).
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Proxy gateway calls so we can hit /api/* from the SPA without CORS
      // friction.
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, API_PATH_PREFIX),
        configure: (proxy) => proxy.on('proxyReq', stripIdentityHeaders)
      }
    }
  },
  build: {
    // Vite 8 bundles with Rolldown: `rollupOptions` -> `rolldownOptions`, and
    // the object form of `manualChunks` is gone — vendor splitting is now
    // `output.codeSplitting.groups` (regex `test` over module ids).
    rolldownOptions: {
      output: {
        // Split heavy/independent deps into long-cacheable vendor chunks.
        // @sentry is intentionally listed: when a DSN is configured it loads
        // via dynamic import() and lands in its own async chunk; in DSN-less
        // builds it is never imported and so never fetched.
        codeSplitting: {
          groups: [
            { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'vendor-router', test: /node_modules[\\/]react-router[\\/]/ },
            { name: 'vendor-i18n', test: /node_modules[\\/](i18next|react-i18next)[\\/]/ },
            { name: 'vendor-icons', test: /node_modules[\\/]lucide-react[\\/]/ },
            { name: 'vendor-sentry', test: /node_modules[\\/]@sentry/ },
          ],
        },
      },
    },
  },
  // Vitest (Q35) — pure-function + component unit tests, separate from the
  // Playwright e2e suite under tests/e2e.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
});
