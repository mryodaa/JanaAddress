import { useEffect, useState } from "react";
import { type ExplainRecord, FIELD_NAMES, type FieldName } from "../../api/client";
import { useI18n } from "../../i18n";
import { FIELD_COLORS } from "../../lib/fields";
import { IconCheck, IconCopy } from "../icons";
import { Button, FieldDot, Highlighted, Hint } from "../ui";
import type { HealthInfo } from "./Theater";
import type { Derived } from "./derive";
import { type DemoTexts, fmt } from "./texts";

function Section({
  title,
  children,
  className = "",
  i = 0,
  hint,
  hintLabel = "?",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
  i?: number;
  hint?: string;
  hintLabel?: string;
}) {
  return (
    <section
      className={`stagger animate-fade-up rounded-[20px] border border-line bg-white p-5 ${className}`}
      style={{ "--i": i * 3 } as React.CSSProperties}
    >
      <h3 className="mb-4 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-3">
        {title}
        {hint && <Hint text={hint} label={hintLabel} />}
      </h3>
      {children}
    </section>
  );
}

function outputJson(r: ExplainRecord): string {
  const out: Record<string, unknown> = { id: r.id, raw_address: r.raw_address };
  for (const f of FIELD_NAMES) out[f] = r[f] ?? null;
  out.confidence = r.confidence;
  return JSON.stringify(out, null, 2);
}

type Cover = "fields" | "markers" | "dropped" | "unparsed";

/** Доли строки по символам без пробелов: что ушло в поля, что служебное, что отброшено, что не разобрано. */
function coverage(r: ExplainRecord, d: Derived): Record<Cover, number> {
  const raw = d.raw;
  const kind: (Cover | null)[] = [...raw].map((c, i) =>
    /\s/.test(c) || d.removed.has(i) ? null : "markers",
  );
  const mark = (a: number, b: number, k: Cover) => {
    for (let i = a; i < b && i < raw.length; i++) if (kind[i] && kind[i] !== "fields") kind[i] = k;
  };
  const find = (part: string, k: Cover) => {
    const i = part ? raw.indexOf(part) : -1;
    if (i >= 0) mark(i, i + part.length, k);
  };
  for (const s of d.spans) if (s.label === "KZ_DUP" || s.label === "NOISE") mark(s.start, s.end, "dropped");
  if (d.bilingual) find(d.bilingual.dropped, "dropped");
  for (const o of d.orgs) find(o, "dropped");
  for (const u of r.unparsed ?? []) find(u, "unparsed");
  // поля последними и с приоритетом: спан поля важнее любой другой метки
  for (const fe of Object.values(r.fields ?? {})) {
    if (fe?.source !== "string" || !fe.span) continue;
    for (let i = fe.span[0]; i < fe.span[1] && i < raw.length; i++) if (kind[i]) kind[i] = "fields";
  }
  const out: Record<Cover, number> = { fields: 0, markers: 0, dropped: 0, unparsed: 0 };
  let n = 0;
  for (const k of kind) {
    if (!k) continue;
    out[k]++;
    n++;
  }
  for (const k of Object.keys(out) as Cover[]) out[k] = n ? out[k] / n : 0;
  return out;
}

const COVER_CLS: Record<Cover, string> = {
  fields: "bg-brand-600",
  markers: "bg-ink-3/40",
  dropped: "bg-warn",
  unparsed: "bg-danger",
};

/** Адрес «как на конверте»: от улицы к области, без повторов. */
function envelopeLines(r: ExplainRecord, labels: Record<FieldName, string>): string[] {
  const v = (f: FieldName) => r[f] ?? null;
  const street = [v("street_type"), v("street_name")].filter(Boolean).join(" ");
  const nums = (["house", "apartment", "entrance", "floor"] as const)
    .filter((f) => v(f))
    .map((f) => `${labels[f]} ${v(f)}`);
  const l1 = [street, ...nums].filter(Boolean).join(", ");
  const l2 = [v("living_area"), v("district")].filter(Boolean).join(", ");
  const city = v("city");
  const prov = v("province");
  const l3 = [city, prov && prov !== city ? prov : null].filter(Boolean).join(", ");
  const l4 = v("landmark") ? `${labels.landmark}: ${v("landmark")}` : "";
  return [l1, l2, l3, l4].filter(Boolean);
}

