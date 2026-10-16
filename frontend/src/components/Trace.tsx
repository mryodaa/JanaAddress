import type { StepTrace } from "../api/client";
import { useI18n } from "../i18n";

function fmt(v: unknown): string {
  if (v && typeof v === "object" && "value" in v) {
    const o = v as { value: unknown; source?: string };
    return `${JSON.stringify(o.value)}${o.source && o.source !== "string" ? ` ← ${o.source}` : ""}`;
  }
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function Trace({ trace }: { trace: StepTrace[] }) {
  const { t: tr, stepLabels } = useI18n();

  return (
    <ol className="space-y-2">
      {trace.map((t) => {
        const changes = Object.entries(t.changes ?? {}).filter(([k]) => k !== "parts" && k !== "unparsed");
        const parts = (t.changes as { parts?: Record<string, number> } | undefined)?.parts;
        return (
          <li key={t.step} className="rounded-lg border border-slate-200 bg-white p-2.5">
            <div className="flex items-center justify-between text-sm">
              <span className="font-semibold text-slate-800">{stepLabels[t.step] ?? t.step}</span>
              <span className="font-mono text-[11px] text-slate-400">
                {t.ms.toFixed(2)} {tr("msUnit")}
              </span>
            </div>
            {changes.length > 0 && (
              <ul className="mt-1 space-y-0.5 font-mono text-xs text-slate-700">
                {changes.map(([k, v]) => (
                  <li key={k}>
                    <span className="text-brand-700">{k}</span> = {fmt(v)}
                  </li>
                ))}
              </ul>
            )}
            {parts && (
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.entries(parts).map(([k, v]) => (
                  <span
                    key={k}
                    className={`rounded px-1.5 py-px font-mono text-[11px] ${v >= 0 ? "bg-brand-50 text-brand-800" : "bg-rose-50 text-rose-700"}`}
                  >
                    {k} {v >= 0 ? "+" : ""}
                    {v}
                  </span>
                ))}
              </div>
            )}
            {(t.notes ?? []).length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                {(t.notes ?? []).map((n) => (
                  <li key={n} className="break-words">
                    {n}
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}
