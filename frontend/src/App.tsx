import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api/client";
import { CheckOne } from "./components/CheckOne";
import { LangSwitcher } from "./components/LangSwitcher";
import { SessionView } from "./components/SessionView";
import { Upload } from "./components/Upload";
import { useI18n } from "./i18n";

type Tab = "batch" | "check";

const SID_KEY = "jana_address_sid";

function readHash(): { tab: Tab; sid: string | null } {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("check")) return { tab: "check", sid: null };
  const m = h.match(/^s\/([\w-]+)/);
  return { tab: "batch", sid: m?.[1] ?? null };
}

// открытый пакет переживает и перезагрузку страницы на #/check
function loadSid(): string | null {
  try {
    return sessionStorage.getItem(SID_KEY);
  } catch {
    return null;
  }
}

function storeSid(sid: string | null): void {
  try {
    if (sid) sessionStorage.setItem(SID_KEY, sid);
    else sessionStorage.removeItem(SID_KEY);
  } catch {
    /* sessionStorage недоступен */
  }
}

export function App() {
  const { t } = useI18n();
  const [tab, setTab] = useState(() => readHash().tab);
  // пакет живёт отдельно от адреса: в #/check его нет, но вкладка «Пакет» должна вернуть к нему, а не к загрузке
  const [sid, setSid] = useState(() => {
    const r = readHash();
    return r.tab === "batch" ? r.sid : loadSid();
  });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 });
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const threshold = cfg.data?.uncertain_threshold ?? 0.6;

  useEffect(() => {
    const on = () => {
      const r = readHash();
      setTab(r.tab);
      if (r.tab === "batch") setSid(r.sid);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => storeSid(sid), [sid]);
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
                ["batch", t("navBatch"), sid ? `#/s/${sid}` : "#/"],
                ["check", t("navCheck"), "#/check"],
              ] as const
            ).map(([tKey, label, href]) => (
              <button
                type="button"
                key={tKey}
                onClick={() => nav(href)}
                className={`rounded-md px-3 py-1 ${tab === tKey ? "bg-white text-brand-800" : "text-white/90 hover:bg-white/10"}`}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <LangSwitcher />
            <span
              className="inline-flex items-center gap-1.5 text-xs text-white/90"
              title={t("serviceTitle")}
            >
              <span className={`h-2 w-2 rounded-full ${ok ? "bg-lime-300" : "bg-amber-300"}`} />
              {ok ? t("serviceReady") : t("serviceLoading")}
            </span>
          </div>
        </div>
      </header>
      {/* обе вкладки смонтированы, неактивная скрыта: переключение не теряет разбор, фильтры, выбор и черновик */}
      <main className="mx-auto min-h-0 w-full max-w-[1600px] flex-1 p-4">
        <div className={tab === "check" ? "" : "hidden"}>
          <CheckOne threshold={threshold} />
        </div>
        <div className={tab === "batch" ? "h-full" : "hidden"}>
          {sid ? (
            <SessionView
              key={sid}
              sid={sid}
              threshold={threshold}
              active={tab === "batch"}
              onBack={() => nav("#/")}
            />
          ) : (
            <Upload onSession={(id) => nav(`#/s/${id}`)} />
          )}
        </div>
      </main>
    </div>
  );
}
