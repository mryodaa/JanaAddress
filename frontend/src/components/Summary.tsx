import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  bucket,
  onBucket,
}: {
  s: SessionInfo;
  filter: string;
  onUncertain: () => void;
  /** выбранный столбец гистограммы (0..9) или null */
  bucket: number | null;
  onBucket: (b: number) => void;
}) {
  const { t } = useI18n();
  const sum = s.summary;
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
          value={<Num value={sum.to_review} />}
          hint={
            (sum.skipped ?? 0) > 0
              ? `${t("skippedCount", { n: sum.skipped ?? 0 })} · ${t("showLink")}`
              : `< ${Math.round(th * 100)}% · ${t("showLink")}`
          }
          accent="warn"
          onClick={onUncertain}
          active={filter === "uncertain"}
        >
          {/* прогресс проверки: сколько изначально неуверенных оператор уже прошёл */}
          {(sum.review_total ?? 0) > 0 && (
            <div className="mt-2">
              <ProgressBar
                value={(sum.review_done ?? 0) / Math.max(1, sum.review_total ?? 0)}
                className="h-1"
              />
              <div className="mt-1 truncate text-[11px] tabular-nums text-ink-3">
                {t("reviewProgress", { done: sum.review_done ?? 0, total: sum.review_total ?? 0 })}
              </div>
            </div>
          )}
        </Tile>
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
      <ConfidenceHistogram
        histogram={sum.histogram}
        below={sum.histogram_uncertain}
        threshold={th}
        total={Math.max(1, s.processed)}
        selected={bucket}
        onSelect={onBucket}
        disabled={!done}
      />
    </section>
  );
}

const TIP_W = 240;

/** Подсказка по центру столбца, в пределах окна; сверху, если над столбцом есть место. */
function tipStyle(r: DOMRect): React.CSSProperties {
  const left = Math.min(Math.max(8, r.left + r.width / 2 - TIP_W / 2), window.innerWidth - TIP_W - 8);
  const above = r.top > 150;
  return {
    left,
    width: TIP_W,
    top: above ? r.top - 8 : r.bottom + 8,
    transform: above ? "translateY(-100%)" : undefined,
  };
}

export function bucketRange(b: number): string {
  return `${b * 10}–${b * 10 + 10}%`;
}

/**
 * Распределение уверенности: столбец на каждые 10%, часть ниже порога жёлтая. Наведение или фокус показывает
 * подсказку, клик (Enter) фильтрует таблицу по столбцу, повторный клик снимает фильтр. Стрелки ходят по столбцам.
 */
