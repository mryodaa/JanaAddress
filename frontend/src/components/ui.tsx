import type { ReactNode } from "react";
import type { FieldExplain, FieldName } from "../api/client";
import { FIELD_COLORS, FIELD_LABELS, highlight, sourceLabel, visible } from "../lib/fields";

export function ConfidenceBadge({ value, threshold }: { value: number; threshold: number }) {
  const pct = Math.round(value * 100);
  const tone =
    value >= Math.max(threshold, 0.8)
      ? "bg-brand-100 text-brand-800"
      : value >= threshold
        ? "bg-lime-100 text-lime-800"
        : value >= threshold / 2
          ? "bg-amber-100 text-amber-800"
          : "bg-rose-100 text-rose-800";
  return (
    <span
      className={`inline-flex min-w-11 justify-center rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${tone}`}
    >
      {pct}%
    </span>
  );
}

export function Highlighted({ raw, fields }: { raw: string; fields: Partial<Record<string, FieldExplain>> }) {
  return (
    <span className="whitespace-pre-wrap break-words">
      {highlight(raw, fields).map((p, i) =>
        p.field ? (
          <mark
            // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
            key={i}
            title={FIELD_LABELS[p.field]}
            className={`rounded px-0.5 ring-1 ring-inset ${FIELD_COLORS[p.field].mark}`}
          >
            {visible(p.text)}
          </mark>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
          <span key={i} className="text-slate-500">
            {visible(p.text)}
          </span>
        ),
      )}
    </span>
  );
}

export function Legend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600">
      {(Object.keys(FIELD_LABELS) as FieldName[]).map((f) => (
        <span key={f} className="inline-flex items-center gap-1">
          <span className={`h-2.5 w-2.5 rounded-sm ${FIELD_COLORS[f].dot}`} />
          {FIELD_LABELS[f]}
        </span>
      ))}
    </div>
  );
}

export function SourceTag({ source }: { source: string | null | undefined }) {
  const label = sourceLabel(source);
  if (!label) return null;
  const manual = source === "manual";
  return (
    <span
      className={`ml-1 rounded px-1 py-px text-[10px] font-medium uppercase tracking-wide ${
        manual ? "bg-slate-800 text-white" : "bg-sky-100 text-sky-800"
      }`}
      title={manual ? "исправлено оператором" : "восстановлено по справочнику, в строке этого нет"}
    >
      {manual ? "правка" : "справ."}
    </span>
  );
}

export function Card({
  title,
  children,
  className = "",
}: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold text-slate-700">{title}</h2>}
      {children}
    </section>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
      {children}
    </kbd>
  );
}

export function Button({
  children,
  variant = "secondary",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const cls = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-200",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${cls} ${rest.className ?? ""}`}
    >
      {children}
    </button>
  );
}
