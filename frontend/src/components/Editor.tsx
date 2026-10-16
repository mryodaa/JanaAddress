import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { FIELD_NAMES, type FieldName, type RecordItem, api } from "../api/client";
import { FIELD_COLORS, FIELD_LABELS } from "../lib/fields";
import { Trace } from "./Trace";
import { Button, ConfidenceBadge, Highlighted, Kbd, SourceTag } from "./ui";

type Draft = Record<FieldName, string>;

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
  saving,
}: {
  sid: string;
  item: RecordItem;
  threshold: number;
  position: string;
  onSave: (fields: Partial<Record<FieldName, string | null>>) => void;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(item));
  const [showTrace, setShowTrace] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const full = useQuery({
    queryKey: ["record", sid, item.idx],
    queryFn: () => api.record(sid, item.idx),
    enabled: showTrace,
  });

  useEffect(() => {
    setDraft(toDraft(item));
  }, [item]);

  const changed = FIELD_NAMES.filter((f) => (item.record[f] ?? "") !== draft[f]);

  function save() {
    onSave(Object.fromEntries(changed.map((f) => [f, draft[f].trim() || null])));
  }

  // Ctrl+Enter сохранить и дальше, Esc закрыть, Alt+↑/↓ соседние записи
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        save();
      } else if (e.key === "Escape") onClose();
      else if (e.altKey && e.key === "ArrowDown") {
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

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <div className="text-sm font-semibold">
          Запись {item.idx + 1} <span className="font-normal text-slate-400">· {position}</span>
        </div>
        <div className="flex items-center gap-1">
          <ConfidenceBadge value={item.record.confidence} threshold={threshold} />
          <Button variant="ghost" onClick={onPrev} title="Предыдущая (K или Alt+↑)" aria-label="предыдущая">
            ↑
          </Button>
          <Button variant="ghost" onClick={onNext} title="Следующая (J или Alt+↓)" aria-label="следующая">
            ↓
          </Button>
          <Button variant="ghost" onClick={onClose} title="Закрыть (Esc)" aria-label="закрыть">
            ✕
          </Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        <div className="mb-3 rounded-lg bg-slate-50 p-2.5 text-sm leading-relaxed">
          <Highlighted raw={String(item.record.raw_address ?? "")} fields={item.fields} />
          <div className="mt-1 font-mono text-[11px] text-slate-400">id: {String(item.record.id)}</div>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
          className="grid gap-2"
        >
          {FIELD_NAMES.map((f, i) => (
            <label key={f} className="grid grid-cols-[130px_minmax(0,1fr)] items-center gap-2">
              <span className="flex items-center gap-1.5 text-xs text-slate-600">
                <span className={`h-2 w-2 rounded-sm ${FIELD_COLORS[f].dot}`} />
                {FIELD_LABELS[f]}
                <SourceTag source={item.fields[f]?.source} />
              </span>
              <input
                ref={i === 0 ? first : undefined}
                value={draft[f]}
                onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
                placeholder="null"
                className={`rounded-md border px-2 py-1 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200 ${
                  changed.includes(f) ? "border-amber-400 bg-amber-50" : "border-slate-300"
                }`}
              />
            </label>
          ))}
          {item.unparsed.length > 0 && (
            <div className="text-xs text-slate-500">
              Не разобрано: {item.unparsed.map((u) => `«${u}»`).join(", ")}
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button variant="primary" type="submit" disabled={saving}>
              {changed.length ? "Сохранить и дальше" : "Подтвердить и дальше"}
            </Button>
            <span className="text-xs text-slate-500">
              <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>
            </span>
            {item.reviewed && <span className="text-xs font-medium text-brand-700">✓ проверено</span>}
          </div>
        </form>
        <button
          type="button"
          onClick={() => setShowTrace((v) => !v)}
          className="mt-4 text-xs font-medium text-brand-700 hover:underline"
        >
          {showTrace ? "Скрыть" : "Показать"} шаги разбора
        </button>
        {showTrace && full.data?.trace && (
          <div className="mt-2">
            <Trace trace={full.data.trace} />
          </div>
        )}
      </div>
    </aside>
  );
}