function ConfidenceHistogram({
  histogram,
  below,
  threshold,
  total,
  selected,
  onSelect,
  disabled,
}: {
  histogram: number[];
  below: number[];
  threshold: number;
  total: number;
  selected: number | null;
  onSelect: (b: number) => void;
  disabled: boolean;
}) {
  const { t } = useI18n();
  // столбец под указателем или фокусом и его место на экране (подсказка рисуется в портале от него)
  const [tipAt, setTipAt] = useState<{ i: number; rect: DOMRect } | null>(null);
  const hover = tipAt?.i ?? null;
  const show = (i: number, el: HTMLElement) => setTipAt({ i, rect: el.getBoundingClientRect() });
  const hide = (i: number) => setTipAt((v) => (v?.i === i ? null : v));
  // прокрутка и смена размера уводят столбец из-под подсказки
  useEffect(() => {
    if (!tipAt) return;
    const off = () => setTipAt(null);
    window.addEventListener("scroll", off, true);
    window.addEventListener("resize", off);
    return () => {
      window.removeEventListener("scroll", off, true);
      window.removeEventListener("resize", off);
    };
  }, [tipAt]);
  const box = useRef<HTMLDivElement>(null);
  const max = Math.max(1, ...histogram);
  const thPct = Math.round(threshold * 100);
  // столбец в порядке Tab: выбранный, иначе первый непустой (остальные стрелками)
  const tabStop =
    selected ??
    Math.max(
      0,
      histogram.findIndex((n) => n > 0),
    );

  const focusBar = (i: number) => box.current?.querySelector<HTMLButtonElement>(`[data-bar="${i}"]`)?.focus();
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (e.key === "Home") focusBar(0);
    else if (e.key === "End") focusBar(histogram.length - 1);
    else if (step) focusBar(Math.min(histogram.length - 1, Math.max(0, i + step)));
    else return;
    e.preventDefault();
  };

  const tip = hover != null ? { n: histogram[hover] ?? 0, below: below[hover] ?? 0 } : null;
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between text-xs text-ink-2">
        <span>{t("confidenceDist")}</span>
        <span className="hidden items-center gap-3 text-ink-3 sm:inline-flex">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-warn" />
            {"<"} {thPct}%
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-brand-600" />≥ {thPct}%
          </span>
        </span>
      </div>
      <div className="relative">
        <div
          ref={box}
          // biome-ignore lint/a11y/useSemanticElements: группа кнопок-столбцов, <fieldset> здесь не форма
          role="group"
          aria-label={t("confidenceHistogramAria")}
          className="flex h-20 items-end gap-0.5"
        >
          {histogram.map((n, i) => {
            // порог может лежать внутри корзины (0.95 в [0.9, 1.0]): столбик делится на две части
            const b = below[i] ?? 0;
            const h = Math.max(3, (n / max) * 56);
            const warnShare = n ? b / n : (i + 1) / 10 <= threshold ? 1 : 0;
            const isSel = selected === i;
            const dim = selected != null && !isSel;
            const empty = n === 0;
            return (
              <button
                key={`b${i * 10}`}
                type="button"
                data-bar={i}
                tabIndex={i === tabStop ? 0 : -1}
                aria-pressed={isSel}
                aria-disabled={empty || disabled || undefined}
                aria-label={t("histBarAria", { range: bucketRange(i), n, below: b })}
                onClick={() => {
                  if (!empty && !disabled) onSelect(i);
                }}
                onKeyDown={(e) => onKeyDown(e, i)}
                onPointerEnter={(e) => show(i, e.currentTarget)}
                onPointerLeave={() => hide(i)}
                onFocus={(e) => show(i, e.currentTarget)}
                onBlur={() => hide(i)}
                // вся высота колонки кликабельна: в маленький столбик не нужно целиться
                className={`group flex h-full flex-1 flex-col items-center justify-end gap-0.5 rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand-600/40 ${
                  empty || disabled ? "cursor-default" : "cursor-pointer hover:bg-canvas"
                } ${isSel ? "bg-brand-50" : ""}`}
              >
                <span
                  className={`text-[10px] tabular-nums transition-colors ${isSel ? "font-semibold text-ink" : "text-ink-3"}`}
                >
                  {n || ""}
                </span>
                <span
                  className={`stagger flex w-full origin-bottom animate-grow-up flex-col-reverse overflow-hidden rounded-t transition-[height,opacity,filter] duration-300 ease-[var(--ease-out-soft)] ${
                    dim ? "opacity-35" : "opacity-100"
                  } ${empty ? "" : "group-hover:brightness-110"} ${isSel ? "ring-2 ring-inset ring-ink/70" : ""}`}
                  style={{ height: `${h}px`, "--i": i } as React.CSSProperties}
                >
                  <span className="bg-warn" style={{ height: `${warnShare * 100}%` }} />
                  <span className="flex-1 bg-brand-600" />
                </span>
              </button>
            );
          })}
        </div>
        {/* метка порога: граница между жёлтыми и зелёными столбиками */}
        <div
          className="pointer-events-none absolute -top-1 bottom-0 animate-fade-in border-l border-dashed border-ink/40"
          style={{ left: `${threshold * 100}%` }}
        >
          <span className="absolute -top-3 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1 text-[9px] font-semibold text-white">
            {t("thresholdMark", { pct: thPct })}
          </span>
        </div>
        {tipAt &&
          tip &&
          createPortal(
            <div
              role="tooltip"
              // в портале с fixed: карточка сводки (анимация появления) держит свой контекст наложения, внутри
              // неё подсказка уходила под кнопки панели ниже; над столбцом, а у верхнего края экрана под ним
              className="pointer-events-none fixed z-50 animate-fade-in rounded-xl bg-white px-3 py-2 text-xs shadow-lg shadow-ink/10 ring-1 ring-line"
              style={tipStyle(tipAt.rect)}
            >
              <div className="text-sm font-semibold tabular-nums text-ink">
                {t("histRecords", { n: tip.n })}
              </div>
              <div className="mt-0.5 text-ink-2 tabular-nums">
                {bucketRange(tipAt.i)} · {t("histShare", { pct: Math.round((tip.n / total) * 100) })}
              </div>
              {tip.below > 0 && (
                <div className="mt-0.5 flex items-center gap-1.5 tabular-nums text-ink-2">
                  <span className="h-0.5 w-3 rounded-full bg-warn" />
                  {t("histBelow", { th: thPct, n: tip.below })}
                </div>
              )}
              {tip.n > 0 && !disabled && (
                <div className="mt-1 border-t border-line-soft pt-1 text-ink-3">
                  {selected === tipAt.i ? t("histClickReset") : t("histClickShow")}
                </div>
              )}
            </div>,
            document.body,
          )}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-3">
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
      <div className="mt-1 text-[11px] text-ink-3">{t("histHint")}</div>
    </div>
  );
}
