import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { modalOpened, useWindowKey } from "../lib/keys";
import { IconBook, IconChevronDown, IconCode, IconDatabase, IconExternalLink, IconFile } from "./icons";

/** Кнопка и меню перехода в документацию: Swagger UI, ReDoc, OpenAPI JSON. */
export function DocsMenu() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();

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
    <div ref={box} className="relative inline-flex items-center">
      {/* Сплит-кнопка: прямой переход в Swagger UI по клику на основную часть + шеврон для открытия всего меню */}
      <div
        className={`inline-flex items-center rounded-xl border border-line bg-white shadow-xs transition duration-150 ${
          open ? "border-brand-200 ring-2 ring-brand-600/15" : "hover:border-brand-200"
        }`}
      >
        <a
          href="/docs"
          target="_blank"
          rel="noreferrer"
          title={`${t("docsSwaggerTitle")} (/docs)`}
          aria-label={`${t("docsSwaggerTitle")} (/docs)`}
          className="inline-flex h-8 items-center gap-1.5 rounded-l-xl px-2.5 text-xs font-semibold text-ink transition hover:bg-brand-50 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30"
        >
          <IconBook className="h-3.5 w-3.5 text-brand-600" />
          <span className="hidden sm:inline">Swagger</span>
          <IconExternalLink className="h-3 w-3 text-ink-3 transition-colors group-hover:text-brand-700" />
        </a>
        <span className="h-4 w-px bg-line" aria-hidden="true" />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          aria-label={t("docsMenuTitle")}
          title={t("docsMenuTitle")}
          onClick={() => setOpen((v) => !v)}
          className={`inline-grid h-8 w-7 place-items-center rounded-r-xl text-ink-2 transition hover:bg-brand-50 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30 ${
            open ? "bg-brand-50 text-brand-700" : ""
          }`}
        >
          <IconChevronDown
            className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {open && (
        <div
          id={id}
          role="menu"
          aria-label={t("docsMenuTitle")}
          className="absolute top-full right-0 z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] animate-scale-in rounded-2xl bg-white p-2 shadow-lg shadow-ink/10 ring-1 ring-line"
        >
          <div className="flex items-center justify-between border-b border-line-soft px-3 py-2">
            <span className="text-xs font-semibold text-ink">{t("docsMenuTitle")}</span>
            <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">
              OpenAPI
            </span>
          </div>

          <div className="mt-1 space-y-1">
            {/* Swagger UI */}
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="group flex items-start gap-3 rounded-xl p-2.5 transition-colors hover:bg-brand-50/70"
            >
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-100 text-brand-700 transition-transform duration-200 group-hover:scale-105">
                <IconCode className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-ink group-hover:text-brand-800">
                    {t("docsSwaggerTitle")}
                  </span>
                  <span className="rounded bg-brand-50 px-1 py-px font-mono text-[10px] font-medium text-brand-700 ring-1 ring-inset ring-brand-200">
                    /docs
                  </span>
                  <IconExternalLink className="ml-auto h-3.5 w-3.5 text-ink-3 transition-colors group-hover:text-brand-700" />
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-3">{t("docsSwaggerDesc")}</p>
              </div>
            </a>

            {/* ReDoc */}
            <a
              href="/redoc"
              target="_blank"
              rel="noreferrer"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="group flex items-start gap-3 rounded-xl p-2.5 transition-colors hover:bg-brand-50/70"
            >
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-lime-100 text-lime-800 transition-transform duration-200 group-hover:scale-105">
                <IconFile className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-ink group-hover:text-brand-800">
                    {t("docsRedocTitle")}
                  </span>
                  <span className="rounded bg-canvas px-1 py-px font-mono text-[10px] font-medium text-ink-3 ring-1 ring-line">
                    /redoc
                  </span>
                  <IconExternalLink className="ml-auto h-3.5 w-3.5 text-ink-3 transition-colors group-hover:text-brand-700" />
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-3">{t("docsRedocDesc")}</p>
              </div>
            </a>

            {/* OpenAPI JSON */}
            <a
              href="/openapi.json"
              target="_blank"
              rel="noreferrer"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="group flex items-start gap-3 rounded-xl p-2.5 transition-colors hover:bg-brand-50/70"
            >
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-canvas text-ink-2 ring-1 ring-line transition-transform duration-200 group-hover:scale-105">
                <IconDatabase className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-ink group-hover:text-brand-800">
                    {t("docsOpenApiTitle")}
                  </span>
                  <span className="rounded bg-canvas px-1 py-px font-mono text-[10px] font-medium text-ink-3 ring-1 ring-line">
                    /openapi.json
                  </span>
                  <IconExternalLink className="ml-auto h-3.5 w-3.5 text-ink-3 transition-colors group-hover:text-brand-700" />
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-3">{t("docsOpenApiDesc")}</p>
              </div>
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
