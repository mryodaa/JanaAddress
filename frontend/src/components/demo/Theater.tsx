import type { ReactNode } from "react";
import { FIELD_NAMES, type FieldName } from "../../api/client";
import { useI18n } from "../../i18n";
import { FIELD_COLORS, visible } from "../../lib/fields";
import { IconCheck } from "../icons";
import { Hint } from "../ui";
import type { Derived } from "./derive";
import { type DemoTexts, type StageId, fmt } from "./texts";

export interface HealthInfo {
  counts?: Record<string, number>;
  houses?: number;
  f1?: number;
  version?: string;
}

// подписи спанов модели, которые не являются полями ответа
const EXTRA_LABEL_CLS: Record<string, string> = {
  KEPT: "bg-brand-50 text-brand-800 ring-brand-200",
  KZ_DUP: "bg-line text-ink-2 ring-line",
  NOISE: "bg-line-soft text-ink-3 ring-line line-through",
};

function markCls(f: FieldName | null, label?: string): string {
  if (f) return FIELD_COLORS[f].mark;
  return EXTRA_LABEL_CLS[label ?? ""] ?? "bg-line-soft text-ink ring-line";
}

/** Строка с подсветкой произвольных диапазонов. */
function Line({
  raw,
  marks,
  dim = [],
  strike = [],
  className = "",
}: {
  raw: string;
  marks: { start: number; end: number; field: FieldName | null; label?: string; fresh?: boolean }[];
  dim?: [number, number][];
  strike?: [number, number][];
  className?: string;
}) {
  const owner = Array.from({ length: raw.length }, () => -1);
  marks.forEach((m, mi) => {
    for (let i = m.start; i < m.end && i < raw.length; i++) owner[i] = mi;
  });
  const inRange = (i: number, rs: [number, number][]) => rs.some(([a, b]) => i >= a && i < b);
  const pieces: { text: string; mi: number; dim: boolean; strike: boolean }[] = [];
  for (let i = 0; i < raw.length; i++) {
    const mi = owner[i] ?? -1;
    const d = inRange(i, dim);
    const s = inRange(i, strike);
    const last = pieces[pieces.length - 1];
    if (last && last.mi === mi && last.dim === d && last.strike === s) last.text += raw[i];
    else pieces.push({ text: raw[i] ?? "", mi, dim: d, strike: s });
  }
  return (
    <div className={`whitespace-pre-wrap break-words text-xl leading-relaxed sm:text-2xl ${className}`}>
      {pieces.map((p, i) => {
        const m = p.mi >= 0 ? marks[p.mi] : undefined;
        const base = `${p.dim ? "opacity-30" : ""} ${p.strike ? "line-through decoration-danger decoration-2" : ""} transition-opacity duration-500`;
        return m ? (
          <mark
            // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
            key={i}
            className={`rounded-md px-0.5 ring-1 ring-inset ${markCls(m.field, m.label)} ${m.fresh ? "animate-scale-in" : ""} ${base}`}
          >
            {visible(p.text)}
          </mark>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
          <span key={i} className={`text-ink-2 ${base}`}>
            {visible(p.text)}
          </span>
        );
      })}
    </div>
  );
}

function Caption({ children }: { children: ReactNode }) {
  return <div className="mt-4 min-h-6 animate-fade-up text-sm text-ink-2">{children}</div>;
}

function findSpan(raw: string, part: string): [number, number] | null {
  if (!part) return null;
  const i = raw.indexOf(part);
  return i >= 0 ? [i, i + part.length] : null;
}

function CleanStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  if (d.layout) {
    return (
      <div>
        <div
          className={`font-mono text-xl text-ink transition-opacity duration-500 ${tick >= 1 ? "opacity-40" : ""}`}
        >
          {d.layout.from}
        </div>
        {tick >= 1 && (
          <div className="my-3 inline-flex animate-fade-up items-center gap-2 rounded-full bg-warn-50 px-3 py-1 text-xs font-semibold text-warn-800">
            ⌨ {tx.layoutFixed}
          </div>
        )}
        {tick >= 2 && <div className="animate-fade-up font-mono text-2xl text-ink">{d.layout.to}</div>}
      </div>
    );
  }
  const chars = [...d.raw];
  return (
    <div>
      <div className="whitespace-pre-wrap break-all font-mono text-xl leading-loose text-ink sm:text-2xl">
        {chars.map((c, i) =>
          d.removed.has(i) ? (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: символы строки не переставляются
              key={i}
              className={`mx-px inline-block rounded bg-danger px-1 text-center text-sm text-white align-middle transition-all duration-500 ${
                tick >= 1 ? "w-0 scale-0 px-0 opacity-0" : "min-w-4"
              }`}
            >
              {c.trim() ? visible(c) : "␣"}
            </span>
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: символы строки не переставляются
            <span key={i}>{c}</span>
          ),
        )}
      </div>
      {tick >= 2 && d.removed.size > 0 && d.cleaned && (
        <div className="mt-4 animate-fade-up font-mono text-xl text-brand-800 sm:text-2xl">→ {d.cleaned}</div>
      )}
      {tick >= 1 && (
        <Caption>
          {d.removed.size ? (
            <span className="inline-flex items-center gap-2">
              <span className="rounded-full bg-danger-50 px-2 py-0.5 text-xs font-semibold text-danger">
                {fmt(tx.cleanRemoved, { n: d.removed.size })}
              </span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-2 text-brand-700">
              <IconCheck className="h-4 w-4" /> {tx.cleanNothing}
            </span>
          )}
        </Caption>
      )}
    </div>
  );
}

const KIND_CLS: Record<string, string> = {
  w: "bg-line-soft text-ink ring-line",
  n: "bg-brand-50 text-brand-800 ring-brand-200",
  s: "bg-canvas text-ink-3 ring-line",
  p: "bg-canvas text-ink-3 ring-line",
};

function TokensStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const shown = Math.min(d.tokens.length, tick * 2);
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {d.tokens.slice(0, shown).map((tk, i) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: токены не переставляются
            key={i}
            className={`animate-scale-in rounded-lg px-2.5 py-1 font-mono text-lg ring-1 ring-inset ${KIND_CLS[tk.kind] ?? KIND_CLS.w}`}
          >
            {visible(tk.text)}
          </span>
        ))}
        {shown < d.tokens.length && <span className="h-9 w-3 animate-pulse rounded bg-line" />}
      </div>
      <Caption>
        <span className="mr-4 font-semibold text-ink">{fmt(tx.tokensCount, { n: shown })}</span>
        {(["w", "n", "s", "p"] as const).map((k) => (
          <span key={k} className="mr-3 inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-sm ring-1 ring-inset ${KIND_CLS[k]}`} />
            {tx.tokenKinds[k]}
          </span>
        ))}
      </Caption>
    </div>
  );
}

function BilingualStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const drop = d.bilingual ? findSpan(d.raw, d.bilingual.dropped) : null;
  const keep = d.bilingual ? findSpan(d.raw, d.bilingual.kept) : null;
  const orgSpans = d.orgs.map((o) => findSpan(d.raw, o)).filter((x): x is [number, number] => !!x);
  if (!d.bilingual && !orgSpans.length) {
    return (
      <div>
        <Line raw={d.raw} marks={[]} />
        <Caption>
          <span className="inline-flex items-center gap-2 text-brand-700">
            <IconCheck className="h-4 w-4" /> {tx.bilingualNone}
          </span>
        </Caption>
      </div>
    );
  }
  const marks =
    tick >= 1
      ? [
          ...(keep ? [{ start: keep[0], end: keep[1], field: null, label: "KEPT", fresh: true }] : []),
          ...(drop ? [{ start: drop[0], end: drop[1], field: null, label: "KZ_DUP", fresh: true }] : []),
          ...orgSpans.map(([a, b]) => ({ start: a, end: b, field: null, label: "NOISE", fresh: true })),
        ]
      : [];
  const gone = tick >= 2 ? [...(drop ? [drop] : []), ...orgSpans] : [];
  return (
    <div>
      <Line raw={d.raw} marks={marks} dim={gone} strike={tick >= 1 ? gone.concat(drop ? [drop] : []) : []} />
      {tick >= 1 && (
        <Caption>
          {d.bilingual && (
            <span className="mr-4">
              <b className="text-ink">«{d.bilingual.kept}»</b> {tx.bilingualKept} ·{" "}
              <s className="text-ink-3">«{d.bilingual.dropped}»</s> {tx.bilingualDropped}
            </span>
          )}
          {d.orgs.map((o) => (
            <span key={o} className="mr-4">
              <s className="text-ink-3">«{o}»</s> {tx.partsDropped}
            </span>
          ))}
        </Caption>
      )}
    </div>
  );
}

