import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState } from "react";
import { ApiError, api } from "./api/client";
import { CheckOne } from "./components/CheckOne";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LangSwitcher } from "./components/LangSwitcher";
import { SessionView } from "./components/SessionView";
import { Settings } from "./components/Settings";
import { Upload } from "./components/Upload";
import { DEMO_TEXTS } from "./components/demo/texts";
import { Segmented, Skeleton } from "./components/ui";
import { useI18n } from "./i18n";
import { useDebounced } from "./lib/motion";
import { useThresholdSetting } from "./lib/settings";
import { confirmLeave, useBeforeUnload } from "./lib/unsaved";

// демо отдельным чанком: сцена и отчёт не нужны, пока вкладку не открыли
const DemoPage = lazy(() => import("./components/demo/DemoPage").then((m) => ({ default: m.DemoPage })));

type Tab = "batch" | "check" | "demo";

const SID_KEY = "jana_address_sid";

function readHash(): { tab: Tab; sid: string | null } {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("check")) return { tab: "check", sid: null };
  if (h.startsWith("demo")) return { tab: "demo", sid: null };
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
  const { t, language } = useI18n();
  const [tab, setTab] = useState(() => readHash().tab);
  // демо, раз открытое, остаётся смонтированным: переключение вкладок не сбрасывает показ
  const [demoSeen, setDemoSeen] = useState(tab === "demo");
  useEffect(() => {
    if (tab === "demo") setDemoSeen(true);
  }, [tab]);
  // пакет живёт отдельно от адреса: в #/check его нет, но вкладка «Пакет» должна вернуть к нему, а не к загрузке
  const [sid, setSid] = useState(() => {
    const r = readHash();
    return r.tab === "batch" ? r.sid : loadSid();
  });
  // 503 у health значит «справочник ещё грузится», а не «сервис недоступен»
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: (q) => (q.state.data?.status === "ok" ? 15000 : 2000),
  });
  const cfg = useQuery({ queryKey: ["config"], queryFn: api.config });
  const defaultThreshold = cfg.data?.uncertain_threshold ?? 0.95;
  // порог из настроек; пока ползунок двигают, пакет не перезапрашиваем на каждый процент
  const chosen = useThresholdSetting();
  const threshold = useDebounced(chosen ?? defaultThreshold, 200);
  // тот же ключ, что в SessionView: кэш общий, лишних запросов нет
  const session = useQuery({
    queryKey: ["session", sid, threshold],
    queryFn: () => api.session(sid ?? "", threshold),
    // при смене порога значок вкладки не мигает; другого пакета данные не подставляем
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === sid ? prev : undefined),
    enabled: !!sid,
  });

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
  useBeforeUnload();
  const nav = (hash: string) => {
    window.location.hash = hash;
  };

  const warming = health.error instanceof ApiError && health.error.status === 503;
  const status =
    health.data?.status === "ok" && !health.isError ? "ok" : health.isError && !warming ? "down" : "loading";
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-line bg-canvas">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          {/* biome-ignore lint/a11y/useValidAnchor: настоящая ссылка, onClick только спрашивает про черновик */}
          <a
            href="#/"
            onClick={(e) => {
              // логотип уводит со страницы пакета: несохранённую правку молча не теряем
              if (!confirmLeave(t("leaveConfirm"))) e.preventDefault();
            }}
            className="group inline-flex items-center gap-2.5 rounded-xl bg-white py-1.5 pr-3 pl-1.5 font-semibold tracking-tight ring-1 ring-line transition hover:ring-brand-200"
          >
            <span className="relative">
              <img
                src="/favicon.svg"
                alt=""
                className="h-7 w-7 rounded-lg transition-transform duration-300 group-hover:-rotate-6"
              />
              {/* на узком экране чип статуса не помещается: точка на логотипе, только при проблеме */}
              {status !== "ok" && (
                <span
                  className={`absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-white sm:hidden ${
                    status === "down" ? "bg-danger" : "animate-pulse-dot bg-warn"
                  }`}
                />
              )}
            </span>
            <span>
              Jana <span className="text-brand-600">Address</span>
            </span>
          </a>
          <Segmented<Tab>
            className="order-last w-full sm:order-none sm:w-auto [&>button]:flex-1 [&>button]:justify-center sm:[&>button]:flex-none"
            ariaLabel={t("appTitle")}
            value={tab}
            onChange={(k) => nav(k === "batch" ? (sid ? `#/s/${sid}` : "#/") : `#/${k}`)}
            options={[
              {
                value: "batch",
                label: t("navBatch"),
                badge: sid ? (session.data?.summary.to_review ?? null) : null,
              },
              { value: "check", label: t("navCheck") },
              { value: "demo", label: DEMO_TEXTS[language].nav },
            ]}
          />
          <div className="ml-auto flex items-center gap-2">
            <LangSwitcher />
            <Settings fallback={defaultThreshold} />
            {/* в рабочем состоянии статус не показываем: только загрузку и недоступность */}
            {status !== "ok" && (
              <span className="hidden h-8 animate-fade-in items-center gap-1.5 rounded-full border border-line bg-white px-3 text-xs text-ink-2 sm:inline-flex">
                <span
                  className={`h-2 w-2 rounded-full ${status === "down" ? "bg-danger" : "animate-pulse-dot bg-warn"}`}
                />
                <span>{status === "down" ? t("serviceUnavailable") : t("serviceLoading")}</span>
              </span>
            )}
          </div>
        </div>
      </header>
      {/* обе вкладки смонтированы, неактивная скрыта: переключение не теряет разбор, фильтры, выбор и черновик */}
      {/* прокручивается область между шапкой и футером, таблица пакета скроллится внутри себя */}
      <div className="min-h-0 flex-1 overflow-auto">
        <main className="mx-auto h-full w-full max-w-[1600px] p-4">
          <div className={tab === "check" ? "animate-fade-in" : "hidden"}>
            <ErrorBoundary resetKey={tab}>
              <CheckOne threshold={threshold} />
            </ErrorBoundary>
          </div>
          <div className={tab === "demo" ? "animate-fade-in" : "hidden"}>
            <ErrorBoundary resetKey={tab}>
              {/* до первого открытия вкладки чанк демо не грузим */}
              {(tab === "demo" || demoSeen) && (
                <Suspense fallback={<Skeleton className="mx-auto h-80 w-full max-w-6xl rounded-[24px]" />}>
                  <DemoPage threshold={threshold} active={tab === "demo"} />
                </Suspense>
              )}
            </ErrorBoundary>
          </div>
          <div className={tab === "batch" ? "h-full animate-fade-in" : "hidden"}>
            <ErrorBoundary resetKey={`${tab}:${sid ?? ""}`}>
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
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <footer className="shrink-0 border-t border-line px-4 py-2 text-center text-[11px] text-ink-3">
        <a
          href="https://www.openstreetmap.org/copyright"
          target="_blank"
          rel="noreferrer"
          className="transition-colors hover:text-brand-700 hover:underline"
        >
          {t("osmAttribution")}
        </a>
      </footer>
    </div>
  );
}
