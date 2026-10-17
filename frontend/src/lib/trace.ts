import { FIELD_NAMES, type FieldName } from "../api/client";

// разбор технических заметок trace (их пишет бэкенд, по-русски) в данные для показа

export interface Token {
  text: string;
  kind: string;
}

export function quoted(s: string): string[] {
  return [...s.matchAll(/'([^']*)'/g)].map((m) => m[1] ?? "");
}

export function asField(label: string): FieldName | null {
  const f = label.toLowerCase();
  return (FIELD_NAMES as readonly string[]).includes(f) ? (f as FieldName) : null;
}

/** «город:w | Алматы:w | /:p» -> токены с видом (w слово, n число, s разделитель, p знак). */
export function parseTokens(note: string): Token[] {
  if (!note) return [];
  return note.split(" | ").map((t) => {
    const k = t.lastIndexOf(":");
    return k > 0 ? { text: t.slice(0, k), kind: t.slice(k + 1) } : { text: t, kind: "w" };
  });
}

/** «английская раскладка: 'Fkvfns' -> 'Алматы'». */
export function parseLayout(notes: string[]): { from: string; to: string } | null {
  const n = notes.find((x) => x.includes("->"));
  const q = n ? quoted(n) : [];
  return q.length >= 2 ? { from: q[0] ?? "", to: q[1] ?? "" } : null;
}

export interface TaggerSpan {
  label: string;
  field: FieldName | null;
  text: string;
  p: number;
}

/** «режим on; спаны: CITY 'Алматы' p=1.0; HOUSE '59' p=1.0». */
export function parseTaggerSpans(notes: string[]): TaggerSpan[] {
  const n = notes.find((x) => x.includes("спаны:")) ?? "";
  return [...n.matchAll(/([A-Z_]+) '([^']*)' p=([\d.]+)/g)].map((m) => ({
    label: m[1] ?? "",
    field: asField(m[1] ?? ""),
    text: m[2] ?? "",
    p: Number(m[3] ?? 0),
  }));
}

export interface ArbiterGroups {
  agree: FieldName[];
  dispute: FieldName[];
  rulesOnly: FieldName[];
  modelOnly: FieldName[];
}

/** «согласны: city, house; спор: street_name; только правила: -; только модель: -». */
export function parseArbiter(notes: string[]): ArbiterGroups | null {
  const n = notes.find((x) => x.startsWith("согласны:"));
  if (!n) return null;
  const pick = (key: string) => {
    const m = n.match(new RegExp(`${key}:\\s*([^;]*)`));
    return (m?.[1] ?? "")
      .split(",")
      .map((s) => asField(s.trim()))
      .filter((f): f is FieldName => !!f);
  };
  return {
    agree: pick("согласны"),
    dispute: pick("спор"),
    rulesOnly: pick("только правила"),
    modelOnly: pick("только модель"),
  };
}

export interface Dispute {
  field: FieldName;
  rules: string;
  rulesScore: number;
  model: string;
  modelScore: number;
  winner: "rules" | "model";
}

/** «street_name: правила 'Нурсити 2' (2.60) vs модель '2' (4.14) -> rules». */
export function parseDisputes(notes: string[]): Dispute[] {
  const out: Dispute[] = [];
  for (const n of notes) {
    const m = n.match(/^(\w+): правила '([^']*)' \(([\d.-]+)\) vs модель '([^']*)' \(([\d.-]+)\) -> (\w+)/);
    const f = m ? asField(m[1] ?? "") : null;
    if (!m || !f) continue;
    out.push({
      field: f,
      rules: m[2] ?? "",
      rulesScore: Number(m[3]),
      model: m[4] ?? "",
      modelScore: Number(m[5]),
      winner: m[6] === "model" ? "model" : "rules",
    });
  }
  return out;
}

export function isRecord(x: unknown): x is Record<string, unknown> {
  return !!x && typeof x === "object" && !Array.isArray(x);
}

/** Числовые части confidence из trace: это JSON с сервера, значения проверяем, а не верим касту. */
export function numericParts(x: unknown): [string, number][] {
  if (!isRecord(x)) return [];
  return Object.entries(x).filter(
    (e): e is [string, number] => typeof e[1] === "number" && Number.isFinite(e[1]),
  );
}
