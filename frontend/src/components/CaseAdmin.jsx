import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';

import { adminApi, filterCases } from '../api/admin.js';
import { Button } from './ui/button.jsx';
import { toast } from '../lib/toast.jsx';

/**
 * Q27 case-registry admin (it_admin only — the route is not mounted for other
 * roles and the gateway 403s them anyway). Lists registered cases, lets the
 * admin add a case or change its confidentiality level, and deactivate it
 * (never delete). Every change is audited server-side with before/after.
 */
export default function CaseAdmin({ session }) {
  const { t } = useTranslation();
  const token = session?.token;
  const [data, setData] = useState({ cases: [], patterns: [], levels: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [draft, setDraft] = useState({ case_id: '', security_level: 'confidential', note: '' });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminApi.listCases(token));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => filterCases(data.cases, query), [data.cases, query]);
  const levels = data.levels.length ? data.levels : ['public', 'confidential'];

  async function run(fn, okMsg) {
    setBusy(true);
    try {
      await fn();
      toast.success(okMsg);
      await load();
    } catch (e) {
      toast.error(e?.message || t('admin.error_generic'));
    } finally {
      setBusy(false);
    }
  }

  function submitNew(e) {
    e.preventDefault();
    const case_id = draft.case_id.trim();
    if (!case_id) return;
    run(
      async () => {
        await adminApi.createCase(token, { ...draft, case_id });
        setDraft({ case_id: '', security_level: 'confidential', note: '' });
      },
      t('admin.created', { id: case_id })
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6">
      <header className="flex items-center gap-2">
        <ShieldCheck className="text-navy-700 dark:text-navy-200 h-5 w-5" aria-hidden="true" />
        <h1 id="case-admin-title" className="text-lg font-semibold">
          {t('admin.title')}
        </h1>
      </header>
      <p className="text-sm text-slate-600 dark:text-slate-300">{t('admin.intro')}</p>

      <form
        onSubmit={submitNew}
        aria-labelledby="case-admin-add"
        className="grid gap-3 rounded-lg border bg-white p-4 sm:grid-cols-[2fr_1fr_2fr_auto] dark:border-slate-700 dark:bg-slate-900"
      >
        <h2 id="case-admin-add" className="sr-only">
          {t('admin.add')}
        </h2>
        <label className="text-xs">
          <span className="mb-1 block text-slate-500">{t('admin.case_id')}</span>
          <input
            className="w-full rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
            value={draft.case_id}
            maxLength={128}
            onChange={(e) => setDraft((d) => ({ ...d, case_id: e.target.value }))}
            data-testid="admin-new-case-id"
          />
        </label>
        <label className="text-xs">
          <span className="mb-1 block text-slate-500">{t('admin.level')}</span>
          <select
            className="w-full rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
            value={draft.security_level}
            onChange={(e) => setDraft((d) => ({ ...d, security_level: e.target.value }))}
            data-testid="admin-new-level"
          >
            {levels.map((l) => (
              <option key={l} value={l}>
                {t(`admin.levels.${l}`, { defaultValue: l })}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="mb-1 block text-slate-500">{t('admin.note')}</span>
          <input
            className="w-full rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
            value={draft.note}
            maxLength={500}
            onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))}
          />
        </label>
        <div className="flex items-end">
          <Button type="submit" disabled={busy || !draft.case_id.trim()} data-testid="admin-add">
            {t('admin.add')}
          </Button>
        </div>
      </form>

      <div className="flex items-center gap-2">
        <label htmlFor="admin-search" className="text-xs text-slate-500">
          {t('admin.search')}
        </label>
        <input
          id="admin-search"
          type="search"
          className="w-64 rounded border px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {error.status === 403 ? t('admin.forbidden') : error.message}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border dark:border-slate-700">
        <table className="w-full text-sm" aria-labelledby="case-admin-title">
          <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase dark:bg-slate-800">
            <tr>
              <th scope="col" className="px-3 py-2">
                {t('admin.case_id')}
              </th>
              <th scope="col" className="px-3 py-2">
                {t('admin.level')}
              </th>
              <th scope="col" className="px-3 py-2">
                {t('admin.status')}
              </th>
              <th scope="col" className="px-3 py-2">
                {t('admin.note')}
              </th>
              <th scope="col" className="px-3 py-2">
                {t('admin.updated')}
              </th>
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">{t('admin.actions')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  {t('admin.loading')}
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  {t('admin.empty')}
                </td>
              </tr>
            )}
            {!loading &&
              rows.map((c) => (
                <CaseRow
                  key={c.case_id}
                  c={c}
                  levels={levels}
                  busy={busy}
                  t={t}
                  onLevel={(level) =>
                    run(
                      () =>
                        adminApi.updateCase(token, { case_id: c.case_id, security_level: level }),
                      t('admin.updated_ok', { id: c.case_id })
                    )
                  }
                  onDeactivate={() => {
                    if (!window.confirm(t('admin.confirm_deactivate', { id: c.case_id }))) return;
                    run(
                      () => adminApi.deactivateCase(token, c.case_id),
                      t('admin.deactivated', { id: c.case_id })
                    );
                  }}
                />
              ))}
          </tbody>
        </table>
      </div>

      {data.patterns.length > 0 && (
        <section aria-labelledby="case-admin-patterns" className="text-xs text-slate-500">
          <h2 id="case-admin-patterns" className="mb-1 font-medium">
            {t('admin.patterns')}
          </h2>
          <ul className="list-inside list-disc">
            {data.patterns.map((p) => (
              <li key={p.pattern}>
                <code>{p.pattern}</code> → {t(`admin.levels.${p.level}`, { defaultValue: p.level })}
              </li>
            ))}
          </ul>
          <p className="mt-1">{t('admin.fail_closed')}</p>
        </section>
      )}
    </div>
  );
}

function CaseRow({ c, levels, busy, t, onLevel, onDeactivate }) {
  return (
    <tr className="border-t dark:border-slate-700" data-testid={`admin-row-${c.case_id}`}>
      <td className="px-3 py-2 font-mono">{c.case_id}</td>
      <td className="px-3 py-2">
        <select
          aria-label={t('admin.level_for', { id: c.case_id })}
          className="rounded border px-1 py-0.5 dark:border-slate-600 dark:bg-slate-800"
          value={c.level}
          disabled={busy}
          onChange={(e) => onLevel(e.target.value)}
        >
          {levels.map((l) => (
            <option key={l} value={l}>
              {t(`admin.levels.${l}`, { defaultValue: l })}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2">{c.active ? t('admin.active') : t('admin.inactive')}</td>
      <td className="px-3 py-2">{c.note}</td>
      <td className="px-3 py-2 text-xs text-slate-500">
        {c.updated_by ? `${c.updated_by} · ${c.updated_at?.slice(0, 10) ?? ''}` : '—'}
      </td>
      <td className="px-3 py-2 text-right">
        {c.active && (
          <Button variant="outline" size="sm" disabled={busy} onClick={onDeactivate}>
            {t('admin.deactivate')}
          </Button>
        )}
      </td>
    </tr>
  );
}
