import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router';

import Login from './components/Login.jsx';
import AppShell from './components/AppShell.jsx';
import { PageLoading } from './components/PageLoading.jsx';
import RouteErrorBoundary from './components/RouteErrorBoundary.jsx';
import { CurrentCaseProvider, useCurrentCase } from './lib/currentCase.jsx';
import { WorkspaceProvider } from './lib/workspace.jsx';
import { SESSION_EXPIRED_EVENT, api } from './api/client.js';
import { queryClient } from './lib/queryClient.js';
import { toast } from './lib/toast.jsx';
import i18n from './lib/i18n.js';

// 設計系統審稿頁（/design）— 內部用，lazy load 讓它不進主 bundle。
const DesignSystem = lazy(() => import('./components/DesignSystem.jsx'));

// Every signed-in page loads on demand (research 09 FE-L4): the first load
// was one 368 KB chunk with every page in it, so an auditor downloaded the
// whole analysis workspace before seeing the audit log. The login screen and
// the shell stay in the entry chunk — they are the first paint.
const loadAnalyze = () => import('./components/Analyze.jsx');
const loadAuditView = () => import('./components/AuditView.jsx');
const loadCaseAdmin = () => import('./components/CaseAdmin.jsx');
const loadHome = () => import('./components/pages/Home.jsx');
const loadCases = () => import('./components/pages/Cases.jsx');
const Analyze = lazy(loadAnalyze);
const AuditView = lazy(loadAuditView);
const CaseAdmin = lazy(loadCaseAdmin);
const Home = lazy(loadHome);
const Cases = lazy(loadCases);

// The pages each role's navigation leads to, fetched while the browser is
// idle right after sign-in (review W2b-E2). Two reasons: the first click needs
// no download, and an open tab keeps working across a redeploy — the new
// image no longer serves the old hashed chunk files, and a chunk fetched only
// later would 404 (and a reload signs the user out: the session is memory-only).
const PAGES_FOR_ROLE = {
  attorney: [loadHome, loadAnalyze, loadCases],
  paralegal: [loadHome, loadAnalyze, loadCases],
  auditor: [loadAuditView, loadCases],
  it_admin: [loadCaseAdmin, loadAuditView],
};

