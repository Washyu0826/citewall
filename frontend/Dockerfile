# syntax=docker/dockerfile:1.7
# PatentMind SPA — static build served by unprivileged nginx, /api proxied to
# the gateway (Q22/Q23). Build context: frontend/.

# ---- build --------------------------------------------------------------------
FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Never bake the demo-login bypass secret into a served bundle (client.js).
ENV VITE_DEMO_LOGIN_SECRET=""
# Public mock-mode demo only (docker/demo.Dockerfile): the one-click logins
# send the published demo-{user} passwords, which the gateway accepts only in
# LLM_MODE=mock. Off by default; it inlines no secret either way.
ARG VITE_DEMO_PUBLIC_PASSWORDS=false
ENV VITE_DEMO_PUBLIC_PASSWORDS=$VITE_DEMO_PUBLIC_PASSWORDS
RUN npm run build \
 && node docker/gen-csp.mjs dist/index.html > /tmp/security-headers.conf

# ---- runtime ------------------------------------------------------------------
# Unprivileged variant: runs as uid 101 and listens on 8080.
FROM nginxinc/nginx-unprivileged:stable-alpine
# Where /api/* is proxied (the /api prefix is stripped, like the vite proxy).
ENV GATEWAY_UPSTREAM=http://gateway:8010
COPY --from=build /src/dist /usr/share/nginx/html
COPY --from=build /tmp/security-headers.conf /etc/nginx/snippets/security-headers.conf
# Rendered to /etc/nginx/conf.d/default.conf by the image's envsubst step.
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
