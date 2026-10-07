import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import viteConfig, { IDENTITY_HEADERS, stripIdentityHeaders } from '../../vite.config.js';

// FAILURE_LOG B-50: the gateway trusts identity headers from loopback, and the
// dev proxy (and the demo image's nginx) forwards from loopback.

describe('dev proxy never forwards a browser-supplied identity', () => {
  it('removes every upstream identity header and nothing else', () => {
    const headers = new Map(
      [...IDENTITY_HEADERS, 'authorization', 'content-type'].map((h) => [h, 'x'])
    );
    const proxyReq = { removeHeader: (h) => headers.delete(h) };
    stripIdentityHeaders(proxyReq);
    expect([...headers.keys()]).toEqual(['authorization', 'content-type']);
  });

  it('is wired into the /api proxy', () => {
    const handlers = [];
    const proxy = { on: (event, fn) => handlers.push([event, fn]) };
    viteConfig.server.proxy['/api'].configure(proxy);
    expect(handlers).toEqual([['proxyReq', stripIdentityHeaders]]);
  });

  it('the nginx template strips the same headers', () => {
    const template = readFileSync(resolve(process.cwd(), 'docker/default.conf.template'), 'utf8');
    for (const h of IDENTITY_HEADERS) {
      expect(template.toLowerCase()).toContain(`proxy_set_header ${h} "";`);
    }
  });
});
