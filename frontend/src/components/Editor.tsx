import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { FIELD_NAMES, type FieldName, type RecordItem, api } from "../api/client";
import { useI18n } from "../i18n";
import type { TranslationKey } from "../i18n/types";
import { Trace, TraceSkeleton, totalMs } from "./Trace";
import { IconAlert, IconCheck, IconChevronDown, IconChevronUp, IconEraser, IconUndo, IconX } from "./icons";
import { Button, ConfidenceBadge, Disclosure, FieldDot, Highlighted, IconButton, Kbd, SourceTag } from "./ui";

type Draft = Record<FieldName, string>;

// поля сгруппированы как адрес читается глазами: где -> улица и дом -> квартира -> ориентир
const GROUPS: { key: TranslationKey; fields: FieldName[]; compact?: boolean }[] = [
  { key: "groupLocality", fields: ["province", "city", "district", "living_area"] },
  { key: "groupStreet", fields: ["street_type", "street_name", "house"] },
  { key: "groupFlat", fields: ["apartment", "entrance", "floor"], compact: true },
  { key: "groupLandmark", fields: ["landmark"] },
];

function toDraft(r: RecordItem): Draft {
  return Object.fromEntries(FIELD_NAMES.map((f) => [f, r.record[f] ?? ""])) as Draft;
}

