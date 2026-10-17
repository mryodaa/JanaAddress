import { type Query, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  FIELD_NAMES,
  type FieldName,
  type ListParams,
  type RecordChange,
  type RecordItem,
  type RecordList,
  type SortKey,
  api,
} from "../api/client";
import { useI18n } from "../i18n";
import { errorText } from "../lib/errors";
import { isModalOpen, typingIn, useWindowKey } from "../lib/keys";
import { useDebounced, useMedia, usePresence } from "../lib/motion";
import { setUnsaved } from "../lib/unsaved";
import { Editor } from "./Editor";
import { ExportDialog } from "./ExportDialog";
import { DEFAULT_SORT, type Flash, RecordsTable, type Sort, nextSort } from "./RecordsTable";
import { ShortcutsDialog } from "./Shortcuts";
import { Summary, bucketRange } from "./Summary";
import { useToast } from "./Toast";
import { IconAlert, IconDownload, IconKeyboard, IconPlus, IconX } from "./icons";
import {
  BusyBar,
  Button,
  IconButton,
  Kbd,
  ProgressBar,
  Segmented,
  Skeleton,
  TextInput,
  useFocusTrap,
} from "./ui";

export type Filter = "all" | "uncertain" | "skipped" | "reviewed" | "edited";
const FILTERS: Filter[] = ["all", "uncertain", "skipped", "reviewed", "edited"];

type ActionKind = "confirm" | "defer" | "unconfirm" | "return" | "undo";
interface RecordAction {
  idx: number;
  change: RecordChange;
  kind: ActionKind;
  /** запись до действия: из неё собирается отмена */
  prev?: RecordItem;
}

/** Изменение, которое возвращает запись в состояние prev: поля, которые поменялись, и статус проверки. */
function revertChange(prev: RecordItem, now: RecordItem): RecordChange {
  const fields: Partial<Record<FieldName, string | null>> = {};
  for (const f of FIELD_NAMES)
    if ((now.record[f] ?? null) !== (prev.record[f] ?? null)) fields[f] = prev.record[f] ?? null;
  return { fields, reviewed: prev.reviewed, skipped: prev.skipped ?? false };
}

/** Записей на страницу: таблица подгружает страницы по мере прокрутки, пакет может быть любого размера. */
const PAGE = 500;
const SORT_KEYS: SortKey[] = ["idx", "confidence", "raw", "added"];

// «неуверенные» = очередь проверки: ниже порога, не подтверждены и не отложены;
// «отложенные» = оператор решил вернуться позже; «проверенные» = подтверждены (с правками или без);
// «исправленные» = оператор поменял хотя бы одно поле
function filterParams(f: Filter): ListParams {
  if (f === "uncertain") return { uncertain: true, reviewed: false, skipped: false };
  if (f === "skipped") return { skipped: true };
  if (f === "reviewed") return { reviewed: true };
  if (f === "edited") return { edited: true };
  return {};
}

/** Фильтр, поиск и сортировка живут в адресе: перезагрузка страницы и ссылка возвращают тот же список. */
function readListState(sid: string): { filter: Filter; q: string; sort: Sort; bucket: number | null } {
  const h = window.location.hash;
  const at = h.indexOf("?");
  const qs = new URLSearchParams(h.startsWith(`#/s/${sid}`) && at >= 0 ? h.slice(at + 1) : "");
  const f = qs.get("f");
  const [key, dir] = (qs.get("sort") ?? "").split(".");
  const sort: Sort =
    SORT_KEYS.includes(key as SortKey) && (dir === "asc" || dir === "desc")
      ? { key: key as SortKey, dir }
      : DEFAULT_SORT;
  const b = Number(qs.get("b") ?? "");
  const bucket = qs.has("b") && Number.isInteger(b) && b >= 0 && b <= 9 ? b : null;
  const filter = FILTERS.includes(f as Filter) ? (f as Filter) : "all";
  return { filter, q: qs.get("q") ?? "", sort, bucket };
}

