import type { StepTrace } from "../api/client";
import { isRecord } from "./trace";

/** Слагаемое модели уверенности: значение признака, вес и баллы (вес × значение) в логитах. */
export interface ConfTerm {
  key: string;
  x: number;
  w: number;
  points: number;
}

/**
 * Модель уверенности одной записи (шаг confidence в trace): p = sigmoid(intercept + сумма баллов), затем
 * ограничение диапазоном bounds. Баллы складываются, поэтому их можно сравнивать и вычитать: в отличие от
 * вкладов в проценты они не зависят от порядка признаков.
 */
export interface ConfModel {
  intercept: number;
  terms: ConfTerm[];
  logit: number;
  /** итог, как в ответе */
  p: number;
  /** вероятность до ограничения диапазоном */
  raw: number;
  bounds: [number, number];
}

export function sigmoid(z: number): number {
  return z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
}

/** Сколько баллов соответствует вероятности p (обратная к sigmoid). */
export function logit(p: number): number {
  const q = Math.min(0.9999, Math.max(0.0001, p));
  return Math.log(q / (1 - q));
}

export function clampTo(p: number, [lo, hi]: [number, number]): number {
  return Math.min(hi, Math.max(lo, p));
}

/** Модель из trace; null для старых записей без слагаемых (там только вклады parts). */
export function confModel(trace: StepTrace[] | null | undefined, confidence: number): ConfModel | null {
  return confModelFrom(trace?.find((s) => s.step === "confidence")?.changes, confidence);
}

/** То же по changes шага confidence. */
export function confModelFrom(ch: unknown, confidence: number): ConfModel | null {
  if (!isRecord(ch) || typeof ch.intercept !== "number" || !Array.isArray(ch.terms)) return null;
  const terms: ConfTerm[] = ch.terms.flatMap((t: unknown) =>
    isRecord(t) &&
    typeof t.key === "string" &&
    typeof t.x === "number" &&
    typeof t.w === "number" &&
    typeof t.points === "number"
      ? [{ key: t.key, x: t.x, w: t.w, points: t.points }]
      : [],
  );
  const b = Array.isArray(ch.bounds) ? ch.bounds : [];
  const bounds: [number, number] = [
    typeof b[0] === "number" ? b[0] : 0.02,
    typeof b[1] === "number" ? b[1] : 0.99,
  ];
  const z = typeof ch.logit === "number" ? ch.logit : ch.intercept + terms.reduce((a, t) => a + t.points, 0);
  return { intercept: ch.intercept, terms, logit: z, p: confidence, raw: sigmoid(z), bounds };
}
