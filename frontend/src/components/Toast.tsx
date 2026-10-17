import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { IconAlert, IconCheck } from "./icons";

type Tone = "ok" | "error";
/** Кнопка в уведомлении: «Отменить» после подтверждения или откладывания записи. */
export interface ToastAction {
  label: string;
  run: () => void;
}
interface Item {
  id: number;
  text: string;
  tone: Tone;
  leaving: boolean;
  action?: ToastAction;
}
type Push = (text: string, tone?: Tone, action?: ToastAction) => void;

const ToastContext = createContext<Push | null>(null);

const SHOW_MS = 2500;
// с кнопкой дольше: человеку нужно успеть передумать и нажать
const ACTION_MS = 6000;
const LEAVE_MS = 180;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, leaving: true } : x)));
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), LEAVE_MS);
  }, []);

  const push = useCallback<Push>(
    (text, toneArg, action) => {
      const tone = toneArg ?? "ok";
      const id = ++seq.current;
      // не больше трёх сразу: при быстром сохранении подряд старые уходят. Отменить можно только последнее
      // действие: отмена старого поверх более новых привела бы запись в неожиданное состояние
      setItems((xs) => [
        ...xs.slice(-2).map((x) => (action ? { ...x, action: undefined } : x)),
        { id, text, tone, leaving: false, action },
      ]);
      setTimeout(() => dismiss(id), action ? ACTION_MS : SHOW_MS);
    },
    [dismiss],
  );

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
            role={x.tone === "error" ? "alert" : "status"}
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
            {x.action && (
              <button
                type="button"
                onClick={() => {
                  x.action?.run();
                  dismiss(x.id);
                }}
                className="-my-1 ml-1 rounded-lg px-2 py-1 font-semibold text-brand-300 transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
              >
                {x.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): Push {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
