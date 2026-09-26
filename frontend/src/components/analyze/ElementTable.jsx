import { useTranslation } from 'react-i18next';
import { Table2 } from 'lucide-react';

import { coveragePct, statusCounts, statusKey, statusTone } from '../../lib/elementTable.js';

const TONE_CLS = {
  rose: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  slate: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
};

/**
 * Q15/Q16 claim-element comparison table for one rejection.
 *
 * One table per charted independent claim: element | prior-art passage |
 * finding | difference. The passage button uses the same onCitationClick
 * contract as the draft citation pills, so the ReferencesPane scrolls to and
 * highlights the matching reference card.
 */
export default function ElementTable({ tables, onCitationClick }) {
  const { t } = useTranslation();
  if (!tables?.length) return null;
  return (
    <section className="space-y-4" data-testid="element-tables" aria-label={t('element_table.heading')}>
      {tables.map((table) => (
        <ClaimTable
          key={`${table.rejection_id}-${table.claim_no}`}
          table={table}
          onCitationClick={onCitationClick}
          t={t}
        />
      ))}
    </section>
  );
}

function ClaimTable({ table, onCitationClick, t }) {
  const counts = statusCounts(table);
  const headingId = `et-${table.rejection_id}-${table.claim_no}`;
  return (
    <div className="rounded-md border dark:border-slate-700" data-testid="element-table">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2 text-xs dark:border-slate-700">
        <Table2 className="h-4 w-4 text-navy-700 dark:text-navy-300" aria-hidden="true" />
        <span id={headingId} className="font-semibold">
          {t('element_table.heading')} · {t('element_table.claim', { no: table.claim_no })}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-2xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {t(`element_table.method.${table.method === 'llm' ? 'llm' : 'rules'}`)}
        </span>
        <span className="ml-auto flex flex-wrap gap-1">
          {['disclosed', 'partial', 'not_disclosed'].map((s) =>
            counts[s] ? (
              <StatusChip key={s} status={s} t={t} suffix={` ${counts[s]}`} />
            ) : null
          )}
        </span>
      </div>
      {table.evidence_available === false && (
        <p className="border-b px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300" data-testid="element-table-no-evidence">
          {t('element_table.no_evidence_note')}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs" aria-labelledby={headingId}>
          <thead className="bg-slate-50 text-2xs uppercase tracking-wider text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-3 py-1.5">{t('element_table.col_element')}</th>
              <th scope="col" className="px-3 py-1.5">{t('element_table.col_evidence')}</th>
              <th scope="col" className="px-3 py-1.5">{t('element_table.col_status')}</th>
              <th scope="col" className="px-3 py-1.5">{t('element_table.col_difference')}</th>
            </tr>
          </thead>
          <tbody className="divide-y dark:divide-slate-700">
            {table.elements.map((el) => (
              <tr key={el.index} className="align-top" data-testid="element-row" data-status={el.status}>
                <td className="px-3 py-2">
                  {el.is_preamble && (
                    <span className="mr-1 text-2xs uppercase text-slate-500 dark:text-slate-400">
                      {t('element_table.preamble')}
                    </span>
                  )}
                  {el.text}
                </td>
                <td className="px-3 py-2">
                  <Evidence el={el} onCitationClick={onCitationClick} t={t} />
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  <StatusChip status={el.status} t={t} />
                  {coveragePct(el.lexical_support) != null && el.status !== 'no_evidence' && (
                    <div className="mt-1 text-2xs text-slate-500 dark:text-slate-400">
                      {t('element_table.score', { pct: coveragePct(el.lexical_support) })}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-slate-700 dark:text-slate-200">
                  <Difference el={el} t={t} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t px-3 py-1.5 text-2xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {t('element_table.disclaimer')}
      </p>
    </div>
  );
}

function StatusChip({ status, t, suffix = '' }) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-2xs font-medium ${TONE_CLS[statusTone(status)]}`}
      data-testid="element-status"
    >
      {t(statusKey(status))}
      {suffix}
    </span>
  );
}

function Evidence({ el, onCitationClick, t }) {
  const ev = el.evidence;
  if (!ev) return <span className="text-slate-400">—</span>;
  const label = `${ev.patent_no}${ev.section ? ` / ${ev.section}` : ''}`;
  return (
    <div>
      {onCitationClick ? (
        <button
          type="button"
          onClick={() => onCitationClick({ patentNo: ev.patent_no, nonce: Date.now() })}
          aria-label={t('element_table.open_ref', { patent: ev.patent_no })}
          className="font-mono text-2xs text-navy-700 underline decoration-dotted hover:text-navy-900 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-navy-500 dark:text-navy-300"
          data-testid="element-evidence-link"
        >
          [{ev.ref_index}] {label}
        </button>
      ) : (
        <span className="font-mono text-2xs">[{ev.ref_index}] {label}</span>
      )}
      <p className="mt-1 line-clamp-4 text-slate-600 dark:text-slate-300" title={ev.passage}>
        {ev.passage}
      </p>
    </div>
  );
}

function Difference({ el, t }) {
  if (el.status === 'no_evidence') return <span className="text-slate-400">—</span>;
  if (el.missing_terms?.length) {
    return <span>{t('element_table.missing', { terms: el.missing_terms.join('、') })}</span>;
  }
  return <span className="text-slate-500 dark:text-slate-400">{t('element_table.all_found')}</span>;
}
