import {
  type ButtonHTMLAttributes,
  type ReactNode,
  type RefObject,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type { FieldExplain, FieldName } from "../api/client";
import { useI18n } from "../i18n";
import { FIELD_COLORS, highlight, visible } from "../lib/fields";
import { modalOpened } from "../lib/keys";
import { usePresence } from "../lib/motion";
import { IconSearch, IconX, Spinner } from "./icons";

export type ConfidenceTone = "high" | "ok" | "low" | "bad";

/** Ступень уверенности относительно порога: одна шкала для значка, отчёта демо и подсказок. */
export function confidenceTone(value: number, threshold: number): ConfidenceTone {
  if (value >= Math.max(threshold, 0.8)) return "high";
  if (value >= threshold) return "ok";
  if (value >= threshold / 2) return "low";
  return "bad";
}

const BADGE_TONE: Record<ConfidenceTone, string> = {
  high: "bg-brand-50 text-brand-800 ring-brand-200",
  ok: "bg-lime-50 text-lime-800 ring-lime-200",
  low: "bg-warn-50 text-warn-800 ring-warn/40",
  bad: "bg-danger-50 text-danger ring-danger/25",
};

export function ConfidenceBadge({ value, threshold }: { value: number; threshold: number }) {
  const pct = Math.round(value * 100);
  const tone = BADGE_TONE[confidenceTone(value, threshold)];
  return (
    <span
      className={`inline-flex min-w-12 justify-center rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ring-1 ring-inset transition-colors ${tone}`}
    >
      {pct}%
    </span>
  );
}

export function Highlighted({
  raw,
  fields,
  onPick,
  hover,
  onHover,
}: {
  raw: string;
  fields: Partial<Record<string, FieldExplain>>;
  /** клик по куску строки: фокус на поле в редакторе */
  onPick?: (f: FieldName) => void;
  hover?: FieldName | null;
  onHover?: (f: FieldName | null) => void;
}) {
  const { fieldLabels } = useI18n();
  return (
    <span className="whitespace-pre-wrap break-words">
      {highlight(raw, fields).map((p, i) =>
        p.field ? (
          // biome-ignore lint/a11y/useKeyWithClickEvents: дубль для мыши, с клавиатуры поля доступны напрямую
          <mark
            // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
            key={i}
            title={fieldLabels[p.field] ?? p.field}
            onClick={onPick ? () => p.field && onPick(p.field) : undefined}
            onMouseEnter={onHover ? () => onHover(p.field) : undefined}
            onMouseLeave={onHover ? () => onHover(null) : undefined}
            className={`rounded px-0.5 ring-1 ring-inset transition-[box-shadow,filter] duration-150 ${FIELD_COLORS[p.field].mark} ${
              onPick ? "cursor-pointer hover:brightness-95" : ""
            } ${hover === p.field ? "shadow-[0_0_0_2px_currentColor]" : ""}`}
          >
            {visible(p.text)}
          </mark>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: куски строки не переставляются
          <span key={i} className="text-ink-3">
            {visible(p.text)}
          </span>
        ),
      )}
    </span>
  );
}

export function FieldDot({ field, className = "" }: { field: FieldName; className?: string }) {
  return (
    <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${FIELD_COLORS[field].dot} ${className}`} />
  );
}

export function Legend() {
  const { fieldLabels } = useI18n();
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
      {(Object.keys(FIELD_COLORS) as FieldName[]).map((f) => (
        <span key={f} className="inline-flex items-center gap-1.5">
          <FieldDot field={f} />
          {fieldLabels[f] ?? f}
        </span>
      ))}
    </div>
  );
}

export function SourceTag({ source }: { source: string | null | undefined }) {
  const { t, sourceLabel } = useI18n();
  const label = sourceLabel(source);
  if (!label) return null;
  const manual = source === "manual";
  return (
    <span
      className={`ml-1 inline-flex rounded-md px-1.5 py-px align-middle text-[10px] font-semibold uppercase tracking-wide ${
        manual ? "bg-ink text-white" : "bg-brand-50 text-brand-800 ring-1 ring-inset ring-brand-200"
      }`}
      title={manual ? t("sourceManualTooltip") : `${label}: ${t("sourceRefTooltip")}`}
    >
      {manual ? t("sourceManual") : t("sourceRef")}
    </span>
  );
}

/** Куски строки, которые не стали ни полем, ни служебным словом. */
export function Unparsed({
  items,
  className = "",
  withLabel = true,
}: { items: string[] | null | undefined; className?: string; withLabel?: boolean }) {
  const { t } = useI18n();
  if (!items?.length) return null;
  return (
    <div className={`flex flex-wrap items-center gap-1.5 text-xs text-ink-2 ${className}`}>
      {withLabel && <span>{t("unparsed")}</span>}
      {/* номер в ключе: один и тот же кусок может встретиться в строке дважды */}
      {items.map((u, i) => (
        <span key={`${i}:${u}`} className="rounded-md bg-danger-50 px-1.5 py-px font-mono text-danger">
          {u}
        </span>
      ))}
    </div>
  );
}

export function Card({
  title,
  children,
  className = "",
}: { title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-[20px] border border-line bg-white p-4 sm:p-5 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold text-ink">{title}</h2>}
      {children}
    </section>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex min-w-5 justify-center rounded-md border border-line bg-white px-1.5 py-px font-mono text-[11px] text-ink-2 shadow-[0_1px_0_var(--color-line)]">
      {children}
    </kbd>
  );
}

type Variant = "primary" | "secondary" | "neutral" | "ghost" | "danger";

const VARIANT: Record<Variant, string> = {
  // brand-700: белый текст 5.9:1 (на brand-600 было 4.4:1, ниже AA)
  primary:
    "bg-brand-700 text-white hover:bg-brand-800 hover:-translate-y-px hover:shadow-md hover:shadow-brand-700/25",
  secondary: "border border-brand-600 bg-white text-brand-700 hover:bg-brand-50",
  neutral: "border border-line bg-white text-ink hover:border-brand-200 hover:bg-brand-50",
  ghost: "text-ink-2 hover:bg-canvas hover:text-ink",
  danger: "text-danger hover:bg-danger-50",
};

/** Классы кнопки отдельно: ими же оформляется ссылка-скачивание (кнопка внутри <a> недопустима). */
export function buttonClass(variant: Variant = "neutral", size: "sm" | "md" = "md"): string {
  const sz = size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm";
  return `relative inline-flex shrink-0 select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-xl font-semibold transition duration-150 active:scale-[.98] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-600/20 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 ${sz} ${VARIANT[variant]}`;
}

export function Button({
  children,
  variant = "neutral",
  size = "md",
  icon,
  loading = false,
  className = "",
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  icon?: ReactNode;
  loading?: boolean;
}) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`${buttonClass(variant, size)} ${className}`}
    >
      {/* спиннер встаёт на место иконки (или поверх текста), ширина кнопки не прыгает */}
      {icon ? loading ? <Spinner /> : icon : null}
      <span className={loading && !icon ? "opacity-0" : undefined}>{children}</span>
      {loading && !icon && (
        <span className="absolute inset-0 grid place-items-center">
          <Spinner />
        </span>
      )}
    </button>
  );
}

export function IconButton({
  label,
  children,
  variant = "ghost",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; variant?: "ghost" | "neutral" }) {
  const v =
    variant === "neutral"
      ? "border border-line bg-white text-ink-2 hover:border-brand-200 hover:bg-brand-50 hover:text-brand-700"
      : "text-ink-2 hover:bg-canvas hover:text-ink";
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      {...rest}
      className={`inline-grid h-8 w-8 shrink-0 place-items-center rounded-xl transition duration-150 active:scale-90 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-600/20 disabled:pointer-events-none disabled:opacity-40 ${v} ${className}`}
    >
      {children}
    </button>
  );
}

export interface SegOption<T extends string> {
  value: T;
  label: ReactNode;
  badge?: number | null;
  badgeTone?: "warn" | "brand";
}

/** Вкладки-пилюли Jana Post: активная тёмная, ползунок переезжает между вариантами. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  ariaLabel,
  className = "",
}: {
  options: SegOption<T>[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
  ariaLabel?: string;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  const [animate, setAnimate] = useState(false);

  // замер активной кнопки. Следим и за каждой кнопкой: счётчик у соседней сдвигает активную, а размер
  // всего переключателя при упоре в max-w-full не меняется. Шрифт догружается позже первого замера
  const labels = options.map((o) => `${o.value}:${o.label}:${o.badge ?? ""}`).join("|");
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || !labels) return;
    const measure = () => {
      const btn = el.querySelector<HTMLElement>(`[data-seg="${CSS.escape(value)}"]`);
      if (btn?.offsetWidth) setPill({ x: btn.offsetLeft, w: btn.offsetWidth });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    for (const b of el.querySelectorAll<HTMLElement>("[data-seg]")) ro.observe(b);
    void document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [value, labels]);
  // первый замер без анимации, иначе ползунок едет из угла
  useEffect(() => {
    if (pill && !animate) {
      const r = requestAnimationFrame(() => setAnimate(true));
      return () => cancelAnimationFrame(r);
    }
  }, [pill, animate]);

  const pad = size === "sm" ? "h-7 px-3 text-xs" : "h-8 px-4 text-sm";
  // стрелки переключают вариант, как в обычном tablist; фокус уходит на выбранную кнопку
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const i = options.findIndex((o) => o.value === value);
    const next = options[(i + step + options.length) % options.length];
    if (!next) return;
    onChange(next.value);
    box.current?.querySelector<HTMLElement>(`[data-seg="${CSS.escape(next.value)}"]`)?.focus();
  };
  return (
    <div
      ref={box}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={`relative isolate inline-flex max-w-full items-center overflow-x-auto rounded-full border border-line bg-white p-0.5 [scrollbar-width:none] ${className}`}
    >
      {pill && (
        <span
          aria-hidden="true"
          className={`absolute top-0.5 bottom-0.5 left-0 rounded-full bg-ink ${animate ? "transition-[transform,width] duration-300 ease-[var(--ease-out-soft)]" : ""}`}
          style={{ width: pill.w, transform: `translateX(${pill.x}px)` }}
        />
      )}
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            data-seg={o.value}
            onClick={() => onChange(o.value)}
            className={`relative z-10 inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-600/20 ${pad} ${
              active ? "text-white" : "text-ink hover:text-brand-700"
            } ${!pill && active ? "bg-ink" : ""}`}
          >
            {o.label}
            {o.badge != null && o.badge > 0 && (
              <span
                className={`rounded-full px-1.5 text-[10px] font-semibold tabular-nums leading-4 transition-colors ${
                  active
                    ? "bg-white/20 text-white"
                    : o.badgeTone === "brand"
                      ? "bg-brand-50 text-brand-800"
                      : "bg-warn-50 text-warn-800"
                }`}
              >
                {o.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  inputRef,
  id,
  icon = true,
  trailing,
  size = "md",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  inputRef?: RefObject<HTMLInputElement>;
  id?: string;
  icon?: boolean;
  trailing?: ReactNode;
  size?: "md" | "lg";
  className?: string;
}) {
  const { t } = useI18n();
  const h = size === "lg" ? "h-12 text-base" : "h-10 text-sm";
  return (
    <div className={`group relative flex items-center ${className}`}>
      {icon && (
        <IconSearch className="pointer-events-none absolute left-3 h-4 w-4 text-ink-3 transition-colors group-focus-within:text-brand-600" />
      )}
      <input
        ref={inputRef}
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.stopPropagation();
            onChange("");
          }
        }}
        placeholder={placeholder}
        className={`w-full min-w-0 rounded-xl border border-line bg-white ${icon ? "pl-9" : "pl-3"} pr-16 text-ink transition placeholder:text-ink-3 hover:border-brand-200 focus:border-brand-600 focus:outline-none focus:ring-4 focus:ring-brand-600/15 ${h}`}
      />
      <div className="absolute right-2 flex items-center gap-1">
        {value ? (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label={t("clear")}
            title={t("clear")}
            className="grid h-6 w-6 animate-scale-in place-items-center rounded-lg text-ink-3 hover:bg-canvas hover:text-ink"
          >
            <IconX className="h-3.5 w-3.5" />
          </button>
        ) : (
          trailing
        )}
      </div>
    </div>
  );
}

export function ProgressBar({ value, className = "h-1.5" }: { value: number; className?: string }) {
  return (
    <div className={`overflow-hidden rounded-full bg-line-soft ${className}`}>
      <div
        className="h-full rounded-full bg-brand-600 transition-[width] duration-500 ease-[var(--ease-out-soft)]"
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      />
    </div>
  );
}

/** Тонкая бегущая полоска «идёт запрос», без сдвига вёрстки. */
export function BusyBar({ active, className = "" }: { active: boolean; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none h-0.5 overflow-hidden transition-opacity duration-300 ${active ? "opacity-100" : "opacity-0"} ${className}`}
    >
      <div className="h-full w-1/3 origin-left animate-indeterminate rounded-full bg-brand-600" />
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Фокус внутри панели, пока она открыта: Tab и Shift+Tab ходят по кругу, при закрытии фокус возвращается
 * туда, откуда панель открыли.
 */
export function useFocusTrap(ref: RefObject<HTMLElement>, enabled: boolean): void {
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!el.contains(document.activeElement)) el.focus({ preventScroll: true });
    const on = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (n) => n.getClientRects().length > 0,
      );
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) {
        e.preventDefault();
        el.focus();
        return;
      }
      const at = document.activeElement;
      if (e.shiftKey && (at === head || at === el || !el.contains(at))) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && (at === tail || !el.contains(at))) {
        e.preventDefault();
        head.focus();
      }
    };
    document.addEventListener("keydown", on, true);
    return () => {
      document.removeEventListener("keydown", on, true);
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [enabled, ref]);
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  const { t } = useI18n();
  const { mounted, leaving } = usePresence(open, 160);
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // обработчик через ref: родитель передаёт новую стрелку на каждом рендере (опрос раз в 500 мс),
  // и эффект не должен из-за этого перезапускаться и снова дёргать фокус
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const done = modalOpened();
    const on = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
      }
    };
    window.addEventListener("keydown", on, true);
    return () => {
      window.removeEventListener("keydown", on, true);
      done();
    };
  }, [open]);
  useFocusTrap(panel, open && mounted);
  if (!mounted) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <button
        type="button"
        aria-label={t("closeTooltip")}
        tabIndex={-1}
        onClick={onClose}
        className={`absolute inset-0 cursor-default bg-ink/30 backdrop-blur-[2px] ${leaving ? "animate-fade-out" : "animate-fade-in"}`}
      />
      <div
        ref={panel}
        // biome-ignore lint/a11y/useSemanticElements: <dialog> мешает анимации ухода, хватает role
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`relative max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-[20px] bg-white p-5 shadow-2xl shadow-ink/20 focus:outline-none ${leaving ? "animate-scale-out" : "animate-scale-in"}`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          <IconButton label={t("closeTooltip")} onClick={onClose}>
            <IconX />
          </IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Свёрнутое содержимое не должно ловить Tab: атрибут inert ставим вручную (React 18 его не знает). */
