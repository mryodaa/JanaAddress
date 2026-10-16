import type { SessionInfo } from "../api/client";
import { Card } from "./ui";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

export function Summary({ s, onUncertain }: { s: SessionInfo; onUncertain: () => void }) {
  const sum = s.summary;
  const max = Math.max(1, ...sum.histogram);
  const th = sum.threshold;
  const done = s.status !== "processing";
  return (
    <Card className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 md:grid-cols-2 xl:grid-cols-4">
        <Stat label="Записей" value={s.total} hint={s.name ?? undefined} />
        <Stat
          label="Обработано"
          value={done ? s.processed : `${Math.round((s.processed / Math.max(1, s.total)) * 100)}%`}
          hint={s.seconds != null ? `${s.seconds.toFixed(1)} с` : "идёт разбор…"}
        />
        <button type="button" onClick={onUncertain} className="text-left hover:opacity-80">
          <Stat label={`Неуверенных (< ${Math.round(th * 100)}%)`} value={sum.uncertain} hint="показать →" />
        </button>
        <Stat
          label="Проверено"
          value={sum.reviewed}
          hint={
            sum.mean_confidence != null
              ? `ср. уверенность ${Math.round(sum.mean_confidence * 100)}%`
              : undefined
          }
        />
        {!done && (
          <div className="col-span-full h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full bg-brand-500 transition-all"
              style={{ width: `${(s.processed / Math.max(1, s.total)) * 100}%` }}
            />
          </div>
        )}
      </div>
      <div>
        <div className="mb-1 text-xs text-slate-500">Распределение confidence</div>
        <div className="flex h-20 items-end gap-1" role="img" aria-label="гистограмма уверенности">
          {sum.histogram.map((n, i) => (
            <div key={`b${i * 10}`} className="flex flex-1 flex-col items-center gap-0.5">
              <span className="text-[10px] tabular-nums text-slate-400">{n || ""}</span>
              <div
                title={`${i * 10}–${i * 10 + 10}%: ${n}`}
                className={`w-full rounded-t ${(i + 1) / 10 <= th ? "bg-amber-400" : "bg-brand-500"}`}
                style={{ height: `${Math.max(2, (n / max) * 56)}px` }}
              />
            </div>
          ))}
        </div>
        <div className="mt-0.5 flex justify-between text-[10px] text-slate-400">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </Card>
  );
}
