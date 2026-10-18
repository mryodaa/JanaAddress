import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { modalOpened, useWindowKey } from "../lib/keys";
import { THRESHOLD_MAX, THRESHOLD_MIN, setThreshold, useThresholdSetting } from "../lib/settings";
import { IconSettings } from "./icons";
import { IconButton } from "./ui";

const pct = (v: number) => Math.round(v * 100);

/** Шестерёнка в шапке: панель с порогом неуверенности (ползунок), значение помнится в браузере. */
export function Settings({ fallback }: { fallback: number }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();
  const chosen = useThresholdSetting();
  const value = chosen ?? fallback;

  // пока панель открыта, горячие клавиши страницы молчат; клик мимо и Esc закрывают
  useEffect(() => {
    if (!open) return;
    const release = modalOpened();
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => {
      release();
      document.removeEventListener("pointerdown", away);
    };
  }, [open]);
  useWindowKey((e) => {
    if (e.key === "Escape") setOpen(false);
  }, open);

  return (
    <div ref={box} className="relative">
      <IconButton
        label={t("settings")}
        variant="neutral"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className={open ? "border-brand-200 bg-brand-50 text-brand-700" : ""}
      >
        <IconSettings className="h-4 w-4" />
      </IconButton>
      {open && (
        <div
          id={id}
          // biome-ignore lint/a11y/useSemanticElements: немодальная панель у кнопки, <dialog> здесь не нужен
          role="dialog"
          aria-label={t("settings")}
          className="absolute top-full right-0 z-40 mt-2 w-[min(20rem,calc(100vw-2rem))] animate-scale-in rounded-2xl bg-white p-4 shadow-lg shadow-ink/10 ring-1 ring-line"
        >
          <div className="text-sm font-semibold text-ink">{t("settings")}</div>
          <label className="mt-3 block">
            <span className="flex items-baseline justify-between gap-2 text-xs text-ink-2">
              {t("thresholdLabel")}
              <span className="text-lg font-semibold tabular-nums text-ink">{pct(value)}%</span>
            </span>
            <input
              type="range"
              min={pct(THRESHOLD_MIN)}
              max={pct(THRESHOLD_MAX)}
              step={1}
              value={pct(value)}
              onChange={(e) => setThreshold(Number(e.target.value) / 100)}
              className="mt-2 w-full cursor-pointer accent-brand-600"
            />
            <span className="mt-0.5 flex justify-between text-[11px] tabular-nums text-ink-3">
              <span>{pct(THRESHOLD_MIN)}%</span>
              <span>{pct(THRESHOLD_MAX)}%</span>
            </span>
          </label>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">{t("thresholdHint")}</p>
          <div className="mt-3 flex items-center justify-between gap-2 border-t border-line-soft pt-3 text-xs">
            <span className="text-ink-3">{t("thresholdDefault", { pct: pct(fallback) })}</span>
            {chosen != null && pct(chosen) !== pct(fallback) && (
              <button
                type="button"
                onClick={() => setThreshold(null)}
                className="rounded-lg px-2 py-1 font-semibold text-brand-700 transition hover:bg-brand-50"
              >
                {t("thresholdReset")}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