export function useInert(ref: RefObject<HTMLElement>, inert: boolean): void {
  useEffect(() => {
    ref.current?.toggleAttribute("inert", inert);
  }, [ref, inert]);
}

/** Аккордеон: заголовок-кнопка и плавное раскрытие по высоте. */
export function Disclosure({
  title,
  open,
  onToggle,
  children,
  extra,
}: { title: ReactNode; open: boolean; onToggle: () => void; children: ReactNode; extra?: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  useInert(body, !open);
  return (
    <div className="rounded-2xl border border-line">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-2xl px-3.5 py-2.5 text-left text-sm font-semibold text-ink transition-colors hover:bg-canvas"
      >
        <span className="inline-flex items-center gap-2">{title}</span>
        <span className="inline-flex items-center gap-2 text-xs font-normal text-ink-3">
          {extra}
          <svg
            viewBox="0 0 24 24"
            className={`h-4 w-4 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      <div ref={body} className="reveal" data-open={open}>
        <div>
          <div className="px-3.5 pb-3.5">{children}</div>
        </div>
      </div>
    </div>
  );
}

const HINT_W_REM = 18;

/** Ширина подсказки в px: 18rem, в полноэкранном демо корневой шрифт больше. */
function hintWidth(): number {
  return HINT_W_REM * (Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16);
}

/** Значок «?» с пояснением по наведению, фокусу или тапу. Пояснение в портале: не обрезается прокруткой. */
export function Hint({
  text,
  label,
  className = "",
}: { text: ReactNode; label: string; className?: string }) {
  const btn = useRef<HTMLButtonElement>(null);
  const id = useId();
  const [pos, setPos] = useState<{ x: number; y: number; above: boolean; w: number } | null>(null);
  const show = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const w = hintWidth();
    const x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    const above = r.top > 240;
    setPos({ x, y: above ? r.top - 8 : r.bottom + 8, above, w });
  };
  const hide = () => setPos(null);
  const open = pos !== null;
  // прокрутка страницы или сцены уводит значок из-под подсказки
  useEffect(() => {
    if (!open) return;
    const off = () => setPos(null);
    window.addEventListener("scroll", off, true);
    window.addEventListener("resize", off);
    return () => {
      window.removeEventListener("scroll", off, true);
      window.removeEventListener("resize", off);
    };
  }, [open]);
  return (
    <>
      <button
        ref={btn}
        type="button"
        aria-label={label}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          e.stopPropagation();
          if (pos) hide();
          else show();
        }}
        className={`inline-grid h-4 w-4 shrink-0 cursor-help place-items-center rounded-full border border-line bg-white align-middle text-[10px] font-semibold normal-case leading-none tracking-normal text-ink-3 transition-colors hover:border-brand-600 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30 ${className}`}
      >
        ?
      </button>
      {pos &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            className="pointer-events-none fixed z-50 animate-fade-in rounded-xl bg-white px-3.5 py-2.5 text-left text-xs leading-relaxed text-ink-2 shadow-lg shadow-ink/10 ring-1 ring-line"
            style={{
              left: pos.x,
              top: pos.y,
              width: pos.w,
              transform: pos.above ? "translateY(-100%)" : undefined,
            }}
          >
            {text}
          </div>,
          // в полноэкранном режиме видно только его содержимое: подсказка рисуется внутри
          document.fullscreenElement ?? document.body,
        )}
    </>
  );
}
