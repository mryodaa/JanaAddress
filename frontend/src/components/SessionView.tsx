import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { type FieldName, type RecordItem, api } from "../api/client";
import { Editor } from "./Editor";
import { RecordsTable } from "./RecordsTable";
import { Summary } from "./Summary";
import { Button, Kbd, Legend } from "./ui";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function SessionView({
  sid,
  threshold,
  onBack,
}: { sid: string; threshold: number; onBack: () => void }) {
  const qc = useQueryClient();
  const [uncertain, setUncertain] = useState(false);
  const [search, setSearch] = useState("");
  const q = useDebounced(search, 250);
  const [selected, setSelected] = useState<number | null>(null);

  const session = useQuery({
    queryKey: ["session", sid],
    queryFn: () => api.session(sid),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 500 : false),
  });
  const done = session.data && session.data.status !== "processing";
  const records = useQuery({
    queryKey: ["records", sid, uncertain, q],
    queryFn: () => api.records(sid, { uncertain, q }),
    enabled: !!done,
    placeholderData: (prev) => prev,
  });
  const items: RecordItem[] = records.data?.items ?? [];
  const pos = useMemo(() => items.findIndex((it) => it.idx === selected), [items, selected]);
  const current = pos >= 0 ? items[pos] : undefined;

  const go = (delta: number) => {
    if (!items.length) return;
    const next = pos < 0 ? 0 : Math.min(items.length - 1, Math.max(0, pos + delta));
    setSelected(items[next]?.idx ?? null);
  };

  const save = useMutation({
    mutationFn: (fields: Partial<Record<FieldName, string | null>>) => api.patch(sid, selected ?? 0, fields),
    onSuccess: (updated) => {
      // обновляем строку на месте, чтобы фильтр «неуверенные» не выкидывал её до перехода дальше
      qc.setQueryData(["records", sid, uncertain, q], (old: typeof records.data) =>
        old ? { ...old, items: old.items.map((it) => (it.idx === updated.idx ? updated : it)) } : old,
      );
      void qc.invalidateQueries({ queryKey: ["session", sid] });
      go(1);
    },
  });

  // J/K или ↓/↑ по списку (когда фокус не в поле ввода)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "j" || e.key === "о" || e.key === "ArrowDown") {
        e.preventDefault();
        go(1);
      } else if (e.key === "k" || e.key === "л" || e.key === "ArrowUp") {
        e.preventDefault();
        go(-1);
      } else if (e.key === "u" || e.key === "г") {
        setUncertain((v) => !v);
      } else if (e.key === "/") {
        e.preventDefault();
        document.getElementById("search")?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (session.isError) {
    return (
      <div className="text-sm text-rose-700">
        Сессия не найдена. <Button onClick={onBack}>К загрузке</Button>
      </div>
    );
  }
  if (!session.data) return <div className="text-sm text-slate-500">Загрузка…</div>;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <Summary
        s={session.data}
        onUncertain={() => {
          setUncertain(true);
          setSelected(null);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <input
          id="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по строке и полям  ( / )"
          className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200 sm:w-72"
        />
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">
          <input
            type="checkbox"
            checked={uncertain}
            onChange={(e) => setUncertain(e.target.checked)}
            className="accent-brand-600"
          />
          только неуверенные
        </label>
        <span className="text-xs text-slate-500">{records.data ? `${records.data.total} в списке` : ""}</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-xs text-slate-500 lg:inline">
            <Kbd>J</Kbd>/<Kbd>K</Kbd> навигация · <Kbd>U</Kbd> неуверенные · <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>{" "}
            сохранить
          </span>
          <a href={api.exportUrl(sid)} download>
            <Button variant="primary" disabled={!done}>
              Экспорт JSON
            </Button>
          </a>
          <Button onClick={onBack}>Новый файл</Button>
        </div>
      </div>
      <Legend />
      <div
        className={`grid min-h-[420px] flex-1 gap-3 ${current ? "lg:grid-cols-[minmax(0,1fr)_420px]" : ""}`}
      >
        <div className="min-h-[420px] min-w-0">
          {done ? (
            <RecordsTable items={items} selected={selected} onSelect={setSelected} threshold={threshold} />
          ) : (
            <div className="grid h-full place-items-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500">
              Идёт разбор…
            </div>
          )}
        </div>
        {current && (
          <div className="min-h-0">
            <Editor
              sid={sid}
              item={current}
              threshold={threshold}
              position={`${pos + 1} из ${items.length}`}
              onSave={(f) => save.mutate(f)}
              onPrev={() => go(-1)}
              onNext={() => go(1)}
              onClose={() => setSelected(null)}
              saving={save.isPending}
            />
          </div>
        )}
      </div>
    </div>
  );
}
