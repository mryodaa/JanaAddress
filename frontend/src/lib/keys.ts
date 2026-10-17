import { useEffect, useRef } from "react";

/** Открытые модальные окна: под диалогом горячие клавиши страницы (J/K, Ctrl+Enter) не работают. */
let modals = 0;

export function modalOpened(): () => void {
  modals += 1;
  let closed = false;
  return () => {
    if (!closed) {
      closed = true;
      modals -= 1;
    }
  };
}

export function isModalOpen(): boolean {
  return modals > 0;
}

/**
 * Слушатель keydown на window, подписанный один раз: обработчик берётся из ref, поэтому перерисовки
 * (опрос прогресса раз в 500 мс, ввод в поиск) не переподписывают его и не меняют порядок слушателей.
 */
export function useWindowKey(handler: (e: KeyboardEvent) => void, enabled = true): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    const on = (e: KeyboardEvent) => ref.current(e);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [enabled]);
}

/** Фокус в поле ввода: буквенные горячие клавиши не перехватываем. */
export function typingIn(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}
