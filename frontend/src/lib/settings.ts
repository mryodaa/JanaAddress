import { useSyncExternalStore } from "react";

// порог неуверенности из настроек: у каждого зрителя свой, помним в браузере; null = порог сервиса по умолчанию
const KEY = "jana.threshold";
export const THRESHOLD_MIN = 0.5;
export const THRESHOLD_MAX = 0.99;

const listeners = new Set<() => void>();

function read(): number | null {
  try {
    const v = Number.parseFloat(localStorage.getItem(KEY) ?? "");
    return Number.isFinite(v) && v >= THRESHOLD_MIN && v <= THRESHOLD_MAX ? v : null;
  } catch {
    return null;
  }
}

let current = read();

export function setThreshold(v: number | null): void {
  current = v;
  try {
    if (v == null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(v));
  } catch {
    // хранилища нет (приватный режим): настройка живёт до перезагрузки
  }
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Порог, выбранный в настройках, или null, если оставлен порог сервиса. */
export function useThresholdSetting(): number | null {
  return useSyncExternalStore(subscribe, () => current);
}
