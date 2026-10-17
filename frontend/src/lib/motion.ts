import { useEffect, useRef, useState } from "react";

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Число «докручивается» к новому значению: от предыдущего, а не от нуля, чтобы опрос прогресса не мигал. */
export function useCountUp(target: number, ms = 600): number {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = from.current;
    if (start === target || prefersReducedMotion()) {
      from.current = target;
      setV(target);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      const eased = 1 - (1 - k) ** 3;
      const cur = start + (target - start) * eased;
      from.current = cur;
      setV(cur);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

/**
 * Держит элемент смонтированным на время анимации ухода.
 * mounted: рисовать ли вообще; leaving: включить класс исчезновения.
 */
export function usePresence(open: boolean, leaveMs = 200): { mounted: boolean; leaving: boolean } {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const t = setTimeout(() => setMounted(false), prefersReducedMotion() ? 0 : leaveMs);
    return () => clearTimeout(t);
  }, [open, leaveMs]);
  return { mounted: mounted || open, leaving: !open && mounted };
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Медиазапрос как состояние: редактор на узком экране становится выезжающей панелью. */
export function useMedia(query: string): boolean {
  const [m, setM] = useState(() => {
    try {
      return window.matchMedia(query).matches;
    } catch {
      return false;
    }
  });
  useEffect(() => {
    let mq: MediaQueryList;
    try {
      mq = window.matchMedia(query);
    } catch {
      return;
    }
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return m;
}
