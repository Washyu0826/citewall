/* eslint-disable react-refresh/only-export-components -- navItemsForRole is shared with App.jsx */
import { useCallback, useEffect, useMemo } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  Check,
  ChevronDown,
  Cloud,
  FileSearch,
  FolderOpen,
  Home,
  Languages,
  Lock,
  LogOut,
  Moon,
  ScrollText,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sun,
  UserRound,
} from 'lucide-react';

import { useAuditVerify, useCases } from '../api/queries.js';
import i18n, { htmlLangFor } from '../lib/i18n';
import { useTheme } from '../lib/theme.jsx';
import { useCurrentCase } from '../lib/currentCase.jsx';
import { useWorkspaceActions } from '../lib/workspace.jsx';
import { isConfidentialLevel } from '../lib/cases.js';
import { chainChipView } from '../lib/chainChip.js';
import { cn } from '../lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
  TooltipProvider,
} from './ui/overlay.jsx';
import { CONTAINER } from './ui/page.jsx';
import StackStatus from './StackStatus.jsx';
import { DeadlineCell, SecurityBadge } from './cases/CaseBits.jsx';

/**
 * Authenticated chrome, official-document style: a navy service bar (brand,
 * current case, account), then one horizontal navigation row that also states
 * the data-handling status in plain words, then the page. No side rail — with
 * two or three destinations per role it was mostly empty space.
 *
 * Trust signals come from the server: the routing status reads the current
 * case's security level from GET /v1/cases, never from the shape of the
 * case_id (unregistered cases are confidential server-side, so guessing from
 * a "-CONF" suffix would under-report them).
 */

export const CASE_ROLES = ['attorney', 'paralegal'];
const CASE_LIST_ROLES = ['attorney', 'paralegal', 'auditor'];

export function navItemsForRole(role) {
  switch (role) {
    case 'auditor':
      return [
        { id: 'audit', to: '/audit', labelKey: 'nav.audit', Icon: ScrollText },
        { id: 'cases', to: '/cases', labelKey: 'nav.cases', Icon: FolderOpen },
      ];
    case 'it_admin':
      return [
        { id: 'admin-cases', to: '/admin/cases', labelKey: 'nav.admin_cases', Icon: Shield },
        { id: 'audit', to: '/audit', labelKey: 'nav.audit', Icon: ScrollText },
      ];
    default:
      return [
        { id: 'home', to: '/home', labelKey: 'nav.home', Icon: Home },
        { id: 'cases', to: '/cases', labelKey: 'nav.cases', Icon: FolderOpen },
        { id: 'analyze', to: '/analyze', labelKey: 'nav.analyze', Icon: FileSearch },
      ];
  }
}

export default function AppShell({ session, onLogout, children, trustContext }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const role = session?.role;
  // UX-5: signing out drops the workspace — ask first if there are sentence
  // decisions not exported yet, or an analysis still running (W2b-R4).
  const { confirmDiscard } = useWorkspaceActions();
  const guardedLogout = useCallback(() => {
    confirmDiscard('logout').then((ok) => ok && onLogout());
  }, [confirmDiscard, onLogout]);

  const isAuditor = role === 'auditor';
  const canCallAudit = isAuditor || role === 'it_admin';
  const canListCases = CASE_LIST_ROLES.includes(role);

  useSavedLanguage();

  const verifyQ = useAuditVerify(session?.token, isAuditor ? 'global' : 'tenant', {
    poll: true,
    enabled: canCallAudit,
  });
  const casesQ = useCases(session?.token, canListCases);
  const cases = casesQ.data?.cases;

  const auditState = useMemo(() => {
    if (!canCallAudit) return { status: 'idle', verified: 0, broken: 0, error: null };
    // The verify call itself failed (rate limited, server error, offline):
    // the chain was not checked, so this is neither "verified" nor "broken"
    // (review of B-53: a 429 used to show the red tamper alarm).
    if (verifyQ.error) {
      return { status: 'unavailable', verified: 0, broken: 0, error: verifyQ.error?.message || 'verify failed' };
    }
    if (!verifyQ.data) return { status: 'idle', verified: 0, broken: 0, error: null };
    const brokenCount = Array.isArray(verifyQ.data.broken) ? verifyQ.data.broken.length : 0;
    return {
      status: brokenCount === 0 ? 'ok' : 'fail',
      verified: verifyQ.data.verified ?? 0,
      broken: brokenCount,
      error: null,
    };
  }, [canCallAudit, verifyQ.data, verifyQ.error]);

  const navItems = useMemo(
    () => navItemsForRole(role).map((item) => ({ ...item, label: t(item.labelKey) })),
    [role, t]
  );

  return (
    <TooltipProvider>
      <div className="flex min-h-screen flex-col bg-surface text-fg">
        <a
          href="#main"
          className="sr-only z-50 rounded bg-surface-raised px-3 py-2 text-sm font-medium text-fg focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          {t('nav.skip_to_content')}
        </a>
        <TopBar
          session={session}
          onLogout={guardedLogout}
          auditState={auditState}
          canCallAudit={canCallAudit}
          onNavigateAudit={() => navigate('/audit')}
          cases={CASE_ROLES.includes(role) ? cases : null}
          onOpenCase={() => navigate('/analyze')}
          onAllCases={() => navigate('/cases')}
        />
        <ServiceNav
          items={navItems}
          session={session}
          trustContext={trustContext}
          cases={cases}
          onWorkspace={location.pathname === '/analyze'}
        />
        <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
          {children}
        </main>
        {/* Integration lights matter to IT / audit, not to the attorney
            reading drafts all day (UX_REVIEW M3). */}
        {canCallAudit && <ShellFooter t={t} />}
      </div>
    </TooltipProvider>
  );
}

