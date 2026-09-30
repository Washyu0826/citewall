import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';

import { cn } from '../../lib/utils';

const WORKSPACE_STEPS =['input', 'redact', 'analyze', 'review', 'export'];

/**
 * Where the attorney is in the flow: 輸入 OA → 確認遮罩 → 分析 → 逐句審閱 → 簽核匯出.
 * `current` is one of WORKSPACE_STEPS; earlier steps render as done.
 */
export default function Stepper({ current }) {
  const { t } = useTranslation();
  const currentIdx = Math.max(0, WORKSPACE_STEPS.indexOf(current));
  return (
    <nav aria-label={t('workspace.steps.label')}>
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-2" data-testid="workspace-stepper">
        {WORKSPACE_STEPS.map((step, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          return (
            <li key={step} className="flex items-center gap-2" aria-current={active ? 'step' : undefined}>
              {i > 0 && (
                <span
                  className={cn('hidden h-px w-6 sm:block lg:w-10', done || active ? 'bg-brand-fg' : 'bg-line-strong')}
                  aria-hidden="true"
                />
              )}
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  done && 'bg-primary text-white',
                  active && 'bg-accent text-slate-950',
                  !done && !active && 'border border-line-strong text-fg-muted'
                )}
                aria-hidden="true"
              >
                {done ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : i + 1}
              </span>
              <span className={cn('text-sm', active ? 'font-semibold text-fg' : done ? 'text-fg-secondary' : 'text-fg-muted')}>
                {t(`workspace.steps.${step}`)}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