/** Выбранная запись: место в списке (null, если в текущем списке её нет) и последнее известное содержимое. */
interface Selection {
  idx: number;
  pos: number | null;
  item: RecordItem;
}

export function SessionView({
  sid,
  threshold: fallbackThreshold,
  active,
  onBack,
}: { sid: string; threshold: number; active: boolean; onBack: () => void }) {
  const { t, language } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [init] = useState(() => readListState(sid));
  const [filter, setFilter] = useState<Filter>(init.filter);
  // столбец гистограммы уверенности: дополнительный фильтр поверх «все / неуверенные / исправленные»
  const [bucket, setBucket] = useState<number | null>(init.bucket);
  const [search, setSearch] = useState(init.q);
  const q = useDebounced(search, 250).trim();
  const [sort, setSort] = useState<Sort>(init.sort);
  const [sel, setSel] = useState<Selection | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [help, setHelp] = useState(false);
  const [exporting, setExporting] = useState(false);
  // переход запрошен при несохранённом черновике: что сделать после «сохранить» или «не сохранять»
  const [pending, setPending] = useState<{ run: () => void } | null>(null);
  const dirty = useRef(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  // редактор встаёт рядом с таблицей уже с 768px; поверх таблицы выезжает только на телефоне
  const isLg = useMedia("(min-width: 768px)");

  const session = useQuery({
    queryKey: ["session", sid],
    queryFn: () => api.session(sid),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 500 : false),
    // 404 не повторяем: пакет удалён; сетевые сбои повторяем, прежние данные остаются на экране
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 3,
  });
  const done = !!session.data && session.data.status !== "processing";
  const threshold = session.data?.summary.threshold ?? fallbackThreshold;

  // ---------- список страницами ----------
  const params: ListParams = useMemo(
    () => ({ ...filterParams(filter), q, sort: sort.key, dir: sort.dir, bucket }),
    [filter, q, sort, bucket],
  );
  const listKey = useMemo(
    () => ["records", sid, filter, q, sort.key, sort.dir, bucket] as const,
    [sid, filter, q, sort, bucket],
  );
  const fetchPage = useCallback((p: number) => api.records(sid, params, p * PAGE, PAGE), [sid, params]);
  const [range, setRange] = useState<[number, number]>([0, 0]);
  const onRange = useCallback((a: number, b: number) => {
    const pa = Math.floor(a / PAGE);
    const pb = Math.floor(b / PAGE);
    setRange((r) => (r[0] === pa && r[1] === pb ? r : [pa, pb]));
  }, []);
  const selPos = sel?.pos ?? null;
  const wanted = useMemo(() => {
    const s = new Set<number>([0]);
    for (let p = range[0]; p <= range[1]; p++) s.add(p);
    if (selPos != null) s.add(Math.floor(selPos / PAGE));
    return [...s].sort((a, b) => a - b);
  }, [range, selPos]);
  const pages = useQueries({
    queries: wanted.map((p) => ({
      queryKey: [...listKey, p],
      queryFn: () => fetchPage(p),
      enabled: done,
      staleTime: 15_000,
      // первая страница при наборе в поиске держит прежний список; при смене фильтра чужой список не показываем
      placeholderData:
        p === 0
          ? (prev: RecordList | undefined, prevQuery: Query<RecordList, Error, RecordList> | undefined) =>
              prevQuery?.queryKey[2] === filter ? prev : undefined
          : undefined,
    })),
  });
  const first = pages[0];
  const total = first?.data?.total ?? 0;
  const byPos = new Map<number, RecordItem>();
  const posOf = new Map<number, number>();
  for (const r of pages) {
    const d = r.data;
    if (!d) continue;
    d.items.forEach((it, i) => {
      byPos.set(d.offset + i, it);
      posOf.set(it.idx, d.offset + i);
    });
  }
  const itemAt = (pos: number) => byPos.get(pos);
  const listFetching = pages.some((r) => r.isFetching);
  const listError = pages.find((r) => r.error)?.error;

  const known = sel ? posOf.get(sel.idx) : undefined;
  const curPos = sel ? (known ?? sel.pos) : null;
  const current = sel ? ((known != null ? byPos.get(known) : undefined) ?? sel.item) : undefined;

  // редактор уезжает с анимацией: последнюю запись держим, пока идёт уход
  const last = useRef<RecordItem | undefined>(undefined);
  if (current) last.current = current;
  const presence = usePresence(!!current, 200);
  const shown = current ?? (presence.mounted ? last.current : undefined);

  // порядок или поиск сменились: место выбранной записи в новом списке знает только сервер
  const selIdx = sel?.idx;
  // biome-ignore lint/correctness/useExhaustiveDependencies: только при смене списка, а не на каждый выбор
  useEffect(() => {
    if (selIdx == null || !done) return;
    let stale = false;
    api
      .position(sid, selIdx, params)
      .then((r) => {
        if (!stale) setSel((s) => (s && s.idx === selIdx ? { ...s, pos: r.position ?? null } : s));
      })
      .catch(() => undefined);
    return () => {
      stale = true;
    };
  }, [params]);

  // фильтр, поиск и сортировка в адресе (без новой записи в истории)
  useEffect(() => {
    if (!active) return;
    const qs = new URLSearchParams();
    if (filter !== "all") qs.set("f", filter);
    if (q) qs.set("q", q);
    if (bucket != null) qs.set("b", String(bucket));
    if (sort.key !== DEFAULT_SORT.key || sort.dir !== DEFAULT_SORT.dir)
      qs.set("sort", `${sort.key}.${sort.dir}`);
    const s = qs.toString();
    const h = `#/s/${sid}${s ? `?${s}` : ""}`;
    if (window.location.hash !== h) window.history.replaceState(null, "", h);
  }, [active, sid, filter, q, sort, bucket]);

  // ---------- выбор и переходы ----------
  const selectNow = useCallback((it: RecordItem | null, pos: number | null) => {
    setPending(null);
    setSel(it ? { idx: it.idx, pos, item: it } : null);
  }, []);

  // любой уход с записи с несохранённым черновиком сначала спрашивает (баннер в редакторе)
  const guard = (run: () => void) => {
    if (dirty.current && sel) {
      setPending({ run });
      return;
    }
    run();
  };

  // актуальное состояние для обработчиков, которые срабатывают позже рендера (успех сохранения, клавиши)
  const live = useRef({ total, byPos, posOf, curPos, listKey, fetchPage, sel, pending });
  live.current = { total, byPos, posOf, curPos, listKey, fetchPage, sel, pending };

  async function go(delta: number, force = false) {
    const { total: n, byPos: map, curPos: from, listKey: key, fetchPage: fetchFn } = live.current;
    if (!n) return;
    const target = Math.min(n - 1, Math.max(0, (from ?? -1) + delta));
    if (from != null && target === from) return;
    let it = map.get(target);
    if (!it) {
      // запись на ещё не загруженной странице: догружаем её и только потом переходим
      const p = Math.floor(target / PAGE);
      try {
        const d = await qc.fetchQuery({
          queryKey: [...key, p],
          queryFn: () => fetchFn(p),
          staleTime: 15_000,
        });
        it = d.items[target - d.offset];
      } catch {
        return;
      }
    }
    if (!it) return;
    const item = it;
    if (force) selectNow(item, target);
    else guard(() => selectNow(item, target));
  }

  // одно действие с записью: подтвердить (с правками), отложить, снять подтверждение, вернуть, отменить
  const save = useMutation({
    mutationFn: (v: RecordAction) => api.patch(sid, v.idx, v.change),
    onSuccess: (updated, v) => {
      // строку обновляем на месте во всех загруженных страницах: фильтр не выкидывает её до перехода дальше
      qc.setQueriesData<RecordList>({ queryKey: ["records", sid] }, (old) =>
        old?.items.some((it) => it.idx === updated.idx)
          ? { ...old, items: old.items.map((it) => (it.idx === updated.idx ? updated : it)) }
          : old,
      );
      void qc.invalidateQueries({ queryKey: ["session", sid] });
      // другие списки (фильтр, поиск, порядок) устарели; текущий не трогаем, иначе запись исчезнет из-под руки
      const cur = live.current.listKey;
      void qc.invalidateQueries({
        queryKey: ["records", sid],
        predicate: (qq) => !cur.every((k, i) => qq.queryKey[i] === k),
      });
      setFlash({ idx: updated.idx, at: Date.now() });
      if (v.kind === "confirm" || v.kind === "defer") {
        dirty.current = false;
        setUnsaved(false);
      }
      setSel((s) => (s && s.idx === updated.idx ? { ...s, item: updated } : s));
      // уведомление с отменой: вернуть запись в состояние до действия и открыть её снова
      const prev = v.prev;
      const undo =
        prev && v.kind !== "undo"
          ? {
              label: t("undo"),
              run: () =>
                save.mutate({ idx: prev.idx, change: revertChange(prev, updated), kind: "undo", prev }),
            }
          : undefined;
      const text = {
        confirm: Object.keys(v.change.fields ?? {}).length ? t("saved") : t("toastConfirmed"),
        defer: t("toastDeferred"),
        unconfirm: t("toastUnconfirmed"),
        return: t("toastReturned"),
        undo: t("undone"),
      }[v.kind];
      toast(text, "ok", undo);
      if (v.kind === "undo") {
        const p = live.current.posOf.get(updated.idx);
        selectNow(updated, p ?? null);
        return;
      }
      if (v.kind !== "confirm" && v.kind !== "defer") return;
      const then = live.current.pending;
      if (then) {
        setPending(null);
        then.run();
      } else if (live.current.sel?.idx === updated.idx) {
        // дальше от сохранённой записи; двойное сохранение не перескакивает через запись
        void go(1, true);
      }
    },
    onError: (e) => toast(t("saveError", { msg: errorText(e, t, language) }), "error"),
  });

  const onDirty = useCallback((d: boolean) => {
    dirty.current = d;
    setUnsaved(d);
  }, []);

  // редактор закрылся: висящий запрос перехода больше некому показать, черновика тоже нет
  useEffect(() => {
    if (!shown) {
      setPending(null);
      dirty.current = false;
      setUnsaved(false);
    }
  }, [shown]);
  useEffect(() => () => setUnsaved(false), []);

  const applyFilter = (f: Filter) =>
    guard(() => {
      setFilter(f);
      selectNow(null, null);
    });

  // клик по столбцу графика: показать его записи, повторный клик снимает
  const applyBucket = (b: number | null) =>
    guard(() => {
      setBucket((cur) => (b === cur ? null : b));
      selectNow(null, null);
    });

  // J/K или ↓/↑ по списку (когда фокус не в поле ввода); на скрытой вкладке и под диалогом клавиши не наши
  useWindowKey((e) => {
    if (isModalOpen() || typingIn(e) || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === "j" || e.key === "о" || e.key === "ArrowDown") {
      e.preventDefault();
      void go(1);
    } else if (e.key === "k" || e.key === "л" || e.key === "ArrowUp") {
      e.preventDefault();
      void go(-1);
    } else if (e.key === "u" || e.key === "г") {
      applyFilter(filter === "uncertain" ? "all" : "uncertain");
    } else if (e.key === "/" || e.key === ".") {
      e.preventDefault();
      searchRef.current?.focus();
    } else if (e.key === "?" || (e.key === "," && e.shiftKey)) {
      e.preventDefault();
      setHelp(true);
    }
  }, active);

  const drawerOpen = !!shown && !isLg;
  useFocusTrap(drawer, drawerOpen && !presence.leaving);

  if (!session.data) {
    if (session.error) {
      const notFound = session.error instanceof ApiError && session.error.status === 404;
      return (
        <div className="mx-auto mt-10 flex max-w-md animate-fade-up flex-col items-center gap-3 rounded-[20px] border border-line bg-white p-8 text-center">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-danger-50 text-danger">
            <IconAlert className="h-5 w-5" />
          </span>
          <div className="text-sm text-ink-2">
            {notFound
              ? t("sessionNotFound")
              : t("sessionLoadError", { msg: errorText(session.error, t, language) })}
          </div>
          <div className="flex gap-2">
            {!notFound && (
              <Button variant="primary" onClick={() => void session.refetch()}>
                {t("retry")}
              </Button>
            )}
            <Button variant={notFound ? "primary" : "neutral"} onClick={onBack}>
              {t("backToUpload")}
            </Button>
          </div>
        </div>
      );
    }
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
      position={
        curPos != null && current ? t("positionOf", { pos: curPos + 1, total }) : t("positionUnknown")
      }
      onSave={(idx, fields) =>
        save.mutate({ idx, change: { fields, reviewed: true }, kind: "confirm", prev: shown ?? undefined })
      }
      onDefer={(idx, fields) =>
        save.mutate({ idx, change: { fields, skipped: true }, kind: "defer", prev: shown ?? undefined })
      }
      onStatus={(idx, change) =>
        save.mutate({
          idx,
          change,
          kind: change.reviewed === false ? "unconfirm" : "return",
          prev: shown ?? undefined,
        })
      }
      onPrev={() => void go(-1)}
      onNext={() => void go(1)}
      onClose={() => guard(() => selectNow(null, null))}
      onDirty={onDirty}
      pending={!!pending}
      onResolve={(a) => {
        const p = pending;
        setPending(null);
        if (a === "discard" && p) {
          dirty.current = false;
          setUnsaved(false);
          p.run();
        }
      }}
      saving={save.isPending}
      active={active && !!current && !help}
      className={
        isLg
          ? presence.leaving
            ? "pointer-events-none animate-slide-out-right"
            : "animate-slide-in-right"
          : "rounded-r-none border-r-0 shadow-2xl shadow-ink/20"
      }
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {session.isError && (
        <div
          // biome-ignore lint/a11y/useSemanticElements: <output> для формы, здесь живое уведомление
          role="status"
          className="flex animate-fade-up items-center gap-2 rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-800"
        >
          <IconAlert className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">{t("errorConnection")}</span>
          <Button size="sm" variant="ghost" onClick={() => void session.refetch()}>
            {t("retry")}
          </Button>
        </div>
      )}
      {s.status === "error" && (
        <div
          role="alert"
          className="flex animate-fade-up items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger"
        >
          <IconAlert className="h-4 w-4 shrink-0" />
          {t("sessionFailed", { msg: s.error ?? "?" })}
        </div>
      )}
      <Summary
        s={s}
        filter={filter}
        onUncertain={() => applyFilter(filter === "uncertain" ? "all" : "uncertain")}
        bucket={bucket}
        onBucket={applyBucket}
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
            { value: "skipped", label: t("filterSkipped"), badge: s.summary.skipped ?? 0 },
            { value: "reviewed", label: t("filterReviewed"), badge: s.summary.reviewed, badgeTone: "brand" },
            { value: "edited", label: t("filterEdited"), badge: s.summary.edited, badgeTone: "brand" },
          ]}
        />
        {bucket != null && (
          <span className="inline-flex h-8 animate-scale-in items-center gap-1 rounded-full bg-ink pr-1 pl-3 text-xs font-medium text-white">
            {t("bucketChip", { range: bucketRange(bucket) })}
            <button
              type="button"
              onClick={() => applyBucket(null)}
              aria-label={t("bucketClear")}
              title={t("bucketClear")}
              className="grid h-6 w-6 place-items-center rounded-full transition-colors hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            >
              <IconX className="h-3.5 w-3.5" />
            </button>
          </span>
        )}
        <span className="text-xs tabular-nums text-ink-3">
          {first?.data ? t("inList", { total: first.data.total }) : ""}
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
          <Button
            variant="primary"
            icon={<IconDownload />}
            disabled={!done}
            onClick={() => setExporting(true)}
          >
            {t("exportOpen")}
          </Button>
          <Button
            onClick={() =>
              guard(() => {
                dirty.current = false;
                setUnsaved(false);
                onBack();
              })
            }
            icon={<IconPlus />}
          >
            {t("newFile")}
          </Button>
        </div>
      </div>
      {listError && (
        <div className="flex animate-fade-up items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger">
          <IconAlert className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">{errorText(listError, t, language)}</span>
          <Button size="sm" variant="ghost" onClick={() => void qc.refetchQueries({ queryKey: listKey })}>
            {t("retry")}
          </Button>
        </div>
      )}
      <div
        className={`grid min-h-[420px] flex-1 gap-3 ${shown && isLg ? "grid-cols-[minmax(0,1fr)_clamp(320px,34vw,440px)]" : "grid-cols-1"}`}
      >
        <div className="relative min-h-[420px] min-w-0">
          <BusyBar active={listFetching && !!first?.data} className="absolute inset-x-5 top-0 z-30" />
          {done ? (
            first?.data || !first?.isPending ? (
              <RecordsTable
                key={listKey.join("|")}
                total={total}
                itemAt={itemAt}
                selectedIdx={sel?.idx ?? null}
                selectedPos={curPos}
                onSelect={(it, pos) => {
                  if (it.idx !== sel?.idx) guard(() => selectNow(it, pos));
                }}
                onRange={onRange}
                sort={sort}
                onSort={(key) => setSort((v) => nextSort(v, key))}
                threshold={threshold}
                active={active}
                flash={flash}
                onReset={
                  filter !== "all" || search || bucket != null
                    ? () =>
                        guard(() => {
                          setSearch("");
                          setFilter("all");
                          setBucket(null);
                          selectNow(null, null);
                        })
                    : undefined
                }
              />
            ) : (
              <Skeleton className="h-full min-h-[420px] w-full rounded-[20px]" />
            )
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
        {shown && isLg && (
          <div className="min-h-0" aria-hidden={presence.leaving || undefined}>
            {editor}
          </div>
        )}
      </div>
      {/* узкий экран: редактор выезжающей панелью поверх таблицы, это модальный диалог */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40">
          <button
            type="button"
            aria-label={t("closeTooltip")}
            tabIndex={-1}
            onClick={() => guard(() => selectNow(null, null))}
            className={`absolute inset-0 cursor-default bg-ink/30 ${presence.leaving ? "animate-fade-out" : "animate-fade-in"}`}
          />
          <div
            ref={drawer}
            // biome-ignore lint/a11y/useSemanticElements: <dialog> мешает анимации выезда, хватает role
            role="dialog"
            aria-modal="true"
            aria-label={shown ? t("recordTitle", { idx: shown.idx + 1 }) : undefined}
            tabIndex={-1}
            className={`absolute inset-y-0 right-0 w-[min(440px,100%)] focus:outline-none ${presence.leaving ? "pointer-events-none animate-slide-out-right" : "animate-slide-in-right"}`}
          >
            {editor}
          </div>
        </div>
      )}
      <ShortcutsDialog open={help} onClose={() => setHelp(false)} />
      <ExportDialog
        open={exporting}
        onClose={() => setExporting(false)}
        sid={sid}
        total={s.total}
        current={
          (filter !== "all" || q || bucket != null) && first?.data
            ? {
                count: first.data.total,
                params,
                labels: [
                  ...(filter !== "all"
                    ? [
                        {
                          uncertain: t("filterUncertain"),
                          skipped: t("filterSkipped"),
                          reviewed: t("filterReviewed"),
                          edited: t("filterEdited"),
                        }[filter],
                      ]
                    : []),
                  ...(q ? [t("exportSearch", { q })] : []),
                  ...(bucket != null ? [t("bucketChip", { range: bucketRange(bucket) })] : []),
                ],
              }
            : null
        }
      />
    </div>
  );
}