/* -------------------------------------------------------------------------- */
/*  Top bar                                                                   */
/* -------------------------------------------------------------------------- */

function TopBar({ session, onLogout, auditState, canCallAudit, onNavigateAudit, cases, onOpenCase, onAllCases }) {
  const { t } = useTranslation();
  return (
    <header className="border-b-4 border-accent bg-brand text-white">
      <div className={cn(CONTAINER, 'flex h-14 items-center gap-3')}>
        {/* min-w-0 + truncate: the product name is long; on a phone it may
            clip rather than push the account controls off-screen. */}
        <div className="flex min-w-0 items-center gap-2.5">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-brand bg-white text-sm font-bold tracking-tight text-navy-900"
            aria-hidden="true"
          >
            OA
          </div>
          <span className="truncate text-lg font-bold tracking-tight" title={t('app_title')}>
            {t('app_title')}
          </span>
          <span className="hidden border-l border-white/30 pl-2.5 text-sm text-navy-100 lg:inline">
            {t('login.subtitle')}
          </span>
        </div>

        {cases && <CaseSwitcher cases={cases} onOpenCase={onOpenCase} onAllCases={onAllCases} />}

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {canCallAudit && <ChainChip state={auditState} onClick={onNavigateAudit} t={t} />}
          <LanguageLink />
          <ThemeToggle />
          <AccountMenu session={session} onLogout={onLogout} />
        </div>
      </div>
    </header>
  );
}

