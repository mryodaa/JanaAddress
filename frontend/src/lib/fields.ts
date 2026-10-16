import type { FieldExplain, FieldName } from "../api/client";
import type { Language } from "../i18n/types";

export const FIELD_LABELS: Record<FieldName, string> = {
  province: "Область",
  city: "Город",
  district: "Район",
  living_area: "Жилой массив / ЖК",
  street_type: "Тип улицы",
  street_name: "Улица",
  house: "Дом",
  apartment: "Кв.",
  entrance: "Подъезд",
  floor: "Этаж",
  landmark: "Ориентир",
};

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

export function sourceLabel(source: string | null | undefined, lang: Language = "ru"): string | null {
  if (!source || source === "string") return null;
  if (source === "manual") {
    if (lang === "kk") return "өңдеу";
    if (lang === "en") return "edit";
    return "правка";
  }
  const [, s] = source.split(":");
  const prefix = lang === "kk" ? "анықтамалық" : lang === "en" ? "reference" : "справочник";
  return s ? `${prefix} · ${s.toUpperCase()}` : prefix;
}

export interface Piece {
  text: string;
  field: FieldName | null;
}

/** Разбивает raw_address на куски по спанам полей (спаны в символах оригинала). */
export function highlight(raw: string, fields: Partial<Record<string, FieldExplain>>): Piece[] {
  const owner: (FieldName | null)[] = Array.from({ length: raw.length }, () => null);
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
    for (let i = s; i < e && i < raw.length; i++) owner[i] = f;
  }
  const pieces: Piece[] = [];
  for (let i = 0; i < raw.length; i++) {
    const f = owner[i] ?? null;
    const last = pieces[pieces.length - 1];
    if (last && last.field === f) last.text += raw[i];
    else pieces.push({ text: raw[i] ?? "", field: f });
  }
  return pieces;
}

/** Невидимые символы показываем значком, чтобы оператор их видел. */
export function visible(text: string): string {
  return text.replace(/\u200b|\u200c|\u200d|\u2060|\ufeff|\u00ad/g, "·").replace(/\u00a0/g, "␣");
}
