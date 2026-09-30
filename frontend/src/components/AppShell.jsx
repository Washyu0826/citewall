/* eslint-disable react-refresh/only-export-components -- navItemsForRole is shared with App.jsx */
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
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
import { isConfidentialLevel } from '../lib/cases.js';
import { chainChipView } from '../lib/chainChip.js';
import { cn } from '../lib/utils';
import { Badge } from './ui/badge.jsx';
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
import StackStatus from './StackStatus.jsx';
import { DeadlineCell, SecurityBadge } from './cases/CaseBits.jsx';

/**
 * Authenticated chrome: brand bar (case switcher, audit-chain chip, account
 * menu), trust band, role-aware navigation and — for IT/audit roles only —
 * the integration status footer.
 *
 * Trust signals come from the server: the routing chip reads the current
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
  const [navCollapsed, setNavCollapsed] = useState(false);
  const role = session?.role;

  const isAuditor = role === 'auditor';
  const canCallAudit = isAuditor || role === 'it_admin';
  const canListCases = CASE_LIST_ROLES.includes(role);

  const verifyQ = useAuditVerify(session?.token, isAuditor ? 'global' : 'tenant', {
    poll: true,
    enabled: canCallAudit,
  });
  const casesQ = useCases(session?.token, canListCases);
  const cases = casesQ.data?.cases;

  const auditState = useMemo(() => {
    if (!canCallAudit) return { status: 'idle', verified: 0, broken: 0, error: null };
    if (verifyQ.error) {
      return { status: 'fail', verified: 0, broken: 0, error: verifyQ.error?.message || 'verify failed' };
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
          onLogout={onLogout}
          auditState={auditState}
          canCallAudit={canCallAudit}
          onNavigateAudit={() => navigate('/audit')}
          cases={CASE_ROLES.includes(role) ? cases : null}
          onOpenCase={() => navigate('/analyze')}
          onAllCases={() => navigate('/cases')}
        />
        <TrustBand
          session={session}
          trustContext={trustContext}
          cases={cases}
          onWorkspace={location.pathname === '/analyze'}
        />
        <div className="flex min-h-0 flex-1">
          <NavRail
            items={navItems}
            collapsed={navCollapsed}
            setCollapsed={setNavCollapsed}
            activePath={location.pathname}
            onNavigate={navigate}
            t={t}
          />
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">
            {children}
          </main>
        </div>
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
    <header className="border-b-2 border-accent bg-brand text-white">
      <div className="mx-auto flex h-14 max-w-[1920px] items-center gap-3 px-4 sm:px-6">
        <div className="flex shrink-0 items-center gap-2.5">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-brand bg-white text-sm font-bold tracking-tight text-navy-900"
            aria-hidden="true"
          >
            CW
          </div>
          <span className="text-base font-semibold tracking-tight">{t('app_title')}</span>
          <span className="hidden rounded bg-white/10 px-1.5 py-0.5 text-2xs font-medium uppercase tracking-wider text-navy-100 ring-1 ring-white/15 md:inline">
            {t('app_tag_poc')}
          </span>
        </div>

        {cases && <CaseSwitcher cases={cases} onOpenCase={onOpenCase} onAllCases={onAllCases} />}

        <div className="ml-auto flex items-center gap-2">
          <ChainChip state={auditState} canCallAudit={canCallAudit} onClick={onNavigateAudit} t={t} />
          <div className="hidden items-center gap-2 sm:flex">
            <LanguageToggle />
            <ThemeToggle />
          </div>
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
        className="ml-2 hidden min-w-0 max-w-xs items-center gap-2 rounded-brand bg-white/10 px-3 py-1.5 text-left text-sm ring-1 ring-white/15 hover:bg-white/15 md:flex"
      >
        <span className="text-navy-100">{t('case_switcher.label')}</span>
        <span className="truncate font-mono font-medium">{caseId || t('case_switcher.none')}</span>
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
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/20">
          <UserRound className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="hidden text-left leading-tight lg:block">
          <span className="block text-sm font-medium">{session?.display_name}</span>
          <span className="block text-2xs text-navy-100">
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

function LanguageToggle() {
  const { t } = useTranslation();
  const [lang, setLang] = useState(i18n.language || 'zh-TW');

  useEffect(() => {
    let saved = null;
    try {
      saved = localStorage.getItem(LANG_KEY);
    } catch {
      saved = null;
    }
    const initial = saved || i18n.language || 'zh-TW';
    applyLanguage(initial);
    setLang(initial);
  }, []);

  useEffect(() => {
    const onChange = (lng) => setLang(lng);
    i18n.on('languageChanged', onChange);
    return () => i18n.off('languageChanged', onChange);
  }, []);

  const isZh = (lang || '').startsWith('zh');
  return (
    <div
      className="flex items-center rounded-brand bg-white/10 p-0.5 ring-1 ring-white/15"
      role="group"
      aria-label={t('shell_extra.language')}
    >
      <LangButton active={isZh} onClick={() => applyLanguage('zh-TW')} label="繁中" />
      <LangButton active={!isZh} onClick={() => applyLanguage('en')} label="EN" />
    </div>
  );
}

function LangButton({ active, onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded px-2 py-1 text-xs font-medium transition-colors',
        active ? 'bg-white text-navy-900' : 'text-navy-50 hover:bg-white/15'
      )}
    >
      {label}
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
      className="inline-flex h-8 w-8 items-center justify-center rounded-brand bg-white/10 text-navy-50 ring-1 ring-white/15 hover:bg-white/20"
    >
      {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
    </button>
  );
}

function ChainChip({ state, canCallAudit, onClick, t }) {
  const { failed, tone, labelKey } = chainChipView(state, canCallAudit);
  const Icon = failed ? ShieldAlert : ShieldCheck;
  const label = t(labelKey);
  const rowsText =
    canCallAudit && state.verified > 0
      ? t('shell.audit_chip.rows', { rows: state.verified.toLocaleString() })
      : null;
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
/*  Trust band                                                                */
/* -------------------------------------------------------------------------- */

