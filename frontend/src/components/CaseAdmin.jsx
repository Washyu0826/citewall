import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Lock, Plus, Search } from 'lucide-react';

import { adminApi, filterCases, normalizeRegistry } from '../api/admin.js';
import { formatDate } from '../lib/cases.js';
import { toast } from '../lib/toast.jsx';
import { useMediaQuery } from '../lib/useMediaQuery.js';
import { Button } from './ui/button.jsx';
import { Field, Input, Select } from './ui/field.jsx';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/overlay.jsx';
import { Page, PageHeader, Section } from './ui/page.jsx';
import { Skeleton } from './Skeleton.jsx';

const EMPTY_DRAFT = { case_id: '', security_level: 'confidential', note: '' };

// Below md the registry is a card list: a six-column table with a select in
// it only fits a phone by scrolling sideways, and its row actions end up
// off-screen.
const TABLE_QUERY = '(min-width: 768px)';

/**
 * Case-registry admin (it_admin only — the route is not mounted for other
 * roles and the gateway 403s them anyway). Lists registered cases, lets the
 * admin add a case or change its confidentiality level, and deactivate it
 * (never delete). Every change is audited server-side with before/after.
 */
export default function CaseAdmin({ session }) {
  const { t } = useTranslation();
  const token = session?.token;
  const [data, setData] = useState(() => normalizeRegistry(null));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(null); // case_id awaiting deactivate confirmation
  const asTable = useMediaQuery(TABLE_QUERY);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(normalizeRegistry(await adminApi.listCases(token)));
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
  const levelLabel = (l) => t(`admin.levels.${l}`, { defaultValue: l });

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
        setDraft(EMPTY_DRAFT);
      },
      t('admin.created', { id: case_id })
    );
  }

  function changeLevel(caseId, level) {
    run(
      () => adminApi.updateCase(token, { case_id: caseId, security_level: level }),
      t('admin.updated_ok', { id: caseId })
    );
  }

  function deactivate(caseId) {
    setConfirming(null);
    run(() => adminApi.deactivateCase(token, caseId), t('admin.deactivated', { id: caseId }));
  }

  // Shared by the table and the card list.
  const levelSelect = (c, className) => (
    <Select
      aria-label={t('admin.level_for', { id: c.case_id })}
      className={className}
      value={c.level}
      disabled={busy}
      onChange={(e) => changeLevel(c.case_id, e.target.value)}
    >
      {data.levels.map((l) => (
        <option key={l} value={l}>
          {levelLabel(l)}
        </option>
      ))}
    </Select>
  );
  const deactivateButton = (c) =>
    c.active && (
      <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirming(c.case_id)}>
        {t('admin.deactivate')}
      </Button>
    );

  return (
    <Page>
      <PageHeader title={t('admin.title')} description={t('admin.intro')} />

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-brand border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          {error.status === 403 ? t('admin.forbidden') : error.message}
        </div>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[1fr_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <Section id="case-admin-add" title={t('admin.add')} description={t('admin_page.add_desc')} className="mb-0">
            <div className="border-t-2 border-fg pt-4">
              <form
                onSubmit={submitNew}
                aria-labelledby="case-admin-add-heading"
                className="grid gap-4 md:grid-cols-[2fr_1.4fr_2fr_auto] md:items-end"
              >
                <Field label={t('admin.case_id')}>
                  <Input
                    value={draft.case_id}
                    maxLength={128}
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                    onChange={(e) => setDraft((d) => ({ ...d, case_id: e.target.value }))}
                    data-testid="admin-new-case-id"
                  />
                </Field>
                <Field label={t('admin.level')}>
                  <Select
                    value={draft.security_level}
                    onChange={(e) => setDraft((d) => ({ ...d, security_level: e.target.value }))}
                    data-testid="admin-new-level"
                  >
                    {data.levels.map((l) => (
                      <option key={l} value={l}>
                        {levelLabel(l)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t('admin.note')} optional optionalLabel={t('admin_page.optional')}>
                  <Input
                    value={draft.note}
                    maxLength={500}
                    onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))}
                  />
                </Field>
                <Button type="submit" disabled={busy || !draft.case_id.trim()} data-testid="admin-add">
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  {t('admin.add')}
                </Button>
              </form>
            </div>
          </Section>

          <section aria-labelledby="case-admin-list" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h2 id="case-admin-list" className="text-xl font-bold text-fg">
                {t('admin_page.registered')}
              </h2>
              <div className="relative w-full sm:ml-auto sm:max-w-xs">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
                  aria-hidden="true"
                />
                <Input
                  id="admin-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('admin_page.search')}
                  aria-label={t('admin_page.search')}
                  className="pl-9"
                />
              </div>
              <p className="text-sm text-fg-muted" aria-live="polite">
                {t('admin_page.count', { count: rows.length })}
              </p>
            </div>

            {loading ? (
              <div className="space-y-3 border-t-2 border-fg pt-4">
                {[0, 1].map((i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <p className="border-t-2 border-fg py-6 text-fg-muted">{t('admin.empty')}</p>
            ) : asTable ? (
              <div className="overflow-x-auto">
                <table className="doc-table" aria-labelledby="case-admin-list">
                  <thead>
                    <tr>
                      <th scope="col">{t('admin.case_id')}</th>
                      <th scope="col">{t('admin.level')}</th>
                      <th scope="col">{t('admin.status')}</th>
                      <th scope="col">{t('admin.note')}</th>
                      <th scope="col">{t('admin.updated')}</th>
                      <th scope="col">
                        <span className="sr-only">{t('admin.actions')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.case_id} data-testid={`admin-row-${c.case_id}`}>
                        <th scope="row" className="whitespace-nowrap font-mono font-semibold text-fg">
                          {c.case_id}
                        </th>
                        <td>{levelSelect(c, 'h-9 min-w-44')}</td>
                        <td>
                          <ActiveText active={c.active} t={t} />
                        </td>
                        <td className="max-w-64 text-fg-secondary">{c.note || '—'}</td>
                        <td className="whitespace-nowrap text-fg-secondary">
                          <UpdatedBy c={c} />
                        </td>
                        <td className="text-right">{deactivateButton(c)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul className="border-t-2 border-fg" aria-labelledby="case-admin-list">
                {rows.map((c) => (
                  <li key={c.case_id} className="flex flex-col gap-3 border-b border-line py-4" data-testid={`admin-row-${c.case_id}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="break-all font-mono font-semibold text-fg">{c.case_id}</span>
                      <ActiveText active={c.active} t={t} />
                    </div>
                    {levelSelect(c)}
                    {c.note && <p className="text-sm text-fg-secondary">{c.note}</p>}
                    <div className="flex items-center justify-between gap-2 text-sm text-fg-secondary">
                      <UpdatedBy c={c} />
                      {deactivateButton(c)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Inset text: the rule an admin must not forget, set off by a rule, not a card. */}
        <aside className="border-l-4 border-confidential py-1 pl-4">
          <h2 className="flex items-center gap-2 text-base font-bold text-fg">
            <Lock className="h-4 w-4 text-confidential" strokeWidth={2} aria-hidden="true" />
            {t('admin_page.fail_closed_title')}
          </h2>
          <p className="mt-1 text-sm text-fg-secondary">{t('admin.fail_closed')}</p>
          {data.patterns.length > 0 && (
            <>
              <h3 className="mt-4 text-sm font-semibold text-fg">{t('admin.patterns')}</h3>
              <ul className="mt-2 flex flex-col gap-1.5">
                {data.patterns.map((p) => (
                  <li key={p.pattern} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                    <code className="font-mono text-fg">{p.pattern}</code>
                    <span className="text-fg-muted">{levelLabel(p.level)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </div>

      <Dialog open={confirming != null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent closeLabel={t('admin_page.cancel')}>
          <DialogHeader>
            <DialogTitle>{t('admin_page.confirm_title', { id: confirming ?? '' })}</DialogTitle>
            <DialogDescription>{t('admin_page.confirm_desc')}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="font-mono text-sm text-fg">{confirming}</p>
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(null)}>
              {t('admin_page.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => deactivate(confirming)} data-testid="admin-deactivate-confirm">
              {t('admin_page.confirm_action')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  );
}

function ActiveText({ active, t }) {
  return (
    <span className={active ? 'whitespace-nowrap text-fg-secondary' : 'whitespace-nowrap text-fg-muted line-through'}>
      {active ? t('admin.active') : t('admin.inactive')}
    </span>
  );
}

function UpdatedBy({ c }) {
  const { i18n } = useTranslation();
  if (!c.updated_by) return <span className="text-fg-muted">—</span>;
  return (
    <span>
      <span className="block">{c.updated_by}</span>
      {c.updated_at && (
        <time dateTime={c.updated_at} className="font-mono text-xs text-fg-muted">
          {formatDate(c.updated_at, i18n.language)}
        </time>
      )}
    </span>
  );
}
