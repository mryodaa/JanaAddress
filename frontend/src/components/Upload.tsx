import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../api/client";
import { Button, Card } from "./ui";

export function Upload({ onSession }: { onSession: (id: string) => void }) {
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const recent = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });

  async function send(file: File) {
    setError(null);
    setProgress(0);
    try {
      const res = await api.upload(file, setProgress);
      onSession(res.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <Card>
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const f = e.dataTransfer.files[0];
            if (f) void send(f);
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-14 text-center transition ${
            drag
              ? "border-brand-500 bg-brand-50"
              : "border-slate-300 hover:border-brand-500 hover:bg-brand-50/40"
          }`}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-10 w-10 text-brand-600"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            aria-hidden="true"
          >
            <path
              d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="text-base font-semibold">Перетащите JSON-файл с адресами</div>
          <div className="text-sm text-slate-500">
            формат как у <code className="rounded bg-slate-100 px-1">sample_input.json</code>: записи{" "}
            <code className="rounded bg-slate-100 px-1">{"{id, raw_address}"}</code>
          </div>
          <Button variant="primary" onClick={() => input.current?.click()}>
            Выбрать файл
          </Button>
          <input
            ref={input}
            type="file"
            accept=".json,.jsonl,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void send(f);
              e.target.value = "";
            }}
          />
          {progress !== null && (
            <div className="w-full max-w-sm">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full bg-brand-500 transition-all"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
              <div className="mt-1 text-xs text-slate-500">загрузка {Math.round(progress * 100)}%</div>
            </div>
          )}
          {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        </label>
      </Card>

      {recent.data && recent.data.length > 0 && (
        <Card title="Предыдущие пакеты">
          <ul className="divide-y divide-slate-100">
            {recent.data.slice(0, 8).map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onSession(s.id)}
                  className="flex w-full items-center justify-between gap-3 px-1 py-2 text-left text-sm hover:bg-slate-50"
                >
                  <span className="truncate font-medium">{s.name}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {s.total} записей · {new Date(s.created_at * 1000).toLocaleString("ru-RU")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
