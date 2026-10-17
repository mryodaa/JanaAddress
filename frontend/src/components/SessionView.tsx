import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type FieldName, type RecordItem, type RecordList, api } from "../api/client";
import { useI18n } from "../i18n";
import { useDebounced, useMedia, usePresence } from "../lib/motion";
import { Editor } from "./Editor";
import {
  DEFAULT_SORT,
  type Flash,
  RecordsTable,
  type Sort,
  type SortKey,
  nextSort,
  sortItems,
} from "./RecordsTable";
import { ShortcutsDialog } from "./Shortcuts";
import { Summary } from "./Summary";
import { useToast } from "./Toast";
import { IconAlert, IconDownload, IconKeyboard, IconPlus } from "./icons";
import {
  BusyBar,
  Button,
  IconButton,
  Kbd,
  ProgressBar,
  Segmented,
  Skeleton,
  TextInput,
  buttonClass,
} from "./ui";

export type Filter = "all" | "uncertain" | "edited";

// «неуверенные» = ниже порога и ещё не просмотрены оператором: то, что стоит пройти;
// «исправленные» = оператор поменял хотя бы одно поле
function filterParams(f: Filter): { uncertain?: boolean; reviewed?: boolean; edited?: boolean } {
  if (f === "uncertain") return { uncertain: true, reviewed: false };
  if (f === "edited") return { edited: true };
  return {};
}

