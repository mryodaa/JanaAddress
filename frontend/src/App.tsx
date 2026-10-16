import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api/client";
import { CheckOne } from "./components/CheckOne";
import { SessionView } from "./components/SessionView";
import { Upload } from "./components/Upload";

type Tab = "batch" | "check";

function readHash(): { tab: Tab; sid: string | null } {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("check")) return { tab: "check", sid: null };
  const m = h.match(/^s\/([\w-]+)/);
  return { tab: "batch", sid: m?.[1] ?? null };
}

export function App() {
  const [{ tab, sid }, setRoute] = useState(readHash);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 });
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const threshold = cfg.data?.uncertain_threshold ?? 0.6;

  useEffect(() => {
    const on = () => setRoute(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const nav = (hash: string) => {
    window.location.hash = hash;
  };

  const ok = health.data?.status === "ok";
  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-brand-700 bg-brand-600 text-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <a href="#/" className="flex items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-7 w-7 rounded-md ring-1 ring-white/40" />
            Jana Address
          </a>
          <nav className="flex gap-1 text-sm">
            {(
              [
                ["batch", "Пакет", sid ? `#/s/${sid}` : "#/"],
                ["check", "Проверить строку", "#/check"],
              ] as const
            ).map(([t, label, href]) => (
              <button
                type="button"
                key={t}
                onClick={() => nav(href)}
                className={`rounded-md px-3 py-1 ${tab === t ? "bg-white text-brand-800" : "text-white/90 hover:bg-white/10"}`}
              >
                {label}
              </button>
            ))}
          </nav>
          <span
            className="ml-auto inline-flex items-center gap-1.5 text-xs text-white/90"
            title="справочник загружен"
          >
            <span className={`h-2 w-2 rounded-full ${ok ? "bg-lime-300" : "bg-amber-300"}`} />
            {ok ? "сервис готов · офлайн" : "загрузка…"}
          </span>
        </div>
      </header>
      <main className="mx-auto min-h-0 w-full max-w-[1600px] flex-1 p-4">
        {tab === "check" ? (
          <CheckOne threshold={threshold} />
        ) : sid ? (
          <SessionView sid={sid} threshold={threshold} onBack={() => nav("#/")} />
        ) : (
          <Upload onSession={(id) => nav(`#/s/${id}`)} />
        )}
      </main>
    </div>
  );
}