export function Editor({
  sid,
  item,
  threshold,
  position,
  onSave,
  onPrev,
  onNext,
  onClose,
  onDirty,
  pending,
  onResolve,
  saving,
  active,
  className = "",
}: {
  sid: string;
  item: RecordItem;
  threshold: number;
  position: string;
  onSave: (fields: Partial<Record<FieldName, string | null>>) => void;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  /** есть ли несохранённый черновик: SessionView не уводит с записи молча */
  onDirty: (dirty: boolean) => void;
  /** запрошен переход, а черновик не сохранён */
  pending: boolean;
  onResolve: (action: "discard" | "cancel") => void;
  saving: boolean;
  active: boolean;
  className?: string;
}) {
  const { t, fieldLabels } = useI18n();
  const [draft, setDraft] = useState<Draft>(() => toDraft(item));
  const [showTrace, setShowTrace] = useState(false);
  const [hover, setHover] = useState<FieldName | null>(null);
  const [ping, setPing] = useState<{ f: FieldName; n: number } | null>(null);
  const inputs = useRef<Partial<Record<FieldName, HTMLInputElement | null>>>({});
  const full = useQuery({
    queryKey: ["record", sid, item.idx],
    queryFn: () => api.record(sid, item.idx),
    enabled: showTrace,
  });

  useEffect(() => {
    setDraft(toDraft(item));
  }, [item]);

  const changed = FIELD_NAMES.filter((f) => (item.record[f] ?? "") !== draft[f]);
  const dirty = changed.length > 0;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);

  function save() {
    onSave(Object.fromEntries(changed.map((f) => [f, draft[f].trim() || null])));
  }

  function pick(f: FieldName) {
    const el = inputs.current[f];
    el?.focus();
    el?.select();
    setPing((p) => ({ f, n: (p?.n ?? 0) + 1 }));
  }

  // Ctrl+Enter сохранить и дальше, Esc закрыть, Alt+↑/↓ соседние записи; на скрытой вкладке не сохранять молча
  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        save();
      } else if (e.key === "Escape") {
        if (pending) onResolve("cancel");
        else onClose();
      } else if (e.altKey && e.key === "ArrowDown") {
        e.preventDefault();
        onNext();
      } else if (e.altKey && e.key === "ArrowUp") {
        e.preventDefault();
        onPrev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function fieldInput(f: FieldName) {
    const isChanged = changed.includes(f);
    const orig = item.record[f] ?? "";
    return (
      <div key={f} className="relative rounded-xl">
        {/* кольцо-вспышка отдельным слоем: перемонтировать сам input нельзя, слетит фокус */}
        {ping?.f === f && (
          <span key={ping.n} className="pointer-events-none absolute inset-0 animate-flash-ring rounded-xl" />
        )}
        <input
          ref={(el) => {
            inputs.current[f] = el;
          }}
          value={draft[f]}
          onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
          onFocus={() => setHover(f)}
          onBlur={() => setHover((h) => (h === f ? null : h))}
          placeholder="null"
          aria-label={fieldLabels[f]}
          className={`h-9 w-full min-w-0 rounded-xl border pl-2.5 pr-14 text-sm transition duration-200 placeholder:font-mono placeholder:text-xs placeholder:text-ink-3/50 focus:outline-none focus:ring-4 ${
            isChanged
              ? "border-warn bg-warn-50 focus:border-warn focus:ring-warn/20"
              : "border-line bg-white hover:border-brand-200 focus:border-brand-600 focus:ring-brand-600/15"
          }`}
        />
        <div className="absolute inset-y-0 right-1 flex items-center gap-0.5">
          {isChanged && (
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setDraft({ ...draft, [f]: orig })}
              title={orig ? t("revertTo", { v: orig }) : t("revert")}
              aria-label={t("revert")}
              className="grid h-7 w-7 animate-scale-in place-items-center rounded-lg text-warn-800 hover:bg-warn/20"
            >
              <IconUndo className="h-3.5 w-3.5" />
            </button>
          )}
          {draft[f] && (
            <button
              type="button"
              tabIndex={-1}
              onClick={() => {
                setDraft({ ...draft, [f]: "" });
                inputs.current[f]?.focus();
              }}
              title={t("setNull")}
              aria-label={t("setNull")}
              className="grid h-7 w-7 animate-scale-in place-items-center rounded-lg text-ink-3 hover:bg-canvas hover:text-danger"
            >
              <IconEraser className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    );
  }

  function label(f: FieldName) {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-ink-2">
        <FieldDot field={f} />
        <span className="truncate">{fieldLabels[f]}</span>
        <SourceTag source={item.fields[f]?.source} />
      </span>
    );
  }

  return (
    <aside className={`flex h-full min-h-0 flex-col rounded-[20px] border border-line bg-white ${className}`}>
      <header className="flex items-center justify-between gap-2 border-b border-line-soft px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            {t("recordTitle", { idx: item.idx + 1 })}
            {item.reviewed && (
              <span className="inline-flex animate-scale-in items-center gap-1 rounded-full bg-brand-50 px-2 py-px text-[11px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">
                <IconCheck className="h-3 w-3" />
                {t("reviewedBadge")}
              </span>
            )}
          </div>
          <div className="text-xs text-ink-3">{position}</div>
        </div>
        <div className="flex items-center gap-0.5">
          <ConfidenceBadge value={item.record.confidence} threshold={threshold} />
          <IconButton label={t("prevTooltip")} onClick={onPrev} className="ml-1">
            <IconChevronUp />
          </IconButton>
          <IconButton label={t("nextTooltip")} onClick={onNext}>
            <IconChevronDown />
          </IconButton>
          <IconButton label={t("closeTooltip")} onClick={onClose}>
            <IconX />
          </IconButton>
        </div>
      </header>

      {pending && (
        <div className="flex animate-fade-up flex-wrap items-center gap-2 border-b border-warn/40 bg-warn-50 px-4 py-2.5 text-sm text-warn-800">
          <IconAlert className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1 font-medium">{t("unsavedTitle")}</span>
          <span className="ml-auto flex shrink-0 items-center gap-1">
            <Button size="sm" variant="primary" onClick={save} loading={saving}>
              {t("unsavedSave")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onResolve("discard")}>
              {t("unsavedDiscard")}
            </Button>
          </span>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div key={item.idx} className="min-h-0 flex-1 animate-fade-in overflow-auto px-4 py-3">
          <div className="mb-4 rounded-2xl bg-canvas p-3 text-sm leading-relaxed">
            <Highlighted
              raw={String(item.record.raw_address ?? "")}
              fields={item.fields}
              onPick={pick}
              hover={hover}
              onHover={setHover}
            />
            <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-ink-3">
              <span className="truncate font-mono">id: {String(item.record.id)}</span>
              <span className="shrink-0">{t("pickHint")}</span>
            </div>
          </div>

          <div className="grid gap-4">
            {GROUPS.map((g) => (
              <fieldset key={g.key} className="grid gap-2">
                <legend className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                  {t(g.key)}
                </legend>
                {g.compact ? (
                  <div className="grid grid-cols-3 gap-2">
                    {g.fields.map((f) => (
                      // biome-ignore lint/a11y/noLabelWithoutControl: input внутри fieldInput
                      <label
                        key={f}
                        className={`grid gap-1 rounded-xl transition-colors ${hover === f ? "bg-canvas" : ""}`}
                        onMouseEnter={() => setHover(f)}
                        onMouseLeave={() => setHover(null)}
                      >
                        {label(f)}
                        {fieldInput(f)}
                      </label>
                    ))}
                  </div>
                ) : (
                  g.fields.map((f) => (
                    // biome-ignore lint/a11y/noLabelWithoutControl: input внутри fieldInput
                    <label
                      key={f}
                      className={`-mx-1.5 grid grid-cols-[120px_minmax(0,1fr)] items-center gap-2 rounded-xl px-1.5 py-0.5 transition-colors ${
                        hover === f ? "bg-canvas" : ""
                      }`}
                      onMouseEnter={() => setHover(f)}
                      onMouseLeave={() => setHover(null)}
                    >
                      {label(f)}
                      {fieldInput(f)}
                    </label>
                  ))
                )}
              </fieldset>
            ))}
          </div>

          {item.unparsed.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
              <span>{t("unparsed")}</span>
              {item.unparsed.map((u) => (
                <span key={u} className="rounded-md bg-danger-50 px-1.5 py-px font-mono text-danger">
                  {u}
                </span>
              ))}
            </div>
          )}

          <div className="mt-4">
            <Disclosure
              title={t("pipelineSteps")}
              open={showTrace}
              onToggle={() => setShowTrace((v) => !v)}
              extra={full.data?.trace ? `${totalMs(full.data.trace).toFixed(1)} ${t("msUnit")}` : undefined}
            >
              {full.data?.trace ? <Trace trace={full.data.trace} /> : showTrace ? <TraceSkeleton /> : null}
            </Disclosure>
          </div>
        </div>

        <footer className="flex flex-wrap items-center gap-2 border-t border-line-soft px-4 py-3">
          <Button variant="primary" type="submit" loading={saving} icon={<IconCheck />}>
            {dirty ? t("saveAndNext") : t("confirmAndNext")}
          </Button>
          <Button variant="ghost" onClick={onNext}>
            {t("skip")}
          </Button>
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-ink-3">
            {dirty ? (
              <span className="animate-fade-in font-medium text-warn-800">
                {t("changedCount", { n: changed.length })}
              </span>
            ) : (
              <>
                <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>
              </>
            )}
          </span>
        </footer>
      </form>
    </aside>
  );
}