function Slots({ values, fresh }: { values: Partial<Record<FieldName, string>>; fresh: FieldName | null }) {
  const { fieldLabels } = useI18n();
  return (
    <div className="grid gap-1.5">
      {FIELD_NAMES.map((f) => {
        const v = values[f];
        return (
          <div
            key={f}
            className={`flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-colors duration-300 ${
              v ? "bg-line-soft" : "bg-canvas"
            }`}
          >
            <span className="inline-flex items-center gap-1.5 text-ink-2">
              <span className={`h-2 w-2 rounded-full ${FIELD_COLORS[f].dot}`} />
              {fieldLabels[f]}
            </span>
            <span
              key={v ?? "-"}
              className={`truncate font-medium ${v ? "text-ink" : "text-ink-3/50"} ${fresh === f ? "animate-scale-in" : ""}`}
            >
              {v ?? "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function RulesStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const { stepLabels } = useI18n();
  const shown = d.rules.slice(0, tick);
  const last = shown[shown.length - 1];
  const values: Partial<Record<FieldName, string>> = {};
  for (const e of shown) values[e.field] = e.value;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div>
        <Line
          raw={d.raw}
          marks={shown
            .filter((e) => e.span)
            .map((e) => ({
              start: e.span?.[0] ?? 0,
              end: e.span?.[1] ?? 0,
              field: e.field,
              fresh: e === last,
            }))}
        />
        <Caption>
          {last ? (
            <span key={`${last.step}-${last.field}`} className="inline-flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-line-soft px-2 py-0.5 text-xs font-semibold text-ink">
                {stepLabels[last.step] ?? last.step}
              </span>
              <span className="font-mono text-xs text-ink-2">
                {last.note ?? `${last.field} = '${last.value}'`}
              </span>
            </span>
          ) : d.rules.length ? null : (
            tx.rulesNone
          )}
        </Caption>
      </div>
      <Slots values={values} fresh={last?.field ?? null} />
    </div>
  );
}

function TaggerStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const { fieldLabels } = useI18n();
  if (!d.modelOn) {
    return (
      <div>
        <Line raw={d.raw} marks={[]} />
        <Caption>{tx.taggerOff}</Caption>
      </div>
    );
  }
  const SWEEP = 5;
  const pos = Math.round((Math.min(tick, SWEEP) / SWEEP) * d.raw.length);
  const label = Array.from({ length: d.raw.length }, () => null as (typeof d.spans)[number] | null);
  for (const s of d.spans) for (let i = s.start; i < s.end && i < d.raw.length; i++) label[i] = s;
  const listed = d.spans.slice(0, Math.max(0, tick - SWEEP));
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-3">{tx.taggerSweep}</div>
      <div className="relative flex flex-wrap gap-[3px] font-mono text-lg">
        {[...d.raw].map((c, i) => {
          const s = label[i];
          const done = i < pos;
          const begin = s && s.start === i;
          return (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: символы строки не переставляются
              key={i}
              className={`relative grid h-9 min-w-6 place-items-center rounded-md px-1 transition-all duration-300 ${
                done && s
                  ? `${markCls(s.field, s.label)} ring-1 ring-inset`
                  : done
                    ? "bg-canvas text-ink-3"
                    : "bg-canvas text-ink-3/60"
              } ${i === pos ? "ring-2 ring-brand-500" : ""}`}
            >
              {c === " " ? "␣" : visible(c)}
              {done && begin && (
                <span className="absolute -top-2 left-0 animate-fade-in rounded bg-ink px-0.5 text-[8px] font-bold leading-3 text-white">
                  B
                </span>
              )}
            </span>
          );
        })}
      </div>
      {listed.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-3">
            {tx.taggerSpans}
            <Hint text={tx.hints.taggerSpans} label={tx.hintLabel} />
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {listed.map((s, i) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: спаны не переставляются
                key={i}
                className="flex animate-fade-up items-center gap-3 rounded-lg bg-canvas px-3 py-1.5 text-sm"
              >
                <span className={`rounded px-1.5 text-xs ring-1 ring-inset ${markCls(s.field, s.label)}`}>
                  {s.field ? fieldLabels[s.field] : s.label === "KZ_DUP" ? tx.kzDupLabel : tx.noiseLabel}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink">{d.raw.slice(s.start, s.end)}</span>
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line-soft">
                  <span
                    className="block h-full origin-left animate-grow-x rounded-full bg-brand-500"
                    style={{ width: `${s.p * 100}%` }}
                  />
                </span>
                <span className="w-10 text-right font-mono text-xs tabular-nums text-ink-2">
                  {s.p.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const DECISION_CLS: Record<string, string> = {
  agree: "bg-brand-50 text-brand-800",
  rules: "bg-warn-50 text-warn-800",
  model: "bg-warn-50 text-warn-800",
  rules_only: "bg-line-soft text-ink-2",
  model_only: "bg-line-soft text-ink-2",
};

function ArbiterStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const { fieldLabels } = useI18n();
  if (!d.arbiter.length) return <Caption>{tx.arbiterNone}</Caption>;
  const cell = (c: { value: string; score: number } | null, win: boolean) =>
    c ? (
      <span className={win ? "font-semibold text-ink" : "text-ink-3"}>
        {c.value || "—"} <span className="font-mono text-[10px] text-ink-3">{c.score.toFixed(2)}</span>
      </span>
    ) : (
      <span className="text-ink-3/50">—</span>
    );
  return (
    <div className="overflow-hidden rounded-xl ring-1 ring-line">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_8.5rem] gap-3 bg-canvas px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        <span />
        <span>{tx.arbiterRules}</span>
        <span>{tx.arbiterModel}</span>
        <span className="inline-flex items-center justify-end gap-1.5">
          {tx.arbiterDecision}
          <Hint text={tx.hints.arbiterScore} label={tx.hintLabel} />
        </span>
      </div>
      {d.arbiter.slice(0, tick).map((row) => (
        <div
          key={row.field}
          className="grid animate-fade-up grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_8.5rem] items-center gap-3 border-t border-line-soft px-3 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5 text-ink-2">
            <span className={`h-2 w-2 rounded-full ${FIELD_COLORS[row.field].dot}`} />
            {fieldLabels[row.field]}
          </span>
          {cell(row.rules, row.decision !== "model" && row.decision !== "model_only")}
          {cell(
            row.model,
            row.decision === "model" || row.decision === "model_only" || row.decision === "agree",
          )}
          <span
            className={`animate-scale-in justify-self-end rounded-full px-2 py-0.5 text-[11px] font-semibold ${DECISION_CLS[row.decision] ?? DECISION_CLS.rules_only}`}
          >
            {tx.decisions[row.decision] ?? row.decision}
          </span>
        </div>
      ))}
    </div>
  );
}

function ReferenceStage({
  d,
  tick,
  tx,
  health,
}: { d: Derived; tick: number; tx: DemoTexts; health: HealthInfo }) {
  const { fieldLabels, locale } = useI18n();
  const n = (v?: number) => (v != null ? v.toLocaleString(locale) : "—");
  return (
    <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
      <div className="rounded-2xl bg-canvas p-4 ring-1 ring-line">
        <div className="relative mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand-50 text-brand-800">
          {tick < Math.max(1, d.reference.length + 1) && (
            <span className="absolute inset-0 animate-ping rounded-xl bg-brand-200" />
          )}
          <svg
            viewBox="0 0 24 24"
            className="h-6 w-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <ellipse cx="12" cy="5.5" rx="7" ry="2.5" />
            <path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" />
          </svg>
        </div>
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-3">
          {tx.refStats}
          <Hint text={tx.hints.refFacts} label={tx.hintLabel} />
        </div>
        <dl className="mt-2 grid gap-1 text-sm">
          <div className="flex justify-between gap-2">
            <dt className="text-ink-3">{tx.facts.streets}</dt>
            <dd className="font-semibold tabular-nums text-ink">{n(health.counts?.street)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-ink-3">{tx.facts.houses}</dt>
            <dd className="font-semibold tabular-nums text-ink">{n(health.houses)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-ink-3">{tx.facts.cities}</dt>
            <dd className="font-semibold tabular-nums text-ink">{n(health.counts?.city)}</dd>
          </div>
        </dl>
      </div>
      <div>
        {!d.reference.length ? (
          <Caption>
            <span className="inline-flex items-center gap-2 text-brand-700">
              <IconCheck className="h-4 w-4" /> {tx.refNone}
            </span>
          </Caption>
        ) : (
          <div className="grid gap-2">
            {d.reference.slice(0, tick).map((e) => (
              <div
                key={e.field}
                className="flex animate-fade-up flex-wrap items-center gap-3 rounded-xl bg-canvas px-4 py-3 ring-1 ring-line"
              >
                <span className="inline-flex items-center gap-1.5 text-sm text-ink-2">
                  <span className={`h-2 w-2 rounded-full ${FIELD_COLORS[e.field].dot}`} />
                  {fieldLabels[e.field]}
                </span>
                <span className="text-ink-3/60">←</span>
                <span className="text-lg font-semibold text-ink">{e.value}</span>
                <span className="ml-auto rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-800">
                  {tx.refSources[e.source] ?? e.source}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Gauge({ value, size = 160 }: { value: number; size?: number }) {
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  const tone =
    value >= 0.8
      ? "stroke-brand-500"
      : value >= 0.6
        ? "stroke-lime-400"
        : value >= 0.3
          ? "stroke-warn"
          : "stroke-danger";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} className="fill-none stroke-line-soft" strokeWidth="10" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        className={`fill-none transition-[stroke-dashoffset,stroke] duration-700 ease-[var(--ease-out-soft)] ${tone}`}
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))}
      />
    </svg>
  );
}

function ConfidenceStage({ d, tick, tx }: { d: Derived; tick: number; tx: DemoTexts }) {
  const shown = d.parts.slice(0, tick);
  const sum = shown.reduce((a, [, v]) => a + v, 0);
  const final = tick > d.parts.length;
  const value = final ? d.confidence : Math.max(0, Math.min(0.99, sum));
  return (
    <div className="grid items-center gap-8 sm:grid-cols-[180px_minmax(0,1fr)]">
      <div className="relative grid place-items-center">
        <Gauge value={value} size={170} />
        <div className="absolute text-center">
          <div className="text-4xl font-semibold tabular-nums text-ink">{Math.round(value * 100)}%</div>
          {final && <div className="animate-fade-in text-xs text-ink-3">{tx.confFinal}</div>}
        </div>
      </div>
      <div className="grid gap-1.5">
        <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-3">
          {tx.confTitle}
          <Hint text={tx.hints.confParts} label={tx.hintLabel} />
        </div>
        {shown.map(([k, v]) => (
          <div
            key={k}
            className="flex animate-fade-up items-center gap-3 rounded-lg bg-canvas px-3 py-1.5 text-sm"
          >
            <span className="min-w-0 flex-1 truncate text-ink">
              {tx.confParts[k] ?? k.replace(/^(flag|bonus):/, "").replace(/_/g, " ")}
            </span>
            <span
              className={`font-mono text-xs font-semibold tabular-nums ${v >= 0 ? "text-brand-700" : "text-danger"}`}
            >
              {v >= 0 ? "+" : ""}
              {v.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function StageView({
  id,
  tick,
  d,
  tx,
  health,
}: { id: StageId; tick: number; d: Derived; tx: DemoTexts; health: HealthInfo }) {
  switch (id) {
    case "clean":
      return <CleanStage d={d} tick={tick} tx={tx} />;
    case "tokens":
      return <TokensStage d={d} tick={tick} tx={tx} />;
    case "bilingual":
      return <BilingualStage d={d} tick={tick} tx={tx} />;
    case "rules":
      return <RulesStage d={d} tick={tick} tx={tx} />;
    case "tagger":
      return <TaggerStage d={d} tick={tick} tx={tx} />;
    case "arbiter":
      return <ArbiterStage d={d} tick={tick} tx={tx} />;
    case "reference":
      return <ReferenceStage d={d} tick={tick} tx={tx} health={health} />;
    case "confidence":
      return <ConfidenceStage d={d} tick={tick} tx={tx} />;
  }
}

export { Gauge };
