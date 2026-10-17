import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { FIELD_NAMES, type FieldName, type RecordItem, type SortDir, type SortKey } from "../api/client";
import { useI18n } from "../i18n";
import { IconCheck, IconClock, IconSearch } from "./icons";
import { Button, ConfidenceBadge, FieldDot, Highlighted, Legend, SourceTag } from "./ui";

export interface Flash {
  idx: number;
  at: number;
}

/**
 * Раскладка по ширине контейнера, горизонтальной прокрутки нет ни в одной.
 * Разобранное из строки видно подсветкой, поэтому отдельной колонкой идёт только то, чего в строке нет:
 * восстановленное по справочнику и правки оператора.
 */
type Mode = "wide" | "narrow";
const WIDE_MIN = 560;
const TEMPLATE: Record<Mode, string> = {
  wide: "52px 64px minmax(0,1.7fr) minmax(0,1fr)",
  narrow: "40px minmax(0,1fr) 56px",
};
const ROW_H = 60;

/** Поля, которых не видно в подсветке: источник не строка (справочник) или ручная правка. */
function addedFields(item: RecordItem): FieldName[] {
  return FIELD_NAMES.filter((f) => {
    const src = item.fields[f]?.source;
    return item.edited.includes(f) || (item.record[f] != null && src != null && src !== "string");
  });
}

export interface Sort {
  key: SortKey;
  dir: SortDir;
}

/** Исходный порядок пакета: по номеру записи. Это «сортировки нет». */
export const DEFAULT_SORT: Sort = { key: "idx", dir: "asc" };

function isDefaultSort(s: Sort): boolean {
  return s.key === DEFAULT_SORT.key && s.dir === DEFAULT_SORT.dir;
}

/** Клик по заголовку: по возрастанию → по убыванию → исходный порядок. У «#» исходный порядок и есть возрастание. */
export function nextSort(s: Sort, key: SortKey): Sort {
  const first: Sort = key === DEFAULT_SORT.key ? { key, dir: "desc" } : { key, dir: "asc" };
  if (isDefaultSort(s) || s.key !== key) return first;
  if (key !== DEFAULT_SORT.key && s.dir === "asc") return { key, dir: "desc" };
  return DEFAULT_SORT;
}

function Added({ item }: { item: RecordItem }) {
  const { fieldLabels } = useI18n();
  const extra = addedFields(item);
  if (!extra.length) return null;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {extra.map((f) => (
        <span key={f} className="inline-flex min-w-0 max-w-full items-baseline gap-1.5">
          <FieldDot field={f} className="self-center" />
          <span className="text-xs text-ink-3">{fieldLabels[f]}</span>
          <span className={`break-words ${item.edited.includes(f) ? "font-semibold text-ink" : ""}`}>
            {item.record[f] ?? <span className="font-mono text-xs text-ink-3">null</span>}
            <SourceTag source={item.fields[f]?.source} />
          </span>
        </span>
      ))}
    </span>
  );
}

