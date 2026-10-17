import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { type SessionBrief, api } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import { IconAlert, IconChevronRight, IconFile, IconTrash, IconUpload } from "./icons";
import { Button, Card, ProgressBar, Skeleton } from "./ui";

const SAMPLE = `[
  { "id": "1", "raw_address": "г. Алматы, мкр Аксай-3а, 59, кв 70" },
  { "id": "2", "raw_address": "Туран 55/6 магазин береке 4подьезд 9этаж" }
]`;

function RecentRow({ s, i, onOpen }: { s: SessionBrief; i: number; onOpen: () => void }) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [removing, setRemoving] = useState(false);
  const processing = s.status === "processing";

  // второе нажатие в течение 3 с подтверждает удаление
  useEffect(() => {
    if (!confirm) return;
    const timer = setTimeout(() => setConfirm(false), 3000);
    return () => clearTimeout(timer);
  }, [confirm]);

  async function remove() {
    setRemoving(true);
    try {
      await Promise.all([api.deleteSession(s.id), new Promise((r) => setTimeout(r, 240))]);
      await qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(t("batchDeleted"));
    } catch (e) {
      setRemoving(false);
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  }

  return (
    <li
      className={`reveal stagger animate-fade-up transition-opacity duration-200 ${removing ? "opacity-0" : ""}`}
      data-open={!removing}
      style={{ "--i": i } as React.CSSProperties}
    >
      <div>
        <div className="group flex items-center gap-3 rounded-2xl px-2 py-2 transition-colors hover:bg-canvas">
          <button
            type="button"
            onClick={onOpen}
            className="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline-none"
          >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700 transition-transform duration-200 group-hover:scale-105">
              <IconFile className="h-5 w-5" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-ink">{s.name}</span>
              <span className="block text-xs text-ink-3">
                {t("recordsCount", { total: s.total })} ·{" "}
                {new Date(s.created_at * 1000).toLocaleString(locale)}
              </span>
            </span>
            {processing ? (
              <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-warn-50 px-2 py-0.5 text-[11px] font-semibold text-warn-800">
                <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-warn" />
                {t("statusProcessing")}
              </span>
            ) : (
              <span className="hidden shrink-0 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 sm:inline">
                {t("statusDone")}
              </span>
            )}
            <IconChevronRight className="h-4 w-4 shrink-0 text-ink-3 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-brand-600" />
          </button>
          {confirm ? (
            <Button
              size="sm"
              variant="danger"
              onClick={remove}
              loading={removing}
              className="animate-scale-in"
            >
              {t("deleteConfirm")}
            </Button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirm(true)}
              title={t("deleteBatch")}
              aria-label={t("deleteBatch")}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-xl text-ink-3 opacity-60 transition hover:bg-danger-50 hover:text-danger group-hover:opacity-100"
            >
              <IconTrash />
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

export function Upload({ onSession }: { onSession: (id: string) => void }) {
  const { t } = useI18n();
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
    <div className="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-4 pt-2 sm:pt-6">
      <div className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("uploadTitle")}</h1>
        <p className="mt-1.5 text-sm text-ink-2 sm:text-base">{t("uploadSubtitle")}</p>
      </div>
      <Card className="animate-fade-up [animation-delay:60ms]">
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
          className={`group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 text-center transition duration-200 ${
            drag
              ? "scale-[1.01] border-brand-600 bg-brand-50"
              : "border-line hover:border-brand-300 hover:bg-brand-50/50"
          }`}
        >
          <span
            className={`grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 transition duration-200 group-hover:-translate-y-0.5 ${
              drag ? "animate-bob bg-white" : ""
            }`}
          >
            <IconUpload className="h-7 w-7" />
          </span>
          <div className="text-base font-semibold">{drag ? t("dropRelease") : t("dropTitle")}</div>
          <div className="text-sm text-ink-2">
            {t("dropHintPre")}
            <code className="rounded-md bg-canvas px-1.5 py-px font-mono text-[13px]">sample_input.json</code>
            {t("dropHintMid")}
            <code className="rounded-md bg-canvas px-1.5 py-px font-mono text-[13px]">
              {"{id, raw_address}"}
            </code>
            {t("dropHintPost")}
          </div>
          <Button
            variant="primary"
            icon={<IconUpload />}
            loading={progress !== null}
            onClick={(e) => {
              e.preventDefault();
              input.current?.click();
            }}
          >
            {t("selectFile")}
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
            <div className="w-full max-w-sm animate-fade-in">
              <ProgressBar value={progress} className="h-2" />
              <div className="mt-1 text-xs tabular-nums text-ink-3">
                {t("uploadProgress", { pct: Math.round(progress * 100) })}
              </div>
            </div>
          )}
          {error && (
            <div className="inline-flex animate-fade-up items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger">
              <IconAlert className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
        </label>
        <details className="group/d mt-3 text-sm">
          <summary className="inline-flex cursor-pointer select-none items-center gap-1 rounded-lg px-1 text-xs font-medium text-brand-700 hover:underline">
            <IconChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-open/d:rotate-90" />
            {t("formatExample")}
          </summary>
          <pre className="mt-2 animate-fade-in overflow-x-auto rounded-xl bg-ink p-3 font-mono text-xs leading-relaxed text-white/90">
            {SAMPLE}
          </pre>
        </details>
      </Card>

      {recent.isLoading && (
        <Card>
          <div className="space-y-2">
            <Skeleton className="h-12 w-full rounded-2xl" />
            <Skeleton className="h-12 w-full rounded-2xl" />
          </div>
        </Card>
      )}
      {recent.data && recent.data.length > 0 && (
        <Card title={t("recentBatches")} className="animate-fade-up [animation-delay:120ms]">
          <ul className="-mx-2 grid">
            {recent.data.slice(0, 8).map((s, i) => (
              <RecentRow key={s.id} s={s} i={i} onOpen={() => onSession(s.id)} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
