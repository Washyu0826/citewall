import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Loader2, LogIn, Mail } from 'lucide-react';

import { api } from '../api/client.js';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { Input, Label } from './ui/field.jsx';

// The demo identity matrix. Person names stay verbatim (e2e selects the
// buttons by name); role and capability text are localised.
const DEMO_USERS = [
  { id: 'alice', initial: 'A', name: 'Alice', role: 'attorney', tenant: 'tenant_a' },
  { id: 'bob', initial: 'B', name: 'Bob', role: 'paralegal', tenant: 'tenant_a' },
  { id: 'carol', initial: 'C', name: 'Carol', role: 'it_admin', tenant: 'tenant_b' },
  { id: 'audit_dave', initial: 'D', name: 'Dave', role: 'auditor', tenant: 'tenant_a' },
];
const DESC_KEY = { alice: 'login.user_alice', bob: 'login.user_bob', carol: 'login.user_carol', audit_dave: 'login.user_dave' };

/**
 * Sign-in. Deliberately an official-portal look, not a startup hero: solid
 * navy agency bar with the amber rule, a plain identity list, no marketing.
 *
 * Contract kept for e2e: a "CiteWall" brand string, one <button> per identity
 * whose accessible name contains the person's name, errors as role="alert".
 */
export default function Login({ onLogin }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [consumingLink, setConsumingLink] = useState(false);
  const consumedRef = useRef(false);

  // Outside demo mode the backend emails `${MAGIC_LINK_BASE_URL}#token=…`
  // instead of returning the token. Landing on that link consumes it here.
  // The fragment is cleared BEFORE the call (never left in history / the
  // address bar) and the ref guards StrictMode's double effect — the token is
  // single-use, a second consume would fail and show a false error.
  useEffect(() => {
    if (consumedRef.current) return;
    const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token');
    if (!token) return;
    consumedRef.current = true;
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    setConsumingLink(true);
    api
      .magicConsume(token)
      .then((session) => onLogin(session))
      .catch(() => setErr(t('magic.consume_failed')))
      .finally(() => setConsumingLink(false));
  }, [onLogin, t]);

  async function handlePick(uid) {
    setBusy(uid);
    setErr(null);
    try {
      onLogin(await api.login(uid));
    } catch (e) {
      // HTTP errors carry a human-readable gateway `detail`; anything without
      // a status is a network failure ("Failed to fetch") — show the
      // localized message instead of the raw browser string.
      setErr(e?.status ? e.message : t('errors.network'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface text-fg">
      <header className="border-b-4 border-accent bg-brand text-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center gap-3 px-4 sm:px-6">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-brand bg-white text-sm font-bold tracking-tight text-navy-900"
            aria-hidden="true"
          >
            CW
          </div>
          <div className="leading-tight">
            <div className="text-base font-semibold tracking-tight">{t('app_title')}</div>
            <div className="text-xs text-navy-100">{t('login.subtitle')}</div>
          </div>
        </div>
      </header>

      <main className="flex flex-1 justify-center px-4 py-8 sm:px-6 sm:py-12">
        <div className="flex w-full max-w-3xl flex-col gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-fg">{t('landing.tagline')}</h1>
            <p className="mt-2 text-sm text-fg-muted">{t('landing.poc_note')}</p>
          </div>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t('landing.pick_user')}</CardTitle>
                <CardDescription className="mt-1">{t('login_page.pick_desc')}</CardDescription>
              </div>
            </CardHeader>
            <ul className="divide-y divide-line-subtle">
              {DEMO_USERS.map((u) => {
                const isBusy = busy === u.id;
                const disabled = busy !== null;
                return (
                  <li key={u.id}>
                    <button
                      type="button"
                      onClick={() => handlePick(u.id)}
                      disabled={disabled}
                      aria-busy={isBusy}
                      className={[
                        'flex w-full items-center gap-4 px-4 py-4 text-left transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary',
                        disabled ? 'cursor-wait opacity-60' : 'hover:bg-surface-hover',
                      ].join(' ')}
                    >
                      <span
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white"
                        aria-hidden="true"
                      >
                        {u.initial}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold text-fg">{u.name}</span>
                          <Badge tone="brand" size="sm">
                            {t(`shell.role_badge.${u.role}`)}
                          </Badge>
                          <span className="font-mono text-xs text-fg-muted">{u.tenant}</span>
                        </span>
                        <span className="mt-1 block text-sm text-fg-secondary">{t(DESC_KEY[u.id])}</span>
                      </span>
                      {isBusy ? (
                        <Loader2 className="h-5 w-5 shrink-0 animate-spin text-brand-fg" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="h-5 w-5 shrink-0 text-fg-muted" aria-hidden="true" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>

          {consumingLink && (
            <div role="status" data-testid="magic-link-consuming" className="flex items-center gap-2 text-sm text-fg-secondary">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('magic_email.consuming')}
            </div>
          )}
          {err && (
            <div role="alert" className="rounded-brand border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger">
              {err}
            </div>
          )}

          <MagicLink onLogin={onLogin} disabled={busy !== null} />
        </div>
      </main>

      <footer className="border-t border-line bg-surface-raised py-3 text-center text-xs text-fg-muted">
        {t('landing.footer')}
      </footer>
    </div>
  );
}

/**
 * Magic-link sign-in. Secondary path: request a link for a user id. The demo
 * returns the token directly (clearly labelled — production emails it), then
 * "sign in with this link" consumes it and yields the same session as the
 * identity list.
 */
function MagicLink({ onLogin, disabled }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState('');
  const [phase, setPhase] = useState('idle'); // idle | requesting | sent | consuming
  const [token, setToken] = useState(null);
  const [error, setError] = useState(null);

  async function requestLink(e) {
    e.preventDefault();
    if (!userId.trim()) return;
    setPhase('requesting');
    setError(null);
    setToken(null);
    try {
      const r = await api.magicRequest(userId.trim());
      // magic_token is the DEMO-ONLY escape hatch; null for unknown users
      // (the message is identical either way — enumeration-safe).
      setToken(r.magic_token || null);
      setPhase('sent');
    } catch (e2) {
      setError(e2?.status ? e2.message : t('errors.network'));
      setPhase('idle');
    }
  }

  async function consume() {
    if (!token) return;
    setPhase('consuming');
    setError(null);
    try {
      onLogin(await api.magicConsume(token));
    } catch {
      setError(t('magic.consume_failed'));
      setPhase('sent');
    }
  }

  if (!open) {
    return (
      <div>
        <Button variant="link" className="h-auto px-0" onClick={() => setOpen(true)} disabled={disabled}>
          <Mail className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          {t('magic.link_cta')}
        </Button>
      </div>
    );
  }

  return (
    <Card className="p-4">
      <form onSubmit={requestLink} className="flex flex-col gap-2">
        <Label htmlFor="magic-user" className="flex items-center gap-2">
          <Mail className="h-4 w-4 text-brand-fg" strokeWidth={1.75} aria-hidden="true" />
          {t('magic.link_cta')}
        </Label>
        <div className="flex flex-wrap gap-2">
          <Input
            id="magic-user"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder={t('magic.user_placeholder')}
            autoComplete="username"
            className="min-w-48 flex-1"
          />
          <Button type="submit" disabled={!userId.trim() || phase === 'requesting' || phase === 'consuming'}>
            {phase === 'requesting' ? t('magic.requesting') : t('magic.request')}
          </Button>
        </div>
      </form>

      {phase === 'sent' && (
        <div className="mt-3 flex flex-col gap-2">
          {/* No token in the body = production shape: the link went by email. */}
          <div role="status" className="text-sm text-fg-secondary">
            {token ? t('magic.sent') : t('magic_email.sent')}
          </div>
          {token && (
            <div className="rounded-brand border border-warning/40 bg-warning-soft p-3">
              <div className="mb-1 text-xs font-semibold text-warning">{t('magic.demo_label')}</div>
              <div className="mb-2 break-all font-mono text-xs text-fg-secondary" data-testid="magic-token">
                {token}
              </div>
              <Button size="sm" onClick={consume} disabled={phase === 'consuming'}>
                {phase === 'consuming' ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <LogIn className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
                )}
                {phase === 'consuming' ? t('magic.consuming') : t('magic.sign_in_with_link')}
              </Button>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-3 text-sm text-danger">
          {error}
        </div>
      )}

      <Button
        variant="link"
        size="xs"
        className="mt-3 px-0 text-fg-muted"
        onClick={() => {
          setOpen(false);
          setPhase('idle');
          setToken(null);
          setError(null);
        }}
      >
        {t('magic.back')}
      </Button>
    </Card>
  );
}
