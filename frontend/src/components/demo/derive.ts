import { type ExplainRecord, FIELD_NAMES, type FieldName, type StepTrace } from "../../api/client";
import { type ConfModel, confModel } from "../../lib/confidence";
import { codepoints } from "../../lib/fields";
import {
  type Token,
  asField,
  isRecord,
  numericParts,
  parseLayout,
  parseTokens,
  quoted,
} from "../../lib/trace";

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
  /** модель уверенности (баллы признаков); null у ответов без слагаемых */
  conf: ConfModel | null;
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
  /** id для показа: строку из демо разбирают без id, а жюри присылает его в каждой записи */
  id: string;
  /** ответ в форме sample_output.json по порядку ключей, с источником каждого поля */
  output: OutLine[];
}

export interface OutLine {
  key: string;
  value: string | number | null;
  source: "string" | "reference" | "manual" | null;
}

export const DEMO_ID = "demo_001";

const RULE_STEPS = ["admin", "details", "street", "landmark", "numbers", "building", "leftover"];

function step(trace: StepTrace[], name: string): StepTrace | undefined {
  return trace.find((s) => s.step === name);
}

/** Какие символы raw выкинула очистка: жадно сопоставляем raw с очищенной строкой. */
function removedChars(raw: string, cleaned: string | null): Set<number> {
  const out = new Set<number>();
  if (cleaned == null) return out;
  // в кодпоинтах, как спаны сервера (lib/fields.codepoints)
  const rs = codepoints(raw);
  const cs = codepoints(cleaned);
  let j = 0;
  for (let i = 0; i < rs.length; i++) {
    const c = rs[i];
    if (j < cs.length && (c === cs[j] || (/\s/.test(c ?? "") && cs[j] === " "))) j++;
    else out.add(i);
  }
  return out;
}

export function derive(r: ExplainRecord): Derived {
  const raw = String(r.raw_address ?? "");
  const trace = r.trace ?? [];

  const layout = parseLayout(step(trace, "layout")?.notes ?? []);

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

  // r.model это свободный JSON с сервера: форму проверяем, битая запись не должна ронять страницу
  const model = isRecord(r.model) ? r.model : null;
  const spans: ModelSpan[] = (Array.isArray(model?.spans) ? model.spans : []).flatMap((s: unknown) => {
    if (
      !isRecord(s) ||
      typeof s.label !== "string" ||
      typeof s.start !== "number" ||
      typeof s.end !== "number"
    )
      return [];
    const p = typeof s.p_cal === "number" ? s.p_cal : typeof s.p === "number" ? s.p : 0;
    return [{ label: s.label, field: asField(s.label), start: s.start, end: s.end, p }];
  });
  const cand = (x: unknown) =>
    isRecord(x) && typeof x.score === "number" ? { value: String(x.value ?? ""), score: x.score } : null;
  const arbiter: ArbiterRow[] = Object.entries(isRecord(model?.fields) ? model.fields : {}).flatMap(
    ([k, v]) => {
      const field = asField(k);
      if (!field || !isRecord(v)) return [];
      return [{ field, rules: cand(v.rules), model: cand(v.model), decision: String(v.decision ?? "") }];
    },
  );

  const reference: RefEvent[] = Object.entries(step(trace, "reference")?.changes ?? {}).flatMap(([k, v]) => {
    const f = asField(k);
    if (!f || !v || typeof v !== "object" || !("value" in v)) return [];
    const o = v as { value: unknown; source?: string };
    return [{ field: f, value: String(o.value ?? ""), source: (o.source ?? "").replace(/^reference:/, "") }];
  });

  const parts = numericParts(step(trace, "confidence")?.changes?.parts);

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
    conf: confModel(trace, r.confidence),
    confidence: r.confidence,
    timings: trace.map((s) => ({ step: s.step, ms: s.ms })),
    id: r.id == null ? DEMO_ID : String(r.id),
    output: [
      { key: "id", value: r.id == null ? DEMO_ID : String(r.id), source: null },
      { key: "raw_address", value: raw, source: null },
      ...FIELD_NAMES.map((f): OutLine => {
        const src = r.fields?.[f]?.source ?? null;
        const value = r[f] ?? null;
        return {
          key: f,
          value,
          source:
            value == null || !src
              ? null
              : src === "string"
                ? "string"
                : src === "manual"
                  ? "manual"
                  : "reference",
        };
      }),
      { key: "confidence", value: r.confidence, source: null },
    ],
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
    confidence: (d.conf ? d.conf.terms.length + 1 : d.parts.length) + 2,
    // вход: скобка, id, raw_address, пауза; выход: по две строки ответа за тик
    input: 4,
    output: Math.ceil(d.output.length / 2) + 2,
  };
}
