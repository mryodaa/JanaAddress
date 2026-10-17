import type { ReactNode } from "react";
import type { SessionInfo } from "../api/client";
import { useI18n } from "../i18n";
import { useCountUp } from "../lib/motion";
import { IconChevronRight } from "./icons";
import { ProgressBar } from "./ui";

function Num({ value, suffix = "" }: { value: number; suffix?: string }) {
  const v = useCountUp(value);
  return (
    <span className="tabular-nums">
      {Math.round(v)}
      {suffix}
    </span>
  );
}

function Tile({
  label,
  value,
  hint,
  onClick,
  accent,
  active,
  children,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  onClick?: () => void;
  accent?: "warn" | "brand";
  active?: boolean;
  children?: ReactNode;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          {accent && (
            <span className={`h-2 w-2 rounded-full ${accent === "warn" ? "bg-warn" : "bg-brand-600"}`} />
          )}
          {label}
        </span>
        {onClick && (
          <IconChevronRight className="h-4 w-4 text-ink-3 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-brand-600" />
        )}
      </div>
      <div className="mt-0.5 text-xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-ink-3">{hint}</div>}
      {children}
    </>
  );
  const base = "min-w-0 rounded-2xl border px-3.5 py-3 text-left";
  if (!onClick) return <div className={`${base} border-line-soft bg-canvas/60`}>{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      // кнопка по умолчанию центрирует содержимое по вертикали: колонкой от верха, как у соседних карточек
      className={`group flex flex-col justify-start ${base} transition duration-200 hover:-translate-y-0.5 hover:shadow-md hover:shadow-ink/5 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-600/20 ${
        active
          ? "border-brand-600 bg-brand-50"
          : "border-line-soft bg-canvas/60 hover:border-brand-200 hover:bg-white"
      }`}
    >
      {body}
    </button>
  );
}

export function Summary({
  s,
  filter,
  onUncertain,
}: {
  s: SessionInfo;
  filter: string;
  onUncertain: () => void;
}) {
  const { t } = useI18n();
  const sum = s.summary;
  const max = Math.max(1, ...sum.histogram);
  const th = sum.threshold;
  const done = s.status !== "processing";
  const progress = s.processed / Math.max(1, s.total);
  return (
    <section className="grid animate-fade-up gap-4 rounded-[20px] border border-line bg-white p-4 sm:p-5 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 md:grid-cols-2 xl:grid-cols-4">
        <Tile label={t("statRecords")} value={<Num value={s.total} />} hint={s.name ?? undefined} />
        <Tile
          label={t("statProcessed")}
          value={done ? <Num value={s.processed} /> : <Num value={Math.round(progress * 100)} suffix="%" />}
          hint={
            s.seconds != null ? t("secondsFmt", { s: s.seconds.toFixed(1) }) : t("parsingInProgressShort")
          }
        >
          {!done && <ProgressBar value={progress} className="mt-2 h-1.5" />}
        </Tile>
        <Tile
          label={t("statUncertain", { pct: Math.round(th * 100) })}
          value={<Num value={sum.uncertain} />}
          hint={`< ${Math.round(th * 100)}% · ${t("showLink")}`}
          accent="warn"
          onClick={onUncertain}
          active={filter === "uncertain"}
        />
        <Tile
          label={t("statConfident")}
          value={<Num value={sum.confident} />}
          hint={
            sum.mean_confidence != null
              ? `≥ ${Math.round(th * 100)}% · ${t("avgConfidence", { pct: Math.round(sum.mean_confidence * 100) })}`
              : `≥ ${Math.round(th * 100)}%`
          }
          accent="brand"
        >
          <ProgressBar value={sum.confident / Math.max(1, s.total)} className="mt-2 h-1" />
        </Tile>
      </div>
      <div className="min-w-0">
        <div className="mb-1 flex items-center justify-between text-xs text-ink-2">
          <span>{t("confidenceDist")}</span>
          <span className="hidden items-center gap-3 text-ink-3 sm:inline-flex">
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm bg-warn" />
              {"<"} {Math.round(th * 100)}%
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm bg-brand-600" />≥ {Math.round(th * 100)}%
            </span>
          </span>
        </div>
        <div className="relative">
          <div className="flex h-20 items-end gap-1" role="img" aria-label={t("confidenceHistogramAria")}>
            {sum.histogram.map((n, i) => {
              // порог может лежать внутри корзины (0.95 в [0.9, 1.0]): столбик делится на две части
              const below = sum.histogram_uncertain[i] ?? 0;
              const h = Math.max(3, (n / max) * 56);
              const warnShare = n ? below / n : (i + 1) / 10 <= th ? 1 : 0;
              return (
                <div
                  key={`b${i * 10}`}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-0.5"
                >
                  <span className="text-[10px] tabular-nums text-ink-3">{n || ""}</span>
                  <div
                    title={
                      below && below < n
                        ? `${i * 10}–${i * 10 + 10}%: ${n} (< ${Math.round(th * 100)}%: ${below})`
                        : `${i * 10}–${i * 10 + 10}%: ${n}`
                    }
                    className="stagger flex w-full origin-bottom animate-grow-up flex-col-reverse overflow-hidden rounded-t-md transition-[height] duration-500 ease-[var(--ease-out-soft)] hover:opacity-80"
                    style={{ height: `${h}px`, "--i": i } as React.CSSProperties}
                  >
                    <div className="bg-warn" style={{ height: `${warnShare * 100}%` }} />
                    <div className="flex-1 bg-brand-600" />
                  </div>
                </div>
              );
            })}
          </div>
          {/* метка порога: граница между жёлтыми и зелёными столбиками */}
          <div
            className="pointer-events-none absolute -top-1 bottom-0 animate-fade-in border-l border-dashed border-ink/40"
            style={{ left: `${th * 100}%` }}
          >
            <span className="absolute -top-3 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1 text-[9px] font-semibold text-white">
              {t("thresholdMark", { pct: Math.round(th * 100) })}
            </span>
          </div>
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-ink-3">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </section>
  );
}
