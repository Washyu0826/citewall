# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Status: **Proof of Concept.** APIs, schemas, and behaviour may change without
> a major-version bump while the project is pre-1.0.

## [Unreleased]

### 2026-09-26 — public release prep (`patentmind-platform`)

- Removed the real OA / gazette PDFs from `docs/`; replaced remaining real
  applicant, application/document numbers and TIPO phone numbers with the
  fictitious values used in `data/cases`; redacted the real applicant name in
  four delivery screenshots.
- gitleaks scan (docker) + `.gitleaks.toml` allowlist for the public canary
  marker and the labelled local-dev Keycloak placeholder.
- `LICENSE` (Apache-2.0, © 2026 Washyu0826), `NOTICE`, Traditional-Chinese
  `SECURITY.md`; `README.md` is now the Traditional-Chinese primary README
  (English in `README.en.md`).
- Presentation and poster: unsupported claims removed, public eval-set numbers
  added, decks rebuilt.
- `docs/DEADLINE_RULES_REVIEW.md` checklist for a patent attorney; KR 2026/2027
  and EP 2026 holiday calendars verified against official sources (KR 2027 adds
  the 12/27 Christmas substitute holiday).

### 2026-09-25 — review branch `fix/review-2026-09-25`

#### Security
- Magic-link token returned in the HTTP body only when `MAGIC_LINK_RETURN_TOKEN`
  (default: mock mode); otherwise the link is emailed (`SMTP_*`,
  `MAGIC_LINK_BASE_URL`) with the token in the URL fragment.
- Stub OIDC/SAML secrets have no published default; the upstream-trust boot
  guard applies in mock mode; `demo-{user_id}` passwords are mock-only
  (`DEMO_PASSWORDS_ENABLED`).
- Confidentiality is a server-side case attribute (`data/case_registry.json`,
  `CASE_REGISTRY_PATH`); unregistered cases are confidential (fail-closed).
- Audit rows `hash_version=2`: HMAC-SHA256 (`AUDIT_HMAC_KEY`) over every stored
  field; v1 rows still verify; tenant-scoped verify no longer reports false breaks.
- Masking: keyed HMAC placeholder ids, wider invisible-character strip, NER for
  persons / organisations / addresses (`NER_BACKEND`), `user_hint` redacted,
  outbox stores payload digests only, per-subject erasure (`erase-subject`).
- `/metrics` requires `METRICS_TOKEN` (loopback-only when unset); ngrok requires
  basic auth (`NGROK_BASIC_AUTH`).
- Dependencies: fastapi 0.141.1, PyJWT 2.15.0, python-multipart 0.0.32.

#### AI engine
- Claude Sonnet 5 (reasoning) + Claude Haiku 4.5 alias (verifier), anthropic SDK
  1.8.0; no sampling parameters (effort instead); Citations API two-call draft;
  structured outputs; verifier honours the case security level.
- Citation wall rejects fabricated patent / publication numbers, case names and
  out-of-range statutes; spotlight tags neutralised; zh-TW dependent-claim parsing.
- Retrieval: Qdrant 1.19 dense + sparse with RRF, optional Qwen3 embedding and
  reranker, contextual retrieval, public examiner-citation eval builder.
- OCR: PaddleOCR-VL (local only for confidential documents).

#### Deadlines
- Calendar-month arithmetic; holiday calendars chosen by year (2025–2027 with
  sources); period starts at the service date (CN presumed issue + 15 days);
  JP domestic 60 days / foreign 3 months; CN first OA 4 months, later 2 months;
  every result carries `rules_reviewed: false` and `assumptions[]`.

#### Frontend
- React 19, Vite 8, Tailwind 4, React Router 7, ESLint 9; vitest unit tests.
- Citation pills resolve per rejection; review progress survives tab switches;
  zh-TW sentence splitting; logout revokes the session; confidence shown as pips;
  deadline inputs (domicile, OA number, service date) and start-date / assumption
  display; "not reviewed by a patent attorney" note.

#### Data & platform
- All case / sample identifiers are fictitious; 16 EP/JP synthetic cases added.
- Python 3.13, CI rewrite (least privilege, audit, frontend job), Dify 1.17.1
  target, digiRunner pinned `release-v4.7.3`.

### 2026-06-12 — Day 15
- Audit on Postgres (`AUDIT_BACKEND=postgres`), WORM archive on MinIO Object Lock
  (`ARCHIVE_BACKEND=s3`), real Keycloak OIDC (`OIDC_MODE=keycloak`), argon2id,
  figure-region extraction, Grafana dashboards, backup cron wrapper.
- DraftEditor tri-state sign-off with keyboard shortcuts; real policy chips.

### 2026-06-11 — Day 14
- Real digiRunner OSS (:18080) and Dify CE 1.14.2 → Ollama `qwen2.5:7b` chain;
  `scripts/start_delivery.sh`, `docs/DELIVERY_RUNBOOK.md`; git history rescue.


### Added
- **Open-source readiness**: `LICENSE` (Apache-2.0), `NOTICE`, `CONTRIBUTING.md`,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, GitHub issue / PR templates.
- **JWT lifecycle hardening (security H-5)**: issuer/audience (`iss`/`aud`)
  pinning, a `jti` revocation list, and `POST /v1/auth/logout` (kill switch);
  magic-link vs session token separation enforced in `verify_token`.
  Optional **RS256 asymmetric signing** (`JWT_ALGO=RS256` + PEM key pair) so a
  verify-only service holds a public key that cannot mint tokens; HS256 stays
  the default. The revocation store is now **pluggable** (`REVOCATION_BACKEND=
  memory|redis`): the Redis backend makes the logout kill switch durable across
  restart and replicas, with each jti auto-expiring at the token's TTL.
- **Verifier transparency**: `DraftResponse` now carries `invalid_citations`,
  `verifier_confidence`, and `verifier_model`, surfaced in the UI as a
  hallucination-defense panel (what the verifier stripped + which model vetted).
- **Multi-person provenance**: `paralegal_edited` / `paralegal_added` provenance
  sources so the responsibility chain (paralegal drafts → attorney signs) is
  visible per sentence and counted separately in the export summary + audit row.
- **Frontend**: deadline calculation is now explainable (roll-forward reason,
  recommended internal deadline, holiday-calendar version); full i18n coverage
  of the analyze flow with a working zh-TW / EN switcher; dark mode (theme
  toggle + `dark:` variants across the app).
- **Frontend architecture**: TanStack Query server-state layer (cache, retry,
  de-dupe) — the audit chain-verify request is now shared between the AppShell
  chip and the AuditView page instead of being issued twice.

### Fixed
- Test isolation: a unit test reloaded `backend.shared.config` in-process,
  desynchronising the `settings` singleton and causing order-dependent failures
  across the suite (passed alone, failed together). Now reads a fresh `Settings`
  instance instead of reloading the module.
- Documentation: corrected stale gateway/AI-engine ports (`:8000`/`:8001` →
  `:8010`/`:8011`) to match `scripts/start_backend.sh`.

### Security
- See `docs/SECURITY_AUDIT.md` for the full self-audit. As of this changelog,
  the original 4 Critical + 8 High findings are closed except H-5 (now also
  addressed here for the POC; production still needs Redis-backed revocation
  and RS256 — tracked in that document).

## [0.2.0]

- POC baseline: end-to-end gateway → AI-engine flow (mock backends), the 20
  architectural decisions in `docs/DECISIONS.md` each backed by runnable code,
  and the React SPA (login → analyze → sign-off → audit). See `README.md`.