function TrustBand({ session, trustContext, cases, onWorkspace }) {
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
    routing = { tone: 'neutral', Icon: Cloud, label: t('case_switcher.none'), hint: t('security.unknown_hint') };
  } else if (confidential) {
    routing = {
      tone: 'confidential',
      Icon: Lock,
      label: t('shell.trust.routing_confidential'),
      hint: level ? t('security.confidential_hint') : t('security.unknown_hint'),
    };
  } else {
    routing = { tone: 'success', Icon: Cloud, label: t('shell.trust.routing_auto'), hint: t('security.public_hint') };
  }

  return (
    <div className="border-b border-line bg-surface-raised">
      <div
        data-testid="trust-band"
        className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-2 px-4 py-1.5 sm:px-6"
      >
        <TrustChip
          testId="trust-redaction"
          Icon={Shield}
          tone="brand"
          label={
            maskedCount > 0
              ? t('shell.trust.redaction_active', { count: maskedCount })
              : t('shell.trust.redaction_default')
          }
          hint={t('shell.trust.redaction_tooltip')}
        />
        <TrustChip
          testId="trust-mapping"
          Icon={Server}
          tone="neutral"
          label={t('shell.trust.mapping_default')}
          hint={t('shell.trust.mapping_tooltip')}
        />
        <TrustChip testId="trust-routing" Icon={routing.Icon} tone={routing.tone} label={routing.label} hint={routing.hint} />
        {session?.tenant_id && (
          <span className="ml-auto hidden items-center gap-1.5 text-xs text-fg-muted sm:flex">
            {t('shell_extra.tenant')}
            <span className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-fg-secondary">
              {session.tenant_id}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}

function TrustChip({ Icon, label, hint, tone, testId }) {
  return (
    <Tooltip content={hint}>
      <Badge data-testid={testId} tone={tone} tabIndex={0} aria-description={hint}>
        <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
        <span>{label}</span>
      </Badge>
    </Tooltip>
  );
}

/* -------------------------------------------------------------------------- */
/*  Navigation                                                                */
/* -------------------------------------------------------------------------- */

function NavRail({ items, collapsed, setCollapsed, activePath, onNavigate, t }) {
  return (
    <nav
      aria-label={t('nav.primary')}
      data-testid="nav-rail"
      className={cn(
        'flex w-16 shrink-0 flex-col border-r border-line bg-surface-raised transition-[width] duration-150',
        collapsed ? 'sm:w-16' : 'sm:w-56'
      )}
    >
      <ul className="flex-1 space-y-1 px-2 py-3">
        {items.map(({ id, to, label, Icon }) => {
          const isActive = activePath === to || activePath.startsWith(to + '/');
          return (
            <li key={id}>
              <Tooltip content={collapsed ? label : null} side="right">
                <button
                  type="button"
                  onClick={() => onNavigate(to)}
                  aria-current={isActive ? 'page' : undefined}
                  aria-label={label}
                  data-testid={`nav-${id}`}
                  className={cn(
                    'relative flex h-10 w-full items-center gap-3 rounded-brand px-3 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-brand-soft text-brand-fg'
                      : 'text-fg-secondary hover:bg-surface-hover hover:text-fg'
                  )}
                >
                  {isActive && (
                    <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" aria-hidden="true" />
                  )}
                  <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} aria-hidden="true" />
                  <span className={cn('truncate', collapsed ? 'hidden' : 'hidden sm:inline')}>{label}</span>
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ul>
      <div className="hidden border-t border-line p-2 sm:block">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
          className="flex h-9 w-full items-center justify-center rounded-brand text-fg-muted hover:bg-surface-hover hover:text-fg"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
      </div>
    </nav>
  );
}

function ShellFooter({ t }) {
  return (
    <footer className="border-t border-line bg-surface-raised">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6">
        <StackStatus />
        <span className="ml-auto hidden text-xs text-fg-muted sm:inline">{t('landing.footer')}</span>
      </div>
    </footer>
  );
}
