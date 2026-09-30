import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';

import { cn } from '../../lib/utils';
import { Card } from '../ui/card.jsx';

// Stage timings calibrated to the live chain (digiRunner → Dify → qwen2.5:7b,
// 25–28 s measured). An honest approximation, not a progress contract — the
// request is one synchronous call, so the stages are time-based.
const STAGES = [
  { name: 'redact', untilSec: 1 },
  { name: 'parse', untilSec: 10 },
  { name: 'retrieve', untilSec: 12 },
  { name: 'draft', untilSec: 22 },
  { name: 'verify', untilSec: 26 },
  { name: 'deadline', untilSec: 27 },
  { name: 'unmask', untilSec: Infinity },
];

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export default function RunningPanel() {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);

  const elapsedMs = now - startRef.current;
  const idx = STAGES.findIndex((s) => elapsedMs / 1000 < s.untilSec);
  const currentIdx = idx === -1 ? STAGES.length - 1 : idx;

  return (
    <Card className="mx-auto w-full max-w-xl p-6" role="status" aria-live="polite">
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Loader2 className="h-5 w-5 animate-spin text-brand-fg" aria-hidden="true" />
          <span className="text-base font-semibold text-fg">{t('analyze.drafts.analyzing')}</span>
        </div>
        <span className="font-mono text-2xl text-brand-fg">{fmtElapsed(elapsedMs)}</span>
      </div>
      <ol className="space-y-2.5">
        {STAGES.map((stage, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          return (
            <li key={stage.name} className="flex items-center gap-3 text-sm">
              <span className={cn('flex w-5 justify-center', done ? 'text-success' : active ? 'text-brand-fg' : 'text-fg-muted')}>
                {done ? (
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                ) : active ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Circle className="h-4 w-4" aria-hidden="true" />
                )}
              </span>
              <span className={cn(done ? 'text-fg-muted' : active ? 'font-medium text-fg' : 'text-fg-muted')}>
                {t(`analyze.stages.${stage.name}`)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-5 text-sm leading-relaxed text-fg-muted">{t('analyze.drafts.running_note')}</p>
    </Card>
  );
}
