import { ApiError } from "../api/client";
import type { Language, TranslationKey } from "../i18n/types";

type T = (key: TranslationKey, params?: Record<string, string | number>) => string;

const BY_STATUS: Partial<Record<number, TranslationKey>> = {
  404: "err404",
  409: "err409",
  413: "err413",
  422: "err422",
};

/**
 * Текст ошибки на языке интерфейса: по статусу ответа. Сервер пишет detail по-русски, поэтому он добавляется
 * пояснением только в русском интерфейсе.
 */
export function errorText(e: unknown, t: T, language: Language): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e);
  if (e.status === 0) return t("serviceUnavailable");
  const key = BY_STATUS[e.status];
  const base = key ? t(key) : t("errServer", { status: e.status });
  return language === "ru" && e.message && e.message !== base ? `${base}: ${e.message}` : base;
}