/** Заголовок столбца: клик сортирует, второй меняет направление, третий возвращает исходный порядок. */
function SortHead({
  k,
  sort,
  onSort,
  className,
  title,
  children,
}: {
  k: SortKey;
  sort: Sort;
  onSort: (key: SortKey) => void;
  className: string;
  title?: string;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  // исходный порядок не подсвечиваем: стрелка видна, только когда сортировка действительно включена
  const on = sort.key === k && !isDefaultSort(sort);
  return (
    <div className="min-w-0">
      <button
        type="button"
        aria-pressed={on}
        onClick={() => onSort(k)}
        title={title ?? t("sortHint")}
        className={`group inline-flex w-full items-center gap-1 text-left transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600/30 ${on ? "text-ink" : ""} ${className}`}
      >
        <span className="truncate">{children}</span>
        <svg
          viewBox="0 0 12 12"
          className={`h-3 w-3 shrink-0 transition ${on ? "text-brand-700" : "text-ink-3 opacity-0 group-hover:opacity-60"} ${on && sort.dir === "desc" ? "rotate-180" : ""}`}
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M6 2.5 9.5 7.5h-7z" />
        </svg>
      </button>
    </div>
  );
}

function RowSkeleton({ mode }: { mode: Mode }) {
  return (
    <>
      <div className="px-2.5 py-3">
        <div className="skeleton h-3.5 w-6" />
      </div>
      {mode === "wide" && (
        <div className="px-2.5 py-3">
          <div className="skeleton h-5 w-11 rounded-full" />
        </div>
      )}
      <div className="px-2.5 py-3">
        <div className="skeleton h-3.5 w-4/5" />
      </div>
      <div className="px-2.5 py-3">
        <div className="skeleton h-3.5 w-1/2" />
      </div>
    </>
  );
}

/**
 * Таблица пакета. Строк может быть сколько угодно: виртуализатор знает только total, а записи приходят
 * страницами по мере прокрутки (itemAt отдаёт undefined, пока страница не загружена: рисуется скелет).
 */
export function RecordsTable({
  total,
  itemAt,
  selectedIdx,
  selectedPos,
  onSelect,
  onRange,
  threshold,
  active,
  flash,
  onReset,
  sort,
  onSort,
}: {
  total: number;
  itemAt: (pos: number) => RecordItem | undefined;
  selectedIdx: number | null;
  selectedPos: number | null;
  onSelect: (item: RecordItem, pos: number) => void;
  /** видимый диапазон строк: какие страницы подгрузить */
  onRange: (start: number, end: number) => void;
  threshold: number;
  active: boolean;
  flash: Flash | null;
  onReset?: () => void;
  sort: Sort;
  onSort: (key: SortKey) => void;
}) {
  const { t } = useI18n();
  const parent = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("wide");

  useLayoutEffect(() => {
    const el = parent.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      if (w) setMode(w >= WIDE_MIN ? "wide" : "narrow");
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const virt = useVirtualizer({
    count: total,
    getScrollElement: () => parent.current,
    estimateSize: () => ROW_H,
    overscan: 12,
    measureElement: (el) => el.getBoundingClientRect().height,
  });
  const vis = virt.getVirtualItems();
  const first = vis[0]?.index ?? 0;
  const last = vis[vis.length - 1]?.index ?? 0;
  useEffect(() => {
    onRange(first, last);
  }, [first, last, onRange]);

  // выбранная строка всегда в зоне видимости (навигация с клавиатуры, в том числе через границу страницы)
  useEffect(() => {
    if (selectedPos == null || selectedPos >= total) return;
    virt.scrollToIndex(selectedPos, { align: "auto" });
  }, [selectedPos, total, virt]);

  // скрытая вкладка (display: none) может потерять прокрутку: запоминаем её и возвращаем при показе
  const offset = useRef(0);
  useLayoutEffect(() => {
    const el = parent.current;
    if (active && el && el.scrollTop !== offset.current) el.scrollTop = offset.current;
  }, [active]);

  const grid = { gridTemplateColumns: TEMPLATE[mode] };
  const cell = "min-w-0 px-2.5 py-2.5";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[20px] border border-line bg-white">
      <div className="border-b border-line-soft px-4 py-2">
        <Legend />
      </div>
      <div className="relative min-h-0 flex-1">
        <div
          ref={parent}
          // biome-ignore lint/a11y/useSemanticElements: виртуальный список на div, <section> не подходит по вёрстке
          role="region"
          aria-label={t("recordsTableAria")}
          onScroll={(e) => {
            if (active) offset.current = e.currentTarget.scrollTop;
          }}
          className="absolute inset-0 overflow-y-auto overflow-x-hidden"
        >
          <div
            style={grid}
            className="sticky top-0 z-20 grid border-b border-line bg-canvas text-xs font-semibold text-ink-2"
          >
            <SortHead k="idx" sort={sort} onSort={onSort} className={cell}>
              #
            </SortHead>
            {mode === "wide" && (
              <SortHead k="confidence" sort={sort} onSort={onSort} className={cell}>
                {t("confidenceShort")}
              </SortHead>
            )}
            <SortHead k="raw" sort={sort} onSort={onSort} className={cell}>
              {t("originalString")}
            </SortHead>
            {mode === "wide" ? (
              <SortHead k="added" sort={sort} onSort={onSort} className={cell} title={t("addedHint")}>
                {t("addedColumn")}
              </SortHead>
            ) : (
              <SortHead k="confidence" sort={sort} onSort={onSort} className={cell}>
                {t("confidenceShort")}
              </SortHead>
            )}
          </div>
          <div style={{ height: virt.getTotalSize(), position: "relative" }}>
            {vis.map((v) => {
              const it = itemAt(v.index);
              if (!it) {
                return (
                  <div
                    key={`s${v.index}`}
                    aria-hidden="true"
                    style={{ ...grid, height: ROW_H, transform: `translateY(${v.start}px)` }}
                    className="absolute left-0 grid w-full border-b border-line-soft"
                  >
                    <RowSkeleton mode={mode} />
                  </div>
                );
              }
              const isSel = it.idx === selectedIdx;
              const isFlash = flash?.idx === it.idx;
              const skipped = !!it.skipped;
              const needsReview =
                !it.reviewed && !skipped && !it.edited.length && it.record.confidence < threshold;
              const stripe = isSel
                ? "bg-brand-600"
                : it.reviewed
                  ? "bg-brand-300"
                  : skipped
                    ? "bg-ink-3/50"
                    : needsReview
                      ? "bg-warn"
                      : "bg-transparent";
              const raw = <Highlighted raw={String(it.record.raw_address ?? "")} fields={it.fields} />;
              const badge = <ConfidenceBadge value={it.record.confidence} threshold={threshold} />;
              return (
                <div
                  key={isFlash ? `${it.idx}-${flash.at}` : it.idx}
                  data-index={v.index}
                  ref={virt.measureElement}
                  aria-current={isSel || undefined}
                  onClick={() => onSelect(it, v.index)}
                  onKeyDown={(e) => e.key === "Enter" && onSelect(it, v.index)}
                  // выбранная строка в порядке Tab: с клавиатуры до таблицы можно дойти и открыть запись Enter
                  tabIndex={isSel || (selectedIdx == null && v.index === first) ? 0 : -1}
                  style={{ ...grid, transform: `translateY(${v.start}px)` }}
                  className={`absolute left-0 grid w-full cursor-pointer border-b border-line-soft text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-600/40 ${
                    isSel ? "bg-brand-50" : "bg-white hover:bg-canvas"
                  } ${isFlash ? "animate-flash-ok" : ""}`}
                >
                  <div className={`${cell} relative`}>
                    <span
                      className={`absolute inset-y-0 left-0 w-[3px] transition-colors duration-200 ${stripe}`}
                    />
                    <span className="inline-flex items-center gap-1 tabular-nums text-ink-3">
                      {it.reviewed ? (
                        <IconCheck
                          className={`h-3.5 w-3.5 text-brand-600 ${isFlash ? "animate-check-pop" : ""}`}
                        />
                      ) : skipped ? (
                        <IconClock
                          className={`h-3.5 w-3.5 text-ink-3 ${isFlash ? "animate-check-pop" : ""}`}
                        />
                      ) : null}
                      {it.idx + 1}
                    </span>
                    {/* статус строки цветом полоски, для скринридера текстом */}
                    <span className="sr-only">
                      {it.reviewed
                        ? t("rowReviewed")
                        : skipped
                          ? t("rowSkipped")
                          : needsReview
                            ? t("rowNeedsReview")
                            : ""}
                    </span>
                  </div>
                  {mode === "wide" && <div className={cell}>{badge}</div>}
                  {mode === "wide" ? (
                    <>
                      <div className={cell}>{raw}</div>
                      <div className={`${cell} text-[13px]`}>
                        <Added item={it} />
                      </div>
                    </>
                  ) : (
                    <>
                      <div className={`${cell} grid gap-1.5`}>
                        <div>{raw}</div>
                        <div className="text-[13px] empty:hidden">
                          <Added item={it} />
                        </div>
                      </div>
                      <div className={`${cell} pl-0`}>{badge}</div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        {total === 0 && (
          <div className="pointer-events-none absolute inset-x-0 top-10 bottom-0 grid place-items-center p-6">
            <div className="pointer-events-auto flex animate-fade-in flex-col items-center gap-3 text-center text-sm text-ink-2">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-canvas text-ink-3">
                <IconSearch className="h-5 w-5" />
              </span>
              {t("nothingFound")}
              {onReset && (
                <Button size="sm" onClick={onReset}>
                  {t("resetFilters")}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
