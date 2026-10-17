import { useState } from "react";
import type { FieldName, StepTrace } from "../api/client";
import { useI18n } from "../i18n";
import { type ConfModel, type ConfTerm, clampTo, logit, sigmoid } from "../lib/confidence";
import { type Dispute, asField, isRecord, parseArbiter, parseDisputes, parseLayout } from "../lib/trace";
import { DEMO_TEXTS, type DemoTexts, confPartLabel, fmt } from "./demo/texts";

const pct = (p: number) => Math.round(p * 100);
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;
// число со знаком минуса (−), а не дефисом, как у баллов
const num = (v: number) => `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
const quote = (xs: string[]) => xs.map((x) => `«${x}»`).join(", ");
const BINARY = new Set(["street_name", "house", "admin", "no_street_house"]);

type Values = Partial<Record<FieldName, string | null | undefined>>;

/** Что известно о записи из trace: для подписи «что именно произошло в этой строке» у каждого признака. */
interface Ctx {
  content: number | null;
  unparsed: string[];
  scores: Partial<Record<FieldName, number>>;
  extra: string[];
  agree: FieldName[];
  rulesOnly: FieldName[];
  modelOnly: FieldName[];
  disputes: Dispute[];
  layout: { from: string; to: string } | null;
  values: Values;
}

function buildCtx(trace: StepTrace[] | undefined, values: Values): Ctx {
  const step = (name: string) => trace?.find((s) => s.step === name);
  const ch = step("confidence")?.changes;
  const c = isRecord(ch) ? ch : {};
  const strings = (v: unknown) =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const scores: Partial<Record<FieldName, number>> = {};
  if (isRecord(c.scores))
    for (const [k, v] of Object.entries(c.scores)) {
      const f = asField(k);
      if (f && typeof v === "number") scores[f] = v;
    }
  const arbNotes = step("arbiter")?.notes ?? [];
  const groups = parseArbiter(arbNotes);
  return {
    content: typeof c.content === "number" ? c.content : null,
    unparsed: strings(c.unparsed),
    scores,
    extra: strings(c.extra),
    agree: groups?.agree ?? [],
    rulesOnly: groups?.rulesOnly ?? [],
    modelOnly: groups?.modelOnly ?? [],
    disputes: parseDisputes(arbNotes),
    layout: parseLayout(step("layout")?.notes ?? []),
    values,
  };
}

/** Строки про эту запись для признака: какие поля разошлись, какая улица в справочнике, какие слова лишние. */
function termContext(
  t: ConfTerm,
  ctx: Ctx,
  cx: DemoTexts["cx"],
  labels: Record<FieldName, string>,
): string[] {
  const v = ctx.values;
  const names = (fs: FieldName[]) => fs.map((f) => labels[f]).join(", ");
  const city = v.city ? fmt(cx.ctxInCity, { city: v.city }) : "";
  switch (t.key) {
    case "consumed":
      return ctx.content
        ? [fmt(cx.ctxConsumed, { n: ctx.content - ctx.unparsed.length, m: ctx.content })]
        : [];
    case "unparsed":
      return ctx.unparsed.length ? [fmt(cx.ctxUnparsed, { list: quote(ctx.unparsed) })] : [];
    case "street_name":
      return v.street_name ? [fmt(cx.ctxStreet, { v: v.street_name })] : [];
    case "house":
      return v.house ? [fmt(cx.ctxHouse, { v: v.house })] : [];
    case "admin":
      return v.city
        ? [fmt(cx.ctxCity, { v: v.city })]
        : v.province
          ? [fmt(cx.ctxProvince, { v: v.province })]
          : [];
    case "min_score": {
      const weakest = (Object.entries(ctx.scores) as [FieldName, number][]).sort((a, b) => a[1] - b[1])[0];
      if (!weakest) return [];
      const [f, s] = weakest;
      if (s >= 0.99) return [cx.ctxAllStrong];
      const reason = s >= 0.99 ? cx.rMarker : s >= 0.85 ? cx.rStrong : s >= 0.6 ? cx.rWeak : cx.rGuess;
      return [fmt(cx.ctxWeakest, { field: labels[f], score: s.toFixed(2), reason })];
    }
    case "flag:model_disagree":
    case "flag:model_override": {
      const ds =
        t.key === "flag:model_override" ? ctx.disputes.filter((d) => d.winner === "model") : ctx.disputes;
      const lines = ds.map((d) =>
        fmt(cx.ctxDispute, {
          field: labels[d.field],
          rules: d.rules || "—",
          model: d.model || "—",
          winner: d.winner === "model" ? cx.winnerModel : cx.winnerRules,
        }),
      );
      if (t.key === "flag:model_disagree") {
        if (ctx.rulesOnly.length) lines.push(fmt(cx.ctxRulesOnly, { list: names(ctx.rulesOnly) }));
        if (ctx.modelOnly.length) lines.push(fmt(cx.ctxModelOnly, { list: names(ctx.modelOnly) }));
      }
      return lines;
    }
    case "flag:model_agree_all":
      return ctx.agree.length ? [fmt(cx.ctxAgree, { list: names(ctx.agree) })] : [];
    case "flag:street_in_reference":
      return v.street_name ? [fmt(cx.ctxStreetRef, { street: v.street_name, city })] : [];
    case "flag:street_not_in_reference":
      return v.street_name ? [fmt(cx.ctxStreetNoRef, { street: v.street_name, city })] : [];
    case "flag:house_in_reference":
      return v.house && v.street_name ? [fmt(cx.ctxHouseRef, { house: v.house, street: v.street_name })] : [];
    case "flag:extra_numbers":
      return ctx.extra.length ? [fmt(cx.ctxExtra, { list: quote(ctx.extra) })] : [];
    case "flag:guessed_street":
      return v.street_name ? [fmt(cx.ctxGuessed, { street: v.street_name })] : [];
    case "flag:layout_fixed":
      return ctx.layout ? [fmt(cx.ctxLayout, ctx.layout)] : [];
    default:
      return [];
  }
}

/** Значение признака, когда оно не просто «есть»: доля, число слов, надёжность. */
function termValue(t: ConfTerm, cx: DemoTexts["cx"]): string | null {
  if (t.key === "consumed") return fmt(cx.share, { v: Math.round(t.x * 100) });
  if (t.key === "unparsed") return fmt(cx.words, { v: t.x });
  if (t.key === "min_score") return t.x.toFixed(2);
  return null;
}

interface Row {
  key: string;
  label: string;
  value: string | null;
  context: string[];
  why: string;
  points: number;
  term: ConfTerm | null;
}

/**
 * Почему у записи такая уверенность. Модель логистическая: баллы признаков (вес × значение) складываются с базой,
 * сумма переводится в вероятность. У каждого признака строка про эту запись (какие поля разошлись, какая улица
 * найдена в справочнике), а по клику: откуда число (формула, во сколько раз меняет шансы, насколько сдвинул
 * итог, как подобран вес). dense: компактно, для шагов разбора в редакторе.
 */
export function ConfidenceExplain({
  model,
  threshold,
  trace,
  values = {},
  dense = false,
}: {
  model: ConfModel;
  threshold: number;
  /** trace записи: из него подписи «что произошло в этой строке» */
  trace?: StepTrace[];
  /** итоговые значения полей записи (улица, дом, город) для подписей */
  values?: Values;
  dense?: boolean;
}) {
  const { language, fieldLabels } = useI18n();
  const tx = DEMO_TEXTS[language];
  const cx = tx.cx;
  const ctx = buildCtx(trace, values);
  const [open, setOpen] = useState<string | null>(null);
  const terms = [...model.terms].sort((a, b) => Math.abs(b.points) - Math.abs(a.points));
  const rows: Row[] = [
    {
      key: "base",
      label: cx.base,
      value: null,
      context: [],
      why: cx.baseWhy,
      points: model.intercept,
      term: null,
    },
    ...terms.map((t) => ({
      key: t.key,
      label: confPartLabel(tx.confParts, t.key),
      value: termValue(t, cx),
      context: termContext(t, ctx, cx, fieldLabels),
      why: cx.why[t.key] ?? (t.key.startsWith("flag:") ? cx.flagWhy : ""),
      points: t.points,
      term: t,
    })),
  ];
  const maxAbs = Math.max(0.5, ...rows.map((r) => Math.abs(r.points)));
  const above = model.p >= threshold;
  const gap = logit(threshold) - model.logit;
  const worst = terms.filter((t) => t.points < 0).sort((a, b) => a.points - b.points)[0];
  const best = terms.filter((t) => t.points > 0).sort((a, b) => b.points - a.points)[0];
  const capped = Math.abs(model.raw - model.p) > 0.0005;
  const without = (points: number) => clampTo(sigmoid(model.logit - points), model.bounds);

  return (
    <div className={`grid min-w-0 ${dense ? "gap-3 text-xs" : "gap-4 text-sm"}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={`font-semibold tabular-nums text-ink ${dense ? "text-lg" : "text-2xl"}`}>
          {pct(model.p)}%
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
            above ? "bg-brand-50 text-brand-800 ring-brand-200" : "bg-warn-50 text-warn-800 ring-warn/40"
          }`}
        >
          {fmt(above ? cx.above : cx.below, { th: pct(threshold) })}
        </span>
      </div>
      <div className="grid gap-1 leading-relaxed text-ink-2">
        {!dense && <p>{cx.how}</p>}
        <p className={dense ? "text-ink-3" : "text-xs text-ink-3"}>{cx.pointHint}</p>
      </div>

      {/* слагаемые: база и признаки по силе влияния; клик раскрывает, откуда число */}
      <div className="grid gap-1">
        {rows.map((r) => {
          const isOpen = open === r.key;
          const effect = r.term ? model.p - without(r.points) : 0;
          return (
            <div key={r.key} className={`rounded-lg ${r.key === "base" ? "bg-canvas/60" : "bg-canvas"}`}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : r.key)}
                className={`grid w-full grid-cols-[minmax(0,1fr)_minmax(56px,26%)_52px] items-center gap-3 rounded-lg text-left transition-colors hover:bg-line-soft/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30 ${
                  dense ? "px-2 py-1.5" : "px-3 py-2"
                }`}
              >
                <span className="min-w-0">
                  <span className="flex items-baseline gap-1.5 text-ink">
                    <svg
                      viewBox="0 0 12 12"
                      className={`h-2.5 w-2.5 shrink-0 text-ink-3 transition-transform ${isOpen ? "rotate-90" : ""}`}
                      fill="currentColor"
                      aria-hidden="true"
                    >
                      <path d="M4 2.5 8.5 6 4 9.5z" />
                    </svg>
                    <span className="min-w-0">
                      {r.label}
                      {r.value && <span className="ml-1.5 text-xs tabular-nums text-ink-3">· {r.value}</span>}
                    </span>
                  </span>
                  {/* про эту запись, если есть; иначе общий смысл признака */}
                  {(r.context.length ? r.context : r.why ? [r.why] : []).map((line) => (
                    <span
                      key={line}
                      className={`mt-0.5 block pl-4 text-xs ${r.context.length ? "text-ink-2" : "text-ink-3"}`}
                    >
                      {line}
                    </span>
                  ))}
                </span>
                <span className="relative h-2 rounded-full bg-line-soft" aria-hidden="true">
                  <span
                    className={`absolute inset-y-0 rounded-full ${r.points >= 0 ? "left-1/2 bg-brand-600" : "right-1/2 bg-danger"}`}
                    style={{ width: `${(Math.abs(r.points) / maxAbs) * 50}%` }}
                  />
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-ink/25" />
                </span>
                <span
                  className={`text-right font-mono text-xs font-semibold tabular-nums ${r.points >= 0 ? "text-brand-700" : "text-danger"}`}
                >
                  {signed(r.points)}
                </span>
              </button>
              {isOpen && (
                <div
                  className={`grid animate-fade-in gap-1.5 border-t border-line-soft text-xs leading-relaxed text-ink-2 ${dense ? "px-2 py-2" : "px-3 py-2.5 pl-7"}`}
                >
                  {r.context.length > 0 && r.why && <p>{r.why}</p>}
                  {r.term ? (
                    <>
                      <p className="font-mono text-ink">
                        {fmt(cx.formula, {
                          w: num(r.term.w),
                          x:
                            r.term.x === 1 && (r.key.startsWith("flag:") || BINARY.has(r.key))
                              ? cx.present
                              : fmt(cx.valueOf, { x: r.term.x }),
                          pts: signed(r.points),
                        })}
                      </p>
                      <p>{fmt(r.points >= 0 ? cx.oddsUp : cx.oddsDown, { k: odds(r.points) })}</p>
                      <p>
                        {Math.abs(effect) < 0.005
                          ? fmt(cx.effectNone, {
                              why: capped ? fmt(cx.whyCap, { hi: pct(model.bounds[1]) }) : cx.whyEdge,
                            })
                          : fmt(cx.effect, {
                              pp: `${effect >= 0 ? "+" : "−"}${Math.abs(Math.round(effect * 100))}`,
                              pct: pct(without(r.points)),
                            })}
                      </p>
                      <p className="text-ink-3">{cx.origin}</p>
                    </>
                  ) : (
                    <p>{cx.baseOrigin}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <div
          className={`mt-1 flex items-center justify-between gap-3 border-t border-line pt-2 font-semibold ${dense ? "px-2" : "px-3"}`}
        >
          <span>{cx.sum}</span>
          <span className="font-mono tabular-nums">
            {model.logit.toFixed(2)} → {pct(model.p)}%
          </span>
        </div>
      </div>

      <div className={`grid items-center gap-4 ${dense ? "" : "sm:grid-cols-[240px_minmax(0,1fr)]"}`}>
        <SigmoidCurve
          z={model.logit}
          p={model.p}
          threshold={threshold}
          bounds={model.bounds}
          label={cx.curveAria}
        />
        <ul className="grid gap-1.5 text-ink-2">
          <li className="font-medium text-ink">
            {gap > 0
              ? fmt(cx.toThreshold, { pts: gap.toFixed(2) })
              : fmt(cx.margin, { pts: Math.abs(gap).toFixed(2) })}
          </li>
          {worst && (
            <li>
              {fmt(cx.worst, {
                label: confPartLabel(tx.confParts, worst.key),
                pts: signed(worst.points),
                pct: pct(without(worst.points)),
              })}
            </li>
          )}
          {best && (
            <li>
              {fmt(cx.best, { label: confPartLabel(tx.confParts, best.key), pts: best.points.toFixed(2) })}
            </li>
          )}
          {capped && (
            <li className="text-ink-3">
              {fmt(cx.cap, { lo: pct(model.bounds[0]), hi: pct(model.bounds[1]) })}
            </li>
          )}
        </ul>
      </div>
      {!dense && <p className="text-xs leading-relaxed text-ink-3">{fmt(cx.read, { pct: pct(model.p) })}</p>}
    </div>
  );
}

/** Во сколько раз балл меняет шансы: e^|баллы|, коротко. */
function odds(points: number): string {
  const k = Math.exp(Math.abs(points));
  return k >= 10 ? String(Math.round(k)) : k.toFixed(1);
}

const Z_MIN = -4;
const Z_MAX = 7;
const W = 240;
const H = 96;
const PAD = 6;

/** Кривая перевода баллов в проценты: где на ней запись и где порог. */
function SigmoidCurve({
  z,
  p,
  threshold,
  bounds,
  label,
}: {
  z: number;
  p: number;
  threshold: number;
  bounds: [number, number];
  label: string;
}) {
  const { language } = useI18n();
  const cx = DEMO_TEXTS[language].cx;
  const sx = (v: number) =>
    PAD + ((Math.min(Z_MAX, Math.max(Z_MIN, v)) - Z_MIN) / (Z_MAX - Z_MIN)) * (W - 2 * PAD);
  const sy = (q: number) => H - PAD - q * (H - 2 * PAD);
  const pts: string[] = [];
  for (let i = 0; i <= 60; i++) {
    const v = Z_MIN + ((Z_MAX - Z_MIN) * i) / 60;
    pts.push(`${sx(v).toFixed(1)},${sy(clampTo(sigmoid(v), bounds)).toFixed(1)}`);
  }
  const above = p >= threshold;
  const zth = logit(threshold);
  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-24 w-full max-w-[240px]"
        role="img"
        aria-label={fmt(label, { z: z.toFixed(2), pct: pct(p), th: pct(threshold) })}
      >
        <line x1={PAD} x2={W - PAD} y1={sy(0)} y2={sy(0)} className="stroke-line" strokeWidth="1" />
        <line x1={PAD} x2={W - PAD} y1={sy(1)} y2={sy(1)} className="stroke-line-soft" strokeWidth="1" />
        {/* порог: уровень вероятности и сколько баллов ему соответствует */}
        <line
          x1={PAD}
          x2={W - PAD}
          y1={sy(threshold)}
          y2={sy(threshold)}
          className="stroke-warn"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
        <line
          x1={sx(zth)}
          x2={sx(zth)}
          y1={sy(0)}
          y2={sy(threshold)}
          className="stroke-warn/60"
          strokeWidth="1"
        />
        <text x={PAD + 2} y={sy(threshold) - 3} className="fill-warn-800 text-[9px]">
          {pct(threshold)}%
        </text>
        <text x={PAD + 2} y={sy(0) - 3} className="fill-ink-3 text-[9px]">
          0%
        </text>
        <polyline
          points={pts.join(" ")}
          fill="none"
          className="stroke-ink-3"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <line x1={sx(z)} x2={sx(z)} y1={sy(0)} y2={sy(p)} className="stroke-ink/30" strokeWidth="1" />
        <circle
          cx={sx(z)}
          cy={sy(p)}
          r="5"
          className={above ? "fill-brand-600 stroke-white" : "fill-warn stroke-white"}
          strokeWidth="2"
        />
      </svg>
      <figcaption className="mt-0.5 text-[11px] text-ink-3">{cx.curve}</figcaption>
    </figure>
  );
}
