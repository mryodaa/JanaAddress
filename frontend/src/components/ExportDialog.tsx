import { useEffect, useState } from "react";
import { EXPORT_FIELDS, type ExportField, type FieldName, type ListParams, api } from "../api/client";
import { useI18n } from "../i18n";
import { IconDownload } from "./icons";
import { FieldDot, Modal, Segmented, buttonClass } from "./ui";

type Scope = "all" | "current";
type Format = "json" | "csv";

// выбор полей и формата помним в браузере: экспорт повторяют с теми же настройками
const PREFS_KEY = "jana.export";

interface Prefs {
  fields: ExportField[];
  format: Format;
  sources: boolean;
}

function readPrefs(): Prefs {
  const all = { fields: [...EXPORT_FIELDS], format: "json" as Format, sources: false };
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null") as Partial<Prefs> | null;
    if (!p) return all;
    const fields = (p.fields ?? []).filter((f): f is ExportField =>
      (EXPORT_FIELDS as readonly string[]).includes(f),
    );
    return {
      fields: fields.length ? fields : all.fields,
      format: p.format === "csv" ? "csv" : "json",
      sources: p.sources === true,
    };
  } catch {
    return all;
  }
}

function savePrefs(p: Prefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    // не запомнили: работает до перезагрузки
  }
}

/**
 * Экспорт с выбором: весь пакет или то, что сейчас в списке (вкладка, поиск, столбец графика), какие поля
 * и в каком формате. Все поля и JSON без фильтров дают ровно ответ батча для жюри.
 */
export function ExportDialog({
  open,
  onClose,
  sid,
  total,
  current,
}: {
  open: boolean;
  onClose: () => void;
  sid: string;
  total: number;
  /** текущий список, если включён хоть один фильтр: число записей, параметры и подписи фильтров */
  current: { count: number; params: ListParams; labels: string[] } | null;
}) {
  const { t, fieldLabels } = useI18n();
  const [scope, setScope] = useState<Scope>(current ? "current" : "all");
  const [prefs, setPrefs] = useState<Prefs>(readPrefs);
  // при каждом открытии область по умолчанию: текущий список, если он отфильтрован
  useEffect(() => {
    if (open) setScope(current ? "current" : "all");
  }, [open, current]);
  useEffect(() => savePrefs(prefs), [prefs]);

  const useCurrent = scope === "current" && current != null;
  const count = useCurrent ? current.count : total;
  const allFields = prefs.fields.length === EXPORT_FIELDS.length;
  const href = api.exportUrl(sid, {
    params: useCurrent ? current.params : undefined,
    fields: allFields ? null : prefs.fields,
    format: prefs.format,
    sources: prefs.sources,
  });
  const toggle = (f: ExportField) =>
    setPrefs((p) => ({
      ...p,
      fields: p.fields.includes(f)
        ? p.fields.filter((x) => x !== f)
        : EXPORT_FIELDS.filter((x) => x === f || p.fields.includes(x)),
    }));
  const label = (f: ExportField) => (f === "confidence" ? "confidence" : fieldLabels[f as FieldName]);

  return (
    <Modal open={open} onClose={onClose} title={t("exportTitle")}>
      <div className="grid gap-5 text-sm">
        <fieldset className="grid gap-2">
          <legend className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            {t("exportScope")}
          </legend>
          <ScopeOption
            checked={!useCurrent}
            onChange={() => setScope("all")}
            title={t("exportAll")}
            count={total}
          />
          <ScopeOption
            checked={useCurrent}
            onChange={() => setScope("current")}
            disabled={!current}
            title={t("exportCurrent")}
            count={current?.count}
            note={current ? current.labels.join(" · ") : t("exportCurrentNone")}
          />
        </fieldset>

        <fieldset>
          <legend className="mb-1.5 flex w-full items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            {t("exportFields")}
            <span className="flex gap-2 normal-case tracking-normal">
              <button
                type="button"
                onClick={() => setPrefs((p) => ({ ...p, fields: [...EXPORT_FIELDS] }))}
                className="rounded font-medium text-brand-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30"
              >
                {t("exportSelectAll")}
              </button>
              <button
                type="button"
                onClick={() => setPrefs((p) => ({ ...p, fields: [] }))}
                className="rounded font-medium text-ink-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30"
              >
                {t("exportSelectNone")}
              </button>
            </span>
          </legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {EXPORT_FIELDS.map((f) => (
              <label
                key={f}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-canvas"
              >
                <input
                  type="checkbox"
                  checked={prefs.fields.includes(f)}
                  onChange={() => toggle(f)}
                  className="h-4 w-4 accent-brand-700"
                />
                {f !== "confidence" && <FieldDot field={f as FieldName} />}
                <span className="truncate">{label(f)}</span>
              </label>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-ink-3">{t("exportFieldsAlways")}</p>
        </fieldset>

        <fieldset className="grid gap-2">
          <legend className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            {t("exportFormat")}
          </legend>
          <Segmented<Format>
            size="sm"
            ariaLabel={t("exportFormat")}
            value={prefs.format}
            onChange={(format) => setPrefs((p) => ({ ...p, format }))}
            options={[
              { value: "json", label: "JSON" },
              { value: "csv", label: "CSV" },
            ]}
          />
          <p className="text-xs text-ink-3">
            {prefs.format === "json" ? t("exportJsonHint") : t("exportCsvHint")}
          </p>
          <label className="mt-1 flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={prefs.sources}
              onChange={(e) => setPrefs((p) => ({ ...p, sources: e.target.checked }))}
              className="h-4 w-4 accent-brand-700"
            />
            <span>{t("exportSources")}</span>
          </label>
        </fieldset>

        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-4">
          <span className="text-xs tabular-nums text-ink-2">
            {t("exportSummary", { n: count, k: 2 + prefs.fields.length })}
          </span>
          <a
            href={count ? href : undefined}
            download
            aria-disabled={!count}
            onClick={() => window.setTimeout(onClose, 0)}
            className={buttonClass("primary")}
          >
            <IconDownload />
            {t("exportDownload")}
          </a>
        </div>
      </div>
    </Modal>
  );
}

function ScopeOption({
  checked,
  onChange,
  title,
  count,
  note,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  title: string;
  count?: number;
  note?: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
        disabled
          ? "cursor-not-allowed border-line-soft opacity-60"
          : checked
            ? "cursor-pointer border-brand-600 bg-brand-50"
            : "cursor-pointer border-line hover:border-brand-200"
      }`}
    >
      <input
        type="radio"
        name="export-scope"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="mt-0.5 h-4 w-4 accent-brand-700"
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="font-medium text-ink">{title}</span>
          {count != null && <span className="text-xs tabular-nums text-ink-2">{count}</span>}
        </span>
        {note && <span className="mt-0.5 block truncate text-xs text-ink-3">{note}</span>}
      </span>
    </label>
  );
}