export function SessionView({
  sid,
  threshold,
  active,
  onBack,
}: { sid: string; threshold: number; active: boolean; onBack: () => void }) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const q = useDebounced(search, 250);
  const [selected, setSelected] = useState<number | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [help, setHelp] = useState(false);
  // переход запрошен при несохранённом черновике: куда (null = закрыть редактор)
  const [pending, setPending] = useState<{ to: number | null } | null>(null);
  const dirty = useRef(false);
  const searchRef = useRef<HTMLInputElement>(null);
  // редактор встаёт рядом с таблицей уже с 768px; поверх таблицы выезжает только на телефоне
  const isLg = useMedia("(min-width: 768px)");

  const session = useQuery({
    queryKey: ["session", sid],
    queryFn: () => api.session(sid),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 500 : false),
  });
  const done = session.data && session.data.status !== "processing";
  const recordsKey = ["records", sid, filter, q] as const;
  const records = useQuery({
    queryKey: recordsKey,
    queryFn: () => api.records(sid, { ...filterParams(filter), q }),
    enabled: !!done,
    // прежний список держим только при наборе в поиске; при смене фильтра чужой список не показываем
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === filter ? prev : undefined),
  });
  // сортировка по клику на столбец; навигация J/K и «дальше» идут в том же порядке, что на экране
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const onSort = (key: SortKey) => setSort((s) => nextSort(s, key));
  const loaded = records.data?.items;
  const items: RecordItem[] = useMemo(() => sortItems(loaded ?? [], sort, locale), [loaded, sort, locale]);
  const pos = useMemo(() => items.findIndex((it) => it.idx === selected), [items, selected]);
  const current = pos >= 0 ? items[pos] : undefined;

  // редактор уезжает с анимацией: последнюю запись держим, пока идёт уход
  const last = useRef<RecordItem | undefined>(undefined);
  if (current) last.current = current;
  const presence = usePresence(!!current, 200);
  const shown = current ?? (presence.mounted ? last.current : undefined);

  const select = useCallback(
    (idx: number | null) => {
      if (idx === selected) return;
      if (dirty.current && selected != null) {
        setPending({ to: idx });
        return;
      }
      setPending(null);
      setSelected(idx);
    },
    [selected],
  );

  const go = (delta: number, force = false) => {
    if (!items.length) return;
    const next = pos < 0 ? 0 : Math.min(items.length - 1, Math.max(0, pos + delta));
    const idx = items[next]?.idx ?? null;
    if (force) {
      setPending(null);
      setSelected(idx);
    } else select(idx);
  };

  const save = useMutation({
    mutationFn: (fields: Partial<Record<FieldName, string | null>>) => api.patch(sid, selected ?? 0, fields),
    onSuccess: (updated) => {
      // обновляем строку на месте, чтобы фильтр не выкидывал её до перехода дальше
      qc.setQueryData(recordsKey, (old: RecordList | undefined) =>
        old ? { ...old, items: old.items.map((it) => (it.idx === updated.idx ? updated : it)) } : old,
      );
      void qc.invalidateQueries({ queryKey: ["session", sid] });
      // списки других фильтров (проверены / не проверены) устарели
      void qc.invalidateQueries({ queryKey: ["records", sid], predicate: (qq) => qq.queryKey[2] !== filter });
      setFlash({ idx: updated.idx, at: Date.now() });
      toast(t("saved"));
      dirty.current = false;
      if (pending) {
        setSelected(pending.to);
        setPending(null);
      } else go(1, true);
    },
    onError: (e) => toast(t("saveError", { msg: e instanceof Error ? e.message : String(e) }), "error"),
  });

  const onDirty = useCallback((d: boolean) => {
    dirty.current = d;
  }, []);

  const applyFilter = (f: Filter) => {
    setFilter(f);
    setSelected(null);
    setPending(null);
    dirty.current = false;
  };

  // J/K или ↓/↑ по списку (когда фокус не в поле ввода); на скрытой вкладке клавиши не наши
  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      const tKey = e.target as HTMLElement;
      if (tKey.tagName === "INPUT" || tKey.tagName === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey)
        return;
      if (e.key === "j" || e.key === "о" || e.key === "ArrowDown") {
        e.preventDefault();
        go(1);
      } else if (e.key === "k" || e.key === "л" || e.key === "ArrowUp") {
        e.preventDefault();
        go(-1);
      } else if (e.key === "u" || e.key === "г") {
        applyFilter(filter === "uncertain" ? "all" : "uncertain");
      } else if (e.key === "/" || e.key === ".") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "?" || e.key === ",") {
        if (e.key === "," && !e.shiftKey) return;
        e.preventDefault();
        setHelp(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (session.isError) {
    return (
      <div className="mx-auto mt-10 flex max-w-md animate-fade-up flex-col items-center gap-3 rounded-[20px] border border-line bg-white p-8 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-danger-50 text-danger">
          <IconAlert className="h-5 w-5" />
        </span>
        <div className="text-sm text-ink-2">{t("sessionNotFound")}</div>
        <Button variant="primary" onClick={onBack}>
          {t("backToUpload")}
        </Button>
      </div>
    );
  }
  if (!session.data) {
    return (
      <div className="grid gap-3">
        <Skeleton className="h-36 w-full rounded-[20px]" />
        <Skeleton className="h-10 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-[20px]" />
      </div>
    );
  }

  const s = session.data;
  const editor = shown && (
    <Editor
      sid={sid}
      item={shown}
      threshold={threshold}
      position={t("positionOf", { pos: pos + 1, total: items.length })}
      onSave={(f) => save.mutate(f)}
      onPrev={() => go(-1)}
      onNext={() => go(1)}
      onClose={() => select(null)}
      onDirty={onDirty}
      pending={!!pending}
      onResolve={(a) => {
        if (a === "discard" && pending) {
          dirty.current = false;
          setSelected(pending.to);
        }
        setPending(null);
      }}
      saving={save.isPending}
      active={active && !!current}
      className={
        isLg
          ? presence.leaving
            ? "animate-slide-out-right"
            : "animate-slide-in-right"
          : "rounded-r-none border-r-0 shadow-2xl shadow-ink/20"
      }
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <Summary
        s={s}
        filter={filter}
        onUncertain={() => applyFilter(filter === "uncertain" ? "all" : "uncertain")}
      />
      <div className="flex flex-wrap items-center gap-2">
        <TextInput
          id="search"
          inputRef={searchRef}
          value={search}
          onChange={setSearch}
          placeholder={t("searchPlaceholder")}
          className="w-full sm:w-72"
          trailing={<Kbd>/</Kbd>}
        />
        <Segmented<Filter>
          ariaLabel={t("filterAria")}
          value={filter}
          onChange={applyFilter}
          options={[
            { value: "all", label: t("filterAll") },
            { value: "uncertain", label: t("filterUncertain"), badge: s.summary.to_review },
            { value: "edited", label: t("filterEdited"), badge: s.summary.edited, badgeTone: "brand" },
          ]}
        />
        <span className="text-xs tabular-nums text-ink-3">
          {records.data ? t("inList", { total: records.data.total }) : ""}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <IconButton
            label={t("shortcutsTitle")}
            variant="neutral"
            onClick={() => setHelp(true)}
            className="h-10 w-10"
          >
            <IconKeyboard className="h-5 w-5" />
          </IconButton>
          <a
            href={done ? api.exportUrl(sid) : undefined}
            download
            aria-disabled={!done}
            className={buttonClass("primary")}
          >
            <IconDownload />
            {t("exportJson")}
          </a>
          <Button onClick={onBack} icon={<IconPlus />}>
            {t("newFile")}
          </Button>
        </div>
      </div>
      <div
        className={`grid min-h-[420px] flex-1 gap-3 ${shown && isLg ? "grid-cols-[minmax(0,1fr)_clamp(320px,34vw,440px)]" : "grid-cols-1"}`}
      >
        <div className="relative min-h-[420px] min-w-0">
          <BusyBar active={records.isFetching && !!records.data} className="absolute inset-x-5 top-0 z-30" />
          {done ? (
            <RecordsTable
              items={items}
              sort={sort}
              onSort={onSort}
              selected={selected}
              onSelect={select}
              threshold={threshold}
              active={active}
              flash={flash}
              onReset={
                filter !== "all" || search
                  ? () => {
                      setSearch("");
                      applyFilter("all");
                    }
                  : undefined
              }
            />
          ) : (
            <div className="grid h-full animate-fade-in place-items-center rounded-[20px] border border-line bg-white">
              <div className="w-72 text-center">
                <div className="mb-3 text-sm font-medium text-ink">{t("parsingInProgress")}</div>
                <ProgressBar value={s.processed / Math.max(1, s.total)} className="h-2" />
                <div className="mt-2 text-xs tabular-nums text-ink-3">
                  {s.processed} / {s.total}
                </div>
              </div>
            </div>
          )}
        </div>
        {shown && isLg && <div className="min-h-0">{editor}</div>}
      </div>
      {/* узкий экран: редактор выезжающей панелью поверх таблицы */}
      {shown && !isLg && (
        <div className="fixed inset-0 z-40">
          <button
            type="button"
            aria-label={t("closeTooltip")}
            onClick={() => select(null)}
            className={`absolute inset-0 cursor-default bg-ink/30 ${presence.leaving ? "animate-fade-out" : "animate-fade-in"}`}
          />
          <div
            className={`absolute inset-y-0 right-0 w-[min(440px,100%)] ${presence.leaving ? "animate-slide-out-right" : "animate-slide-in-right"}`}
          >
            {editor}
          </div>
        </div>
      )}
      <ShortcutsDialog open={help} onClose={() => setHelp(false)} />
    </div>
  );
}
