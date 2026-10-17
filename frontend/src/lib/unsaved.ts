import { useEffect } from "react";

/**
 * Несохранённый черновик редактора, видимый всему приложению: шапка и «Новый файл» уводят со страницы пакета,
 * и это не должно молча терять правки. Внутри пакета переходы спрашивает сам редактор (баннер), здесь только
 * уход за пределы пакета и закрытие вкладки браузера.
 */
let dirty = false;

export function setUnsaved(v: boolean): void {
  dirty = v;
}

export function hasUnsaved(): boolean {
  return dirty;
}

/** true: можно уходить (черновика нет или человек согласился его потерять). */
export function confirmLeave(message: string): boolean {
  if (!dirty) return true;
  const ok = window.confirm(message);
  if (ok) dirty = false;
  return ok;
}

/** Предупреждение браузера при закрытии или перезагрузке вкладки с черновиком. */
export function useBeforeUnload(): void {
  useEffect(() => {
    const on = (e: BeforeUnloadEvent) => {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", on);
    return () => window.removeEventListener("beforeunload", on);
  }, []);
}