function CaseSwitcher({ cases, onOpenCase, onAllCases }) {
  const { t } = useTranslation();
  const { caseId, setCaseId } = useCurrentCase();
  const current = cases.find((c) => c.case_id === caseId);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="case-switcher"
        className="ml-4 hidden min-w-0 max-w-xs items-center gap-2 border-l border-white/30 py-1 pl-4 text-left text-sm hover:underline md:flex"
      >
        <span className="text-navy-100">{t('case_switcher.label')}</span>
        <span className="truncate font-mono font-semibold">{caseId || t('case_switcher.none')}</span>
        {caseId && (current ? isConfidentialLevel(current.security_level) : true) && (
          <Lock className="h-3.5 w-3.5 shrink-0 text-purple-200" aria-hidden="true" />
        )}
        <ChevronDown className="h-4 w-4 shrink-0 text-navy-100" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-96">
        <DropdownMenuLabel>{t('case_switcher.choose')}</DropdownMenuLabel>
        {cases.length === 0 && (
          <p className="px-2.5 py-2 text-sm text-fg-muted">{t('case_switcher.empty')}</p>
        )}
        {cases.map((c) => (
          <DropdownMenuItem
            key={c.case_id}
            onSelect={() => {
              setCaseId(c.case_id);
              onOpenCase();
            }}
            className="flex-col items-stretch gap-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 font-mono text-sm font-medium text-fg">
                {c.case_id === caseId && <Check className="h-3.5 w-3.5 text-brand-fg" aria-hidden="true" />}
                {c.case_id}
              </span>
              <SecurityBadge level={c.security_level} size="sm" />
            </div>
            {c.last_analysis?.statutory_deadline && <DeadlineCell iso={c.last_analysis.statutory_deadline} />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onAllCases}>
          <FolderOpen className="h-4 w-4" aria-hidden="true" />
          {t('case_switcher.all_cases')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AccountMenu({ session, onLogout }) {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const isDark = theme === 'dark';
  const isZh = (i18n.language || '').startsWith('zh');
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="account-menu"
        aria-label={t('account.menu')}
        className="flex items-center gap-2 rounded-brand px-2 py-1.5 hover:bg-white/10"
      >
        <UserRound className="h-5 w-5" aria-hidden="true" />
        <span className="hidden text-left leading-tight lg:block">
          <span className="block text-sm font-semibold">{session?.display_name}</span>
          <span className="block text-xs text-navy-100">
            {t(`shell.role_badge.${session?.role || 'attorney'}`, { defaultValue: session?.role })}
          </span>
        </span>
        <ChevronDown className="h-4 w-4 text-navy-100" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <div className="px-2.5 py-2">
          <p className="text-xs text-fg-muted">{t('account.signed_in_as')}</p>
          <p className="text-sm font-medium text-fg">{session?.display_name}</p>
          <p className="mt-1 text-xs text-fg-muted">
            {t('account.tenant')}：<span className="font-mono">{session?.tenant_id}</span>
          </p>
        </div>
        <DropdownMenuSeparator />
        {/* Language + theme live here too so phones can reach them (UX_REVIEW A8). */}
        <DropdownMenuItem onSelect={() => applyLanguage(isZh ? 'en' : 'zh-TW')}>
          <Languages className="h-4 w-4" aria-hidden="true" />
          {t('account.language')}：{isZh ? 'English' : '繁體中文'}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme(isDark ? 'light' : 'dark')}>
          {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
          {isDark ? t('account.theme_light') : t('account.theme_dark')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onLogout} data-testid="logout">
          <LogOut className="h-4 w-4" aria-hidden="true" />
          {t('account.logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/* -------------------------------------------------------------------------- */
/*  Language / theme                                                          */
/* -------------------------------------------------------------------------- */

const LANG_KEY = 'pm.lang';

function applyLanguage(lng) {
  i18n.changeLanguage(lng);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = htmlLangFor(lng);
  }
  try {
    localStorage.setItem(LANG_KEY, lng);
  } catch {
    /* localStorage may be unavailable (private mode) — non-fatal. */
  }
}

/** Restore the language the user picked last time (once per session). */
function useSavedLanguage() {
  useEffect(() => {
    let saved = null;
    try {
      saved = localStorage.getItem(LANG_KEY);
    } catch {
      saved = null;
    }
    applyLanguage(saved || i18n.language || 'zh-TW');
  }, []);
}

/** The other language as a plain text link — the way government sites offer it. */
function LanguageLink() {
  const { i18n: inst } = useTranslation();
  const isZh = (inst.language || '').startsWith('zh');
  return (
    <button
      type="button"
      onClick={() => applyLanguage(isZh ? 'en' : 'zh-TW')}
      lang={isZh ? 'en' : 'zh-Hant-TW'}
      className="hidden rounded-brand px-2 py-1 text-sm text-white underline-offset-4 hover:underline sm:inline"
    >
      {isZh ? 'English' : '中文'}
    </button>
  );
}

function ThemeToggle() {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const isDark = theme === 'dark';
  const label = isDark ? t('shell.theme.to_light') : t('shell.theme.to_dark');
  return (
    <button
      type="button"
      data-testid="theme-toggle"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label={label}
      title={label}
      className="hidden h-8 w-8 items-center justify-center rounded-brand text-navy-50 hover:bg-white/10 sm:inline-flex"
    >
      {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
    </button>
  );
}

/** Audit roles only: whether the hash chain verified, linking to the log. */
function ChainChip({ state, onClick, t }) {
  const { failed, tone, labelKey } = chainChipView(state, true);
  const Icon = failed ? ShieldAlert : ShieldCheck;
  const label = t(labelKey);
  const rowsText =
    state.verified > 0 ? t('shell.audit_chip.rows', { rows: state.verified.toLocaleString() }) : null;
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="trust-chain-chip"
      aria-label={rowsText ? `${label} · ${rowsText}` : label}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-brand px-2.5 py-1 text-xs font-medium ring-1 transition-colors',
        tone
      )}
      title={failed ? t('shell.audit_chip.fail') : t('shell.audit_chip.tooltip')}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      <span className="hidden whitespace-nowrap sm:inline">{label}</span>
      {rowsText && <span className="hidden font-mono opacity-80 xl:inline">· {rowsText}</span>}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  Service navigation + data-handling status                                 */
/* -------------------------------------------------------------------------- */

function ServiceNav({ items, session, trustContext, cases, onWorkspace }) {
  const { t } = useTranslation();
  return (
    <div className="border-b border-line bg-surface-raised">
      <div className={cn(CONTAINER, 'flex flex-wrap items-stretch justify-between gap-x-8')}>
        <nav aria-label={t('nav.primary')} data-testid="primary-nav" className="-mb-px flex gap-6 overflow-x-auto">
          {items.map(({ id, to, label }) => (
            <NavLink
              key={id}
              to={to}
              data-testid={`nav-${id}`}
              className={({ isActive }) =>
                cn(
                  'whitespace-nowrap border-b-4 py-3 text-base transition-colors',
                  isActive
                    ? 'border-accent font-bold text-fg'
                    : 'border-transparent text-fg-link hover:border-line-strong hover:text-fg'
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <TrustStatus session={session} trustContext={trustContext} cases={cases} onWorkspace={onWorkspace} />
      </div>
    </div>
  );
}

/**
 * What happens to the data right now, in words: masking, where the mapping
 * lives, and which models the current case may use. Plain text with one
 * colour for the one state that matters (confidential) — not a chip row.
 */
function TrustStatus({ session, trustContext, cases, onWorkspace }) {
  const { t } = useTranslation();
  const { caseId } = useCurrentCase();
  // In the workspace the case being analysed (reported by Analyze) is the one
  // whose routing matters; elsewhere it is the selected case.
  const activeCase = (onWorkspace && trustContext?.caseId) || caseId || '';
  const maskedCount = onWorkspace ? (trustContext?.maskedEntityCount ?? 0) : 0;
  const row = cases?.find((c) => c.case_id === activeCase);
  // Fail-closed: a case we don't have a registry answer for is confidential.
  const level = row?.security_level;
  const confidential = activeCase ? (level ? isConfidentialLevel(level) : true) : false;

  let routing;
  if (!activeCase) {
    routing = { tone: 'muted', Icon: Cloud, label: t('case_switcher.none'), hint: t('security.unknown_hint') };
  } else if (confidential) {
    routing = {
      tone: 'confidential',
      Icon: Lock,
      label: t('shell.trust.routing_confidential'),
      hint: level ? t('security.confidential_hint') : t('security.unknown_hint'),
    };
  } else {
    routing = { tone: 'plain', Icon: Cloud, label: t('shell.trust.routing_auto'), hint: t('security.public_hint') };
  }

  return (
    <div data-testid="trust-band" className="flex flex-wrap items-center gap-x-5 gap-y-1 py-2.5 text-sm">
      <TrustItem
        testId="trust-redaction"
        Icon={Shield}
        label={
          maskedCount > 0
            ? t('shell.trust.redaction_active', { count: maskedCount })
            : t('shell.trust.redaction_default')
        }
        hint={t('shell.trust.redaction_tooltip')}
      />
      <TrustItem
        testId="trust-mapping"
        Icon={Server}
        label={t('shell.trust.mapping_default')}
        hint={t('shell.trust.mapping_tooltip')}
      />
      <TrustItem testId="trust-routing" Icon={routing.Icon} tone={routing.tone} label={routing.label} hint={routing.hint} />
      {session?.tenant_id && (
        <span className="hidden text-fg-muted md:inline">
          {t('shell_extra.tenant')} <span className="font-mono text-fg-secondary">{session.tenant_id}</span>
        </span>
      )}
    </div>
  );
}

const TRUST_TONE = {
  plain: 'text-fg-secondary',
  muted: 'text-fg-muted',
  confidential: 'font-semibold text-confidential',
};

function TrustItem({ Icon, label, hint, tone = 'plain', testId }) {
  return (
    <Tooltip content={hint}>
      <span
        data-testid={testId}
        tabIndex={0}
        aria-description={hint}
        className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', TRUST_TONE[tone])}
      >
        <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        {label}
      </span>
    </Tooltip>
  );
}

function ShellFooter({ t }) {
  return (
    <footer className="border-t border-line bg-surface-raised">
      <div className={cn(CONTAINER, 'flex flex-wrap items-center gap-x-4 gap-y-1 py-2')}>
        <StackStatus />
        <span className="ml-auto hidden text-xs text-fg-muted sm:inline">{t('landing.footer')}</span>
      </div>
    </footer>
  );
}
