import type { FieldExplain, FieldName } from "../api/client";

// полные имена классов, чтобы Tailwind их нашёл при сборке
export const FIELD_COLORS: Record<FieldName, { mark: string; dot: string }> = {
  province: { mark: "bg-sky-100 text-sky-900 ring-sky-300", dot: "bg-sky-400" },
  city: { mark: "bg-blue-100 text-blue-900 ring-blue-300", dot: "bg-blue-500" },
  district: { mark: "bg-indigo-100 text-indigo-900 ring-indigo-300", dot: "bg-indigo-500" },
  living_area: { mark: "bg-violet-100 text-violet-900 ring-violet-300", dot: "bg-violet-500" },
  street_type: { mark: "bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300", dot: "bg-fuchsia-500" },
  street_name: { mark: "bg-emerald-100 text-emerald-900 ring-emerald-300", dot: "bg-emerald-500" },
  house: { mark: "bg-amber-100 text-amber-900 ring-amber-300", dot: "bg-amber-500" },
  apartment: { mark: "bg-orange-100 text-orange-900 ring-orange-300", dot: "bg-orange-500" },
  entrance: { mark: "bg-rose-100 text-rose-900 ring-rose-300", dot: "bg-rose-500" },
  floor: { mark: "bg-pink-100 text-pink-900 ring-pink-300", dot: "bg-pink-500" },
  landmark: { mark: "bg-teal-100 text-teal-900 ring-teal-300", dot: "bg-teal-500" },
};

/**
 * Строка как массив кодпоинтов. Спаны сервера считаются в символах Python (кодпоинтах), а индексы строки JS в
 * UTF-16: после эмодзи или другого символа вне BMP подсветка по raw[i] съехала бы.
 */
export function codepoints(s: string): string[] {
  return Array.from(s);
}

/** indexOf по кодпоинтам: позиция подстроки part в cps или -1. */
export function cpIndexOf(cps: string[], part: string): number {
  const p = codepoints(part);
  if (!p.length) return -1;
  outer: for (let i = 0; i + p.length <= cps.length; i++) {
    for (let j = 0; j < p.length; j++) if (cps[i + j] !== p[j]) continue outer;
    return i;
  }
  return -1;
}

export interface Piece {
  text: string;
  field: FieldName | null;
}

/** Разбивает raw_address на куски по спанам полей (спаны в символах оригинала). */
export function highlight(raw: string, fields: Partial<Record<string, FieldExplain>>): Piece[] {
  const cps = codepoints(raw);
  const owner: (FieldName | null)[] = Array.from({ length: cps.length }, () => null);
  // порядок важен: более конкретные поля поверх общих
  const order: FieldName[] = [
    "landmark",
    "street_type",
    "street_name",
    "living_area",
    "district",
    "city",
    "province",
    "house",
    "apartment",
    "entrance",
    "floor",
  ];
  for (const f of order) {
    const fe = fields[f];
    if (!fe?.span || fe.source !== "string") continue;
    const [s, e] = fe.span;
    for (let i = s; i < e && i < cps.length; i++) owner[i] = f;
  }
  const pieces: Piece[] = [];
  for (let i = 0; i < cps.length; i++) {
    const f = owner[i] ?? null;
    const last = pieces[pieces.length - 1];
    if (last && last.field === f) last.text += cps[i];
    else pieces.push({ text: cps[i] ?? "", field: f });
  }
  return pieces;
}

/** Невидимые символы показываем значком, чтобы оператор их видел. */
export function visible(text: string): string {
  return text.replace(/\u200b|\u200c|\u200d|\u2060|\ufeff|\u00ad/g, "·").replace(/\u00a0/g, "␣");
}
