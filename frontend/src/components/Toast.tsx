import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { IconAlert, IconCheck } from "./icons";

type Tone = "ok" | "error";
interface Item {
  id: number;
  text: string;
  tone: Tone;
  leaving: boolean;
}

const ToastContext = createContext<((text: string, tone?: Tone) => void) | null>(null);

const SHOW_MS = 2500;
const LEAVE_MS = 180;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const seq = useRef(0);

  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = ++seq.current;
    // не больше трёх сразу: при быстром сохранении подряд старые уходят
    setItems((xs) => [...xs.slice(-2), { id, text, tone, leaving: false }]);
    setTimeout(() => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, leaving: true } : x))), SHOW_MS);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), SHOW_MS + LEAVE_MS);
  }, []);

  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4"
      >
        {items.map((x) => (
          <div
            key={x.id}
            className={`pointer-events-auto inline-flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-medium shadow-lg shadow-ink/10 ${
              x.tone === "ok" ? "bg-ink text-white" : "bg-danger text-white"
            } ${x.leaving ? "animate-fade-out" : "animate-fade-up"}`}
          >
            {x.tone === "ok" ? (
              <IconCheck className="h-4 w-4 animate-check-pop text-brand-300" />
            ) : (
              <IconAlert className="h-4 w-4" />
            )}
            {x.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (text: string, tone?: Tone) => void {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