function usePrefetchPages(role) {
  useEffect(() => {
    const loaders = PAGES_FOR_ROLE[role];
    if (!loaders) return undefined;
    const run = () => loaders.forEach((load) => load().catch(() => {}));
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(run, { timeout: 3000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = setTimeout(run, 1500);
    return () => clearTimeout(id);
  }, [role]);
}

function DesignRoute() {
  return (
    <Suspense fallback={null}>
      <DesignSystem />
    </Suspense>
  );
}

/**
 * Role-aware landing route — each role lands on the page it actually uses:
 *   • attorney / paralegal → /home         (deadlines + cases)
 *   • auditor              → /audit        (read-only audit log)
 *   • it_admin             → /admin/cases  (case registry)
 */
function landingPathForRole(role) {
  switch (role) {
    case 'auditor':
      return '/audit';
    case 'it_admin':
      return '/admin/cases';
    default:
      return '/home';
  }
}

const CASE_WORK_ROLES = ['attorney', 'paralegal'];

/**
 * Slice B + Day 9C: router-based shell with persistent chrome.
 *
 * Session lives in App state (same as the original POC — production switches
 * to httpOnly cookie set by gateway, see CLAUDE.md). After CHUNK-1 every
 * authenticated route is wrapped in <AppShell>, which owns the top bar,
 * trust band (CHUNK-8), and left nav rail. Each child page receives
 * `embedded` so its in-component header is suppressed; the three-pane
 * Analyze grid + AuditView's table layout are otherwise untouched.
 *
 * `trustContext` is the upward channel from the active route to the shell's
 * trust band — Analyze pushes the current case_id + redaction count so the
 * Routing chip + Redaction chip reflect the live analysis instead of static
 * defaults.
 */
export default function App() {
  const [session, setSession] = useState(null);
  // Lifted to App so it survives route changes; routes call setTrustContext.
  const [trustContext, setTrustContext] = useState({ caseId: '', maskedEntityCount: 0 });
  // Keys the per-page error boundary: navigating away clears a page's error.
  const { pathname } = useLocation();
  usePrefetchPages(session?.role);

  const handleLogout = useCallback(() => {
    setSession((cur) => {
      // Best-effort server-side revocation (H-5); a failure must not block the
      // local logout — the token still expires at JWT_EXPIRES_MIN.
      if (cur?.token) api.logout(cur.token).catch(() => {});
      return null;
    });
    setTrustContext({ caseId: '', maskedEntityCount: 0 });
    // Query keys are not user-scoped — drop cached server state so the next
    // user on this browser never sees the previous user's audit/quota data.
    queryClient.clear();
  }, []);

  // Server-side session death (expired JWT / revoked jti) surfaces as a 401
  // on any authed call — the api client emits one event, we log out once and
  // tell the user why they're back at the login screen instead of letting
  // every query silently fail in place.
  useEffect(() => {
    const onExpired = () => {
      setSession((cur) => {
        if (cur) toast.error(i18n.t('session_expired'));
        return null;
      });
      setTrustContext({ caseId: '', maskedEntityCount: 0 });
      queryClient.clear();
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  if (!session) {
    // Login + the design-system review page are the only public routes.
    return (
      <Routes>
        <Route path="/login" element={<LoginRoute onLogin={setSession} />} />
        <Route path="/design" element={<DesignRoute />} />
        <Route path="*" element={<LoginRoute onLogin={setSession} />} />
      </Routes>
    );
  }

  const landingPath = landingPathForRole(session.role);
  const canWorkCases = CASE_WORK_ROLES.includes(session.role);

  return (
    // Keyed by user so a new login never inherits the previous user's case.
    <CurrentCaseProvider key={session.user_id || session.display_name}>
      <WorkspaceProvider>
      <AppShell session={session} onLogout={handleLogout} trustContext={trustContext}>
        <RouteErrorBoundary key={pathname}>
        <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<Navigate to={landingPath} replace />} />
          {canWorkCases && <Route path="/home" element={<Home session={session} />} />}
          {canWorkCases && (
            <Route
              path="/analyze"
              element={
                <AnalyzeRoute
                  session={session}
                  onLogout={handleLogout}
                  onTrustChange={setTrustContext}
                />
              }
            />
          )}
          {session.role !== 'it_admin' && <Route path="/cases" element={<Cases session={session} />} />}
          <Route path="/audit" element={<AuditRoute session={session} onLogout={handleLogout} />} />
          {/* Q27 case-registry admin — only mounted for it_admin (the gateway
              403s every other role as well). */}
          {session.role === 'it_admin' && (
            <Route path="/admin/cases" element={<CaseAdmin session={session} />} />
          )}
          <Route path="/design" element={<DesignRoute />} />
          <Route path="*" element={<Navigate to={landingPath} replace />} />
        </Routes>
        </Suspense>
        </RouteErrorBoundary>
      </AppShell>
      </WorkspaceProvider>
    </CurrentCaseProvider>
  );
}

function LoginRoute({ onLogin }) {
  const navigate = useNavigate();
  // Login expects a single onLogin(session) callback; preserve that contract.
  // Route to the role-appropriate landing page (auditor/it_admin → /audit).
  return (
    <Login
      onLogin={(s) => {
        onLogin(s);
        navigate(landingPathForRole(s?.role), { replace: true });
      }}
    />
  );
}

/**
 * Adapter: existing Analyze/AuditView use onSwitchView('analyze' | 'audit').
 * The shell owns top-level nav now, but legacy callers inside the components
 * (e.g. result-summary deep links) still rely on the contract.
 */
function buildSwitchView(navigate) {
  return (view) => {
    if (view === 'analyze') navigate('/analyze');
    else if (view === 'audit') navigate('/audit');
    else if (view === 'cases') navigate('/cases');
    else navigate('/analyze');
  };
}

function AnalyzeRoute({ session, onLogout, onTrustChange }) {
  const navigate = useNavigate();
  const { caseId } = useCurrentCase();
  return (
    // Analyze follows `initialCaseId` itself (keeps the typed OA, drops the
    // old result) — no remount on case switch.
    <Analyze
      session={session}
      onLogout={onLogout}
      onSwitchView={buildSwitchView(navigate)}
      embedded
      onTrustChange={onTrustChange}
      initialCaseId={caseId || undefined}
    />
  );
}

function AuditRoute({ session, onLogout }) {
  return <AuditView session={session} onLogout={onLogout} />;
}
