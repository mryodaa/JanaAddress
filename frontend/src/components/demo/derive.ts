import type { ExplainRecord, FieldName, StepTrace } from "../../api/client";
import { type Token, asField, parseTokens, quoted } from "../../lib/trace";

// из ответа /parse?explain=true достаём то, что показывает анимация; ничего не придумываем сверх trace

export type { Token };

export interface RuleEvent {
  step: string;
  field: FieldName;
  value: string;
  span: [number, number] | null;
  note: string | null;
}

export interface ModelSpan {
  label: string;
  field: FieldName | null;
  start: number;
  end: number;
  p: number;
}

export interface ArbiterRow {
  field: FieldName;
  rules: { value: string; score: number } | null;
  model: { value: string; score: number } | null;
  decision: string;
}

export interface RefEvent {
  field: FieldName;
  value: string;
  source: string;
}

export interface Derived {
  raw: string;
  removed: Set<number>;
  layout: { from: string; to: string } | null;
  cleaned: string | null;
  tokens: Token[];
  bilingual: { kept: string; dropped: string } | null;
  orgs: string[];
  rules: RuleEvent[];
  modelOn: boolean;
  spans: ModelSpan[];
  arbiter: ArbiterRow[];
  reference: RefEvent[];
  parts: [string, number][];
  confidence: number;
  timings: { step: string; ms: number }[];
}

const RULE_STEPS = ["admin", "details", "street", "landmark", "numbers", "building", "leftover"];

function step(trace: StepTrace[], name: string): StepTrace | undefined {
  return trace.find((s) => s.step === name);
}

/** Какие символы raw выкинула очистка: жадно сопоставляем raw с очищенной строкой. */
function removedChars(raw: string, cleaned: string | null): Set<number> {
  const out = new Set<number>();
  if (cleaned == null) return out;
  let j = 0;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (j < cleaned.length && (c === cleaned[j] || (/\s/.test(c ?? "") && cleaned[j] === " "))) j++;
    else out.add(i);
  }
  return out;
}

export function derive(r: ExplainRecord): Derived {
  const raw = String(r.raw_address ?? "");
  const trace = r.trace ?? [];

  const layoutNote = (step(trace, "layout")?.notes ?? []).find((n) => n.includes("->"));
  const lq = layoutNote ? quoted(layoutNote) : [];
  const layout = lq.length >= 2 ? { from: lq[0] ?? "", to: lq[1] ?? "" } : null;

  const cleanNote = (step(trace, "clean")?.notes ?? []).find((n) => n.startsWith("clean:"));
  const cleaned = cleanNote ? (quoted(cleanNote)[0] ?? null) : null;

  const tokNote = (step(trace, "tokenize")?.notes ?? [])[0] ?? "";
  const tokens: Token[] = parseTokens(tokNote);

  const biNote = (step(trace, "split_bilingual")?.notes ?? [])[0];
  const bq = biNote ? quoted(biNote) : [];
  const bilingual = bq.length >= 2 ? { kept: bq[0] ?? "", dropped: bq[1] ?? "" } : null;
  const orgs = (step(trace, "parts")?.notes ?? []).flatMap((n) => quoted(n).slice(0, 1));

  const rules: RuleEvent[] = [];
  for (const name of RULE_STEPS) {
    const s = step(trace, name);
    if (!s) continue;
    for (const [k, v] of Object.entries(s.changes ?? {})) {
      const f = asField(k);
      if (!f || !v || typeof v !== "object" || !("value" in v)) continue;
      const value = String((v as { value: unknown }).value ?? "");
      const fe = r.fields?.[f];
      rules.push({
        step: name,
        field: f,
        value,
        span: fe?.source === "string" && fe.span ? [fe.span[0], fe.span[1]] : null,
        note: (s.notes ?? []).find((n) => n.startsWith(f) || n.includes(`'${value}'`)) ?? null,
      });
    }
  }

  const model = r.model as
    | {
        mode?: string;
        spans?: { label: string; start: number; end: number; p: number; p_cal?: number }[];
        fields?: Record<
          string,
          {
            rules?: { value: string; score: number } | null;
            model?: { value: string; score: number } | null;
            decision: string;
          }
        >;
      }
    | null
    | undefined;
  const spans: ModelSpan[] = (model?.spans ?? []).map((s) => ({
    label: s.label,
    field: asField(s.label),
    start: s.start,
    end: s.end,
    p: s.p_cal ?? s.p,
  }));
  const arbiter: ArbiterRow[] = Object.entries(model?.fields ?? {})
    .filter(([k]) => asField(k))
    .map(([k, v]) => ({
      field: k as FieldName,
      rules: v.rules ? { value: String(v.rules.value ?? ""), score: v.rules.score } : null,
      model: v.model ? { value: String(v.model.value ?? ""), score: v.model.score } : null,
      decision: v.decision,
    }));

  const reference: RefEvent[] = Object.entries(step(trace, "reference")?.changes ?? {}).flatMap(([k, v]) => {
    const f = asField(k);
    if (!f || !v || typeof v !== "object" || !("value" in v)) return [];
    const o = v as { value: unknown; source?: string };
    return [{ field: f, value: String(o.value ?? ""), source: (o.source ?? "").replace(/^reference:/, "") }];
  });

  const conf = step(trace, "confidence")?.changes as { parts?: Record<string, number> } | undefined;
  const parts = Object.entries(conf?.parts ?? {});

  return {
    raw,
    removed: removedChars(raw, layout ? null : cleaned),
    layout,
    cleaned,
    tokens,
    bilingual,
    orgs,
    rules,
    modelOn: !!model && model.mode !== "off",
    spans,
    arbiter,
    reference,
    parts,
    confidence: r.confidence,
    timings: trace.map((s) => ({ step: s.step, ms: s.ms })),
  };
}

/** Сколько «тиков» анимации у каждого этапа: шаги внутри этапа появляются по одному. */
export function ticksOf(d: Derived): Record<string, number> {
  return {
    clean: d.layout || d.removed.size ? 3 : 2,
    tokens: Math.max(2, Math.ceil(d.tokens.length / 2) + 1),
    bilingual: d.bilingual || d.orgs.length ? 3 : 1,
    rules: Math.max(1, d.rules.length + 1),
    tagger: d.modelOn ? 6 + d.spans.length : 1,
    arbiter: Math.max(1, d.arbiter.length + 1),
    reference: Math.max(1, d.reference.length + 1),
    confidence: d.parts.length + 2,
  };
}