export function Analysis({
  r,
  d,
  tx,
  health,
  threshold,
}: { r: ExplainRecord; d: Derived; tx: DemoTexts; health: HealthInfo; threshold: number }) {
  const { fieldLabels, stepLabels, locale } = useI18n();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const conf = r.confidence;
  const verdict =
    conf >= Math.max(threshold, 0.8) ? tx.verdictHigh : conf >= threshold ? tx.verdictMid : tx.verdictLow;
  const tone =
    conf >= Math.max(threshold, 0.8)
      ? "bg-brand-50 text-brand-800 ring-brand-200"
      : conf >= threshold
        ? "bg-lime-50 text-lime-800 ring-lime-200"
        : "bg-warn-50 text-warn-800 ring-warn/40";
  const lines = envelopeLines(r, fieldLabels);
  const pct = Math.round(threshold * 100);
  const H = (id: keyof DemoTexts["hints"]) => ({ hint: fmt(tx.hints[id], { pct }), hintLabel: tx.hintLabel });

  const counts = { agree: 0, dispute: 0, single: 0 };
  for (const a of d.arbiter) {
    if (a.decision === "agree") counts.agree++;
    else if (a.decision === "rules" || a.decision === "model") counts.dispute++;
    else counts.single++;
  }
  const disputes = d.arbiter.filter((a) => a.decision === "rules" || a.decision === "model");

  const cover = coverage(r, d);
  const filled = FIELD_NAMES.filter((f) => r[f] != null);
  const fromString = filled.filter((f) => r.fields?.[f]?.source === "string").length;
  const maxPart = Math.max(0.01, ...d.parts.map(([, v]) => Math.abs(v)));
  const total = d.timings.reduce((a, s) => a + s.ms, 0);
  const maxMs = Math.max(0.001, ...d.timings.map((s) => s.ms));

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="animate-fade-up">
        <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{tx.reportTitle}</h2>
        <p className="mt-1 text-sm text-ink-2 sm:text-base">{tx.reportLead}</p>
      </div>

      {/* итог: строка с подсветкой и вердикт */}
      <section className="stagger grid animate-fade-up grid-cols-[minmax(0,1fr)] gap-5 rounded-[20px] border border-line bg-white p-5 sm:p-6 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="text-lg leading-relaxed sm:text-xl">
            <Highlighted raw={d.raw} fields={r.fields ?? {}} />
          </div>
          <div
            className={`mt-4 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ring-1 ring-inset ${tone}`}
          >
            <IconCheck className="h-4 w-4" />
            {verdict}
            <Hint text={fmt(tx.hints.verdict, { pct })} label={tx.hintLabel} />
          </div>
        </div>
        <div className="flex items-center gap-4 md:flex-col md:items-end">
          <div className="text-5xl font-semibold tracking-tight tabular-nums">{Math.round(conf * 100)}%</div>
          <div className="flex items-center gap-1.5 text-xs text-ink-3">
            confidence
            <Hint text={fmt(tx.hints.confidence, { pct })} label={tx.hintLabel} />
          </div>
        </div>
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* конверт: рамка авиапочты в цветах Jana Post */}
        <Section title={tx.envelope} i={1} {...H("envelope")}>
          <div className="rounded-2xl bg-[repeating-linear-gradient(135deg,var(--color-brand-600)_0_14px,#fff_14px_22px,var(--color-warn)_22px_36px,#fff_36px_44px)] p-1.5">
            <div className="relative min-h-40 rounded-xl bg-white p-4 pr-24 sm:p-5 sm:pr-28">
              <div className="absolute top-4 right-4 grid h-20 w-16 rotate-3 place-items-center rounded-md border-2 border-dashed border-brand-600 bg-brand-50 text-center text-brand-700">
                <div>
                  <div className="text-lg font-bold leading-none tabular-nums">{Math.round(conf * 100)}</div>
                  <div className="text-[9px] font-semibold uppercase tracking-wide">conf %</div>
                </div>
              </div>
              {lines.length ? (
                <div className="grid gap-1 font-medium">
                  {lines.map((l, i) => (
                    <div
                      key={l}
                      className={`stagger animate-fade-up border-b border-dashed border-line pb-1 ${i === 0 ? "text-lg" : "text-ink-2"}`}
                      style={{ "--i": i * 4 + 6 } as React.CSSProperties}
                    >
                      {l}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-ink-3">{tx.envelopeEmpty}</div>
              )}
            </div>
          </div>
        </Section>

        <Section title={tx.agreementTitle} i={2} {...H("agreement")}>
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                [counts.agree, tx.agreeCount, "text-brand-700"],
                [counts.dispute, tx.disputeCount, "text-warn-800"],
                [counts.single, tx.singleCount, "text-ink-2"],
              ] as const
            ).map(([n, l, c]) => (
              <div key={l} className="rounded-2xl bg-canvas p-3 text-center">
                <div className={`text-2xl font-semibold tabular-nums ${c}`}>{n}</div>
                <div className="text-xs text-ink-3">{l}</div>
              </div>
            ))}
          </div>
          {disputes.length > 0 && (
            <div className="mt-3 grid gap-1.5">
              {disputes.map((a) => (
                <div
                  key={a.field}
                  className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-50 px-3 py-2 text-sm"
                >
                  <FieldDot field={a.field} />
                  <span className="text-ink-2">{fieldLabels[a.field]}:</span>
                  <span className={a.decision === "rules" ? "font-semibold" : "text-ink-3 line-through"}>
                    {a.rules?.value || "—"}
                  </span>
                  <span className="text-ink-3">vs</span>
                  <span className={a.decision === "model" ? "font-semibold" : "text-ink-3 line-through"}>
                    {a.model?.value || "—"}
                  </span>
                  <span className="ml-auto text-xs font-semibold text-warn-800">
                    {tx.decisions[a.decision]}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-ink-2">
            <div className="rounded-xl border border-line-soft p-3">
              <div className="mb-1 flex items-center gap-1.5 font-semibold text-ink">
                {tx.modelFacts}
                <Hint text={tx.hints.modelF1} label={tx.hintLabel} />
              </div>
              <div>BiLSTM-CRF · ONNX int8</div>
              {health.f1 != null && (
                <div>
                  {tx.facts.f1}: <b className="tabular-nums text-ink">{health.f1.toFixed(3)}</b>
                </div>
              )}
              {health.version && <div className="font-mono text-[10px] text-ink-3">{health.version}</div>}
            </div>
            <div className="rounded-xl border border-line-soft p-3">
              <div className="mb-1 flex items-center gap-1.5 font-semibold text-ink">
                {tx.refFacts}
                <Hint text={tx.hints.refFacts} label={tx.hintLabel} />
              </div>
              <div>
                <b className="tabular-nums text-ink">
                  {health.counts?.street?.toLocaleString(locale) ?? "—"}
                </b>{" "}
                {tx.facts.streets}
              </div>
              <div>
                <b className="tabular-nums text-ink">{health.houses?.toLocaleString(locale) ?? "—"}</b>{" "}
                {tx.facts.houses}
              </div>
              <div className="text-ink-3">OSM + КАТО</div>
            </div>
          </div>
        </Section>
      </div>

      <Section title={tx.fieldsTitle} i={3} {...H("fields")}>
        <div className="grid gap-x-8 sm:grid-cols-2">
          {FIELD_NAMES.map((f) => {
            const fe = r.fields?.[f];
            const v = r[f] ?? null;
            const src = fe?.source ?? null;
            const via = src?.replace(/^reference:/, "") ?? "";
            return (
              <div key={f} className="flex items-baseline gap-3 border-b border-line-soft py-2.5">
                <span className="flex w-36 shrink-0 items-center gap-1.5 text-xs text-ink-2">
                  <FieldDot field={f} />
                  {fieldLabels[f]}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block break-words text-sm font-medium ${v ? "" : "font-normal text-line"}`}
                  >
                    {v ?? tx.notFound}
                  </span>
                  {v && src && (
                    <span className="mt-0.5 block text-[11px] text-ink-3">
                      {src === "string" && fe?.span ? (
                        <span className={`rounded px-1 ring-1 ring-inset ${FIELD_COLORS[f].mark}`}>
                          {fmt(tx.fromString, { a: fe.span[0], b: fe.span[1] })}
                        </span>
                      ) : (
                        <span className="rounded bg-brand-50 px-1 text-brand-800 ring-1 ring-inset ring-brand-200">
                          {tx.refSources[via] ?? via}
                        </span>
                      )}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </Section>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <Section title={tx.confTitle} i={4} {...H("confParts")}>
          <div className="grid gap-1.5">
            {d.parts.map(([k, v], i) => (
              <div key={k} className="grid grid-cols-[minmax(0,1fr)_120px_48px] items-center gap-3 text-sm">
                <span className="truncate text-ink-2">
                  {tx.confParts[k] ?? k.replace(/^(flag|bonus):/, "").replace(/_/g, " ")}
                </span>
                <span className="relative h-2 rounded-full bg-line-soft">
                  <span
                    className={`stagger absolute inset-y-0 animate-grow-x rounded-full ${v >= 0 ? "left-1/2 origin-left bg-brand-600" : "right-1/2 origin-right bg-danger"}`}
                    style={{ width: `${(Math.abs(v) / maxPart) * 50}%`, "--i": i + 8 } as React.CSSProperties}
                  />
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-ink/20" />
                </span>
                <span
                  className={`text-right font-mono text-xs font-semibold tabular-nums ${v >= 0 ? "text-brand-700" : "text-danger"}`}
                >
                  {v >= 0 ? "+" : ""}
                  {v.toFixed(2)}
                </span>
              </div>
            ))}
            <div className="mt-2 flex items-center justify-between border-t border-line pt-2 text-sm font-semibold">
              <span>{tx.confFinal}</span>
              <span className="tabular-nums">{conf.toFixed(2)}</span>
            </div>
          </div>
        </Section>

        <Section title={tx.timingTitle} i={5} {...H("timing")}>
          <div className="grid gap-1">
            {d.timings.map((s, i) => (
              <div
                key={s.step}
                className="grid grid-cols-[minmax(0,1fr)_100px_64px] items-center gap-3 text-xs"
              >
                <span className="truncate text-ink-2">{stepLabels[s.step] ?? s.step}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-line-soft">
                  {/* корень: короткие шаги тоже видны рядом с долгим */}
                  <span
                    className="stagger block h-full origin-left animate-grow-x rounded-full bg-brand-600/70"
                    style={
                      { width: `${Math.sqrt(s.ms / maxMs) * 100}%`, "--i": i + 8 } as React.CSSProperties
                    }
                  />
                </span>
                <span className="text-right font-mono tabular-nums text-ink-3">{s.ms.toFixed(2)}</span>
              </div>
            ))}
            <div className="mt-2 flex items-center justify-between border-t border-line pt-2 text-sm font-semibold">
              <span>{tx.totalTime}</span>
              <span className="tabular-nums">{total.toFixed(1)} ms</span>
            </div>
            <p className="mt-1 text-[11px] text-ink-3">{tx.timingNote}</p>
          </div>
        </Section>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Section title={tx.unparsedTitle} i={6} {...H("unparsed")}>
            {(r.unparsed ?? []).length ? (
              <div className="flex flex-wrap gap-1.5">
                {(r.unparsed ?? []).map((u) => (
                  <span key={u} className="rounded-md bg-danger-50 px-2 py-0.5 font-mono text-sm text-danger">
                    {u}
                  </span>
                ))}
              </div>
            ) : (
              <div className="inline-flex items-center gap-2 text-sm text-brand-700">
                <IconCheck className="h-4 w-4" /> {tx.unparsedNone}
              </div>
            )}
          </Section>
          <Section title={tx.coverageTitle} i={6} className="flex-1" {...H("coverage")}>
            <div className="flex h-3 overflow-hidden rounded-full bg-line-soft">
              {(Object.keys(cover) as Cover[]).map((k) =>
                cover[k] > 0 ? (
                  <span
                    key={k}
                    className={`h-full origin-left animate-grow-x ${COVER_CLS[k]}`}
                    style={{ width: `${cover[k] * 100}%` }}
                  />
                ) : null,
              )}
            </div>
            <div className="mt-3 grid gap-1.5">
              {(Object.keys(cover) as Cover[])
                .filter((k) => cover[k] > 0 || k === "fields")
                .map((k) => (
                  <div key={k} className="flex items-center gap-2 text-sm">
                    <span className={`h-2.5 w-2.5 shrink-0 rounded-sm ${COVER_CLS[k]}`} />
                    <span className="min-w-0 flex-1 truncate text-ink-2">{tx.coverageParts[k]}</span>
                    <span className="font-semibold tabular-nums">{Math.round(cover[k] * 100)}%</span>
                  </div>
                ))}
            </div>
            <div className="mt-4 border-t border-line-soft pt-3">
              <div className="mb-2 text-sm font-medium">
                {fmt(tx.coverageFilled, { n: filled.length, total: FIELD_NAMES.length })}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {FIELD_NAMES.map((f) => {
                  const on = r[f] != null;
                  const ref = on && r.fields?.[f]?.source !== "string";
                  return (
                    <span
                      key={f}
                      title={fieldLabels[f]}
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${
                        on
                          ? ref
                            ? "bg-brand-50 text-brand-800 ring-brand-200"
                            : `${FIELD_COLORS[f].mark}`
                          : "bg-canvas text-ink-3/60 ring-line-soft"
                      }`}
                    >
                      {fieldLabels[f]}
                    </span>
                  );
                })}
              </div>
              <div className="mt-2 text-xs text-ink-3">
                {tx.coverageFromString}: <b className="text-ink">{fromString}</b> · {tx.coverageFromRef}:{" "}
                <b className="text-ink">{filled.length - fromString}</b>
              </div>
            </div>
          </Section>
        </div>
        <Section title={tx.jsonTitle} i={7} className="flex flex-col" {...H("json")}>
          {/* код растягивается на высоту ряда: пустого места под ним нет */}
          <div className="relative min-h-72 flex-1">
            <pre className="absolute inset-0 overflow-auto rounded-xl bg-ink p-4 font-mono text-xs leading-relaxed text-white/90">
              {outputJson(r)}
            </pre>
            <div className="absolute top-2 right-2">
              <Button
                size="sm"
                icon={
                  copied ? <IconCheck className="h-4 w-4 animate-check-pop text-brand-600" /> : <IconCopy />
                }
                onClick={() => {
                  void navigator.clipboard
                    .writeText(outputJson(r))
                    .then(() => setCopied(true))
                    .catch(() => undefined);
                }}
              >
                {copied ? tx.copied : tx.copy}
              </Button>
            </div>
          </div>
        </Section>
      </div>
    </div>
  );
}
