import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, type RefObject, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { type ExplainRecord, api } from "../../api/client";
import { useI18n } from "../../i18n";
import { errorText } from "../../lib/errors";
import { visible } from "../../lib/fields";
import { isModalOpen, typingIn, useWindowKey } from "../../lib/keys";
import { prefersReducedMotion } from "../../lib/motion";
import { IconAlert, IconCheck, IconChevronRight, IconCollapse, IconExpand } from "../icons";
import { Button, TextInput } from "../ui";
import { Analysis } from "./Analysis";
import { type HealthInfo, StageView } from "./Theater";
import { derive, ticksOf } from "./derive";
import { DEMO_TEXTS, type StageId, fmt } from "./texts";

const STAGES: StageId[] = [
  "input",
  "clean",
  "tokens",
  "bilingual",
  "rules",
  "tagger",
  "arbiter",
  "reference",
  "confidence",
  "output",
];
// темп демонстрации, не реального разбора: один «тик» анимации при скорости 1×
const TICK_MS = 750;
const SPEEDS = [0.5, 1, 2] as const;

// невидимый символ собираем кодом: в исходниках только escape-последовательности
const ZWSP = String.fromCharCode(0x200b);
const EXAMPLES = [
  `г.Алматы,${ZWSP}  мкр.Самал-2  д.5  кв.12  4подьезд`,
  "город Актобе/Ақтөбе қаласы, проспект Абилкайыр хана 52, кв 14",
  "Fkvfns? ek/ f,fz 10",
  "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
  "ТОО Ромашка, г. Астана, пр. Мангилик Ел 55/1 БЦ Изумрудный квартал, офис 5",
  "Туран 55/6 магазин береке 4подьезд 9этаж",
];

const ICON_PATH: Record<StageId, ReactNode> = {
  clean: <path d="M4 20h16M7 16l9-9 3 3-9 9H7zM14 5l3 3" />,
  tokens: (
    <>
      <rect x="3" y="7" width="5" height="10" rx="1.5" />
      <rect x="10" y="7" width="4" height="10" rx="1.5" />
      <rect x="16" y="7" width="5" height="10" rx="1.5" />
    </>
  ),
  bilingual: <path d="M4 6h8M8 4v2m2.5 0C10 10 7 13 4 14m3-4c1 2 3 3.5 5 4M13 20l4-9 4 9m-6.5-3h5" />,
  rules: <path d="M6 4h9l3 3v13H6zM9 10h6M9 14h6M9 18h3" />,
  tagger: (
    <>
      <circle cx="6" cy="7" r="2" />
      <circle cx="6" cy="17" r="2" />
      <circle cx="18" cy="12" r="2" />
      <path d="M8 7.5l8 3.5M8 16.5l8-3.5M12 4v16" />
    </>
  ),
  arbiter: <path d="M12 4v16M6 20h12M5 8h14M5 8l-2.5 6a2.5 2.5 0 0 0 5 0zM19 8l-2.5 6a2.5 2.5 0 0 0 5 0z" />,
  reference: (
    <>
      <ellipse cx="12" cy="5.5" rx="7" ry="2.5" />
      <path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" />
    </>
  ),
  confidence: <path d="M4 16a8 8 0 1 1 16 0M12 16l4-5M3 20h18" />,
  // фигурные скобки JSON со стрелкой внутрь и наружу
  input: <path d="M8 4C6 4 5 5 5 7v2c0 1.5-1 3-2 3 1 0 2 1.5 2 3v2c0 2 1 3 3 3M13 12h8M18 9l3 3-3 3" />,
  output: <path d="M16 4c2 0 3 1 3 3v2c0 1.5 1 3 2 3-1 0-2 1.5-2 3v2c0 2-1 3-3 3M3 12h8M8 9l3 3-3 3" />,
};

function StageIcon({ id, className = "h-5 w-5" }: { id: StageId; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICON_PATH[id]}
    </svg>
  );
}

export function DemoPage({ threshold, active }: { threshold: number; active: boolean }) {
  const { t, language } = useI18n();
  const tx = DEMO_TEXTS[language];
  const [text, setText] = useState(EXAMPLES[0] ?? "");
  const [r, setR] = useState<ExplainRecord | null>(null);
  const [phase, setPhase] = useState<"idle" | "play" | "done">("idle");
  const [stage, setStage] = useState(0);
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [autoNext, setAutoNext] = useState(readAutoNext);
  const toggleAuto = () =>
    setAutoNext((v) => {
      saveAutoNext(!v);
      return !v;
    });
  const top = useRef<HTMLDivElement>(null);
  const nav = useRef<HTMLElement>(null);
  const [full, toggleFull] = useFullscreen(top);
  // 10 этапов не помещаются в строку: текущий этап всегда виден, навигация прокручивается к нему сама
  // (только по горизонтали, страница не дёргается)
  // biome-ignore lint/correctness/useExhaustiveDependencies: phase нужен, навигация появляется только при показе
  useEffect(() => {
    const box = nav.current;
    const el = box?.querySelector<HTMLElement>(`[data-stage="${stage}"]`);
    if (!box || !el) return;
    const left = el.offsetLeft - box.clientWidth / 2 + el.offsetWidth / 2;
    box.scrollTo({ left, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [stage, phase]);

  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const f1 = health.data?.tagger?.metrics?.unseen_span_f1;
  const h: HealthInfo = {
    counts: health.data?.reference?.counts,
    houses: health.data?.reference?.houses ?? undefined,
    f1: typeof f1 === "number" ? f1 : undefined,
    version: health.data?.tagger?.version ?? undefined,
  };

  const d = useMemo(() => (r ? derive(r) : null), [r]);
  const ticks = useMemo(() => (d ? ticksOf(d) : null), [d]);
  const id = STAGES[stage] ?? "clean";
  const maxTick = ticks?.[id] ?? 1;

  // показываем ответ только на последний запрошенный адрес: быстрый клик по двум примерам не должен
  // показать первый, если он пришёл позже второго
  const wanted = useRef("");
  const parse = useMutation({
    mutationFn: api.parseOne,
    onSuccess: (res, q) => {
      if (q !== wanted.current) return;
      setR(res);
      start();
    },
  });
  const run = (q: string) => {
    wanted.current = q;
    parse.mutate(q);
  };

  // ссылка «Как это разобрано» со страницы проверки: #/demo?q=<адрес> подставляет адрес и сразу запускает показ
  const runFromHash = useRef<() => void>(() => undefined);
  runFromHash.current = () => {
    const m = window.location.hash.match(/^#\/?demo\?q=(.*)$/);
    if (!m) return;
    // убираем q из адреса: перезагрузка страницы не должна снова запускать показ
    window.history.replaceState(null, "", "#/demo");
    let q = "";
    try {
      q = decodeURIComponent(m[1] ?? "");
    } catch {
      return; // битая ссылка (%E0 и т. п.): просто открываем демо без запуска
    }
    if (!q.trim()) return;
    setText(q);
    run(q);
  };
  useEffect(() => {
    const on = () => runFromHash.current();
    on();
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // сцена встаёт на место строки ввода: страница не прокручивается и не прыгает
  function toTop() {
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    requestAnimationFrame(() => top.current?.scrollIntoView({ behavior, block: "start" }));
  }

  function start() {
    setStage(0);
    // без анимаций сразу последний кадр каждого этапа
    setTick(0);
    setPlaying(true);
    setPhase("play");
    toTop();
  }

  function finish() {
    setPhase("done");
    toTop();
  }

  function reset() {
    setPhase("idle");
    toTop();
  }

  function goStage(i: number) {
    if (i >= STAGES.length) return finish();
    setStage(Math.max(0, i));
    setTick(0);
  }

  // таймер демонстрации: тики внутри этапа, на последнем тике пауза подольше, потом следующий этап.
  // Без автоперехода этап доигрывает анимацию и ждёт «дальше»
  // на скрытой вкладке показ стоит на месте и продолжается, когда к нему вернутся
  const waiting = phase === "play" && playing && !autoNext && tick >= maxTick;
  const goNext = useRef<() => void>(() => undefined);
  goNext.current = () => goStage(stage + 1);
  useEffect(() => {
    if (!active || phase !== "play" || !playing || waiting) return;
    const reduced = prefersReducedMotion();
    const hold = tick >= maxTick;
    const ms = (TICK_MS / speed) * (hold ? 2.2 : reduced ? 0.4 : 1);
    const timer = setTimeout(() => {
      if (!hold) setTick(reduced ? maxTick : tick + 1);
      else goNext.current();
    }, ms);
    return () => clearTimeout(timer);
  }, [active, phase, playing, waiting, tick, maxTick, speed]);

  // пробел пауза, стрелки по этапам; не мешаем вводу
  useWindowKey(
    (e) => {
      if (typingIn(e) || isModalOpen()) return;
      if (e.key === " ") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.key === "a" || e.key === "ф") toggleAuto();
      else if (e.key === "ArrowRight") goStage(stage + 1);
      else if (e.key === "ArrowLeft") goStage(stage - 1);
      // Esc в полноэкранном режиме закрывает его (это делает браузер), а не показ
      else if (e.key === "Escape" && !document.fullscreenElement) finish();
    },
    active && phase === "play",
  );
  // F: на весь экран и обратно, на всех фазах демо
  useWindowKey((e) => {
    if (!toggleFull || typingIn(e) || isModalOpen() || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "f" || e.key === "F" || e.key === "а" || e.key === "А") toggleFull();
  }, active);
  const fullBtn = toggleFull && (
    <button
      type="button"
      onClick={toggleFull}
      title={full ? tx.exitFullscreen : tx.fullscreen}
      aria-label={full ? tx.exitFullscreen : tx.fullscreen}
      aria-pressed={full}
      className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-2 transition hover:bg-canvas hover:text-ink active:scale-90"
    >
      {full ? <IconCollapse className="h-4 w-4" /> : <IconExpand className="h-4 w-4" />}
    </button>
  );

  const progress = (stage + Math.min(1, tick / Math.max(1, maxTick))) / STAGES.length;
  const st = tx.stages[id];

  return (
    <div
      ref={top}
      // на весь экран: фон страницы и своя прокрутка (отчёт длиннее экрана), сцена во всю высоту
      className={`mx-auto grid grid-cols-[minmax(0,1fr)] gap-5 ${
        full
          ? "h-full max-w-none content-start overflow-y-auto bg-canvas p-3 sm:p-5"
          : "max-w-6xl scroll-mt-4 pt-2 sm:pt-4"
      }`}
    >
      {/* ввод: только до запуска, дальше на его месте сцена */}
      {(phase === "idle" || !d) && (
        <section className="relative animate-fade-up overflow-clip rounded-[24px] border border-line bg-white p-5 sm:p-8">
          <div className="pointer-events-none absolute -top-24 -right-24 h-72 w-72 rounded-full bg-brand-50" />
          <div className="pointer-events-none absolute -bottom-28 right-40 h-56 w-56 rounded-full bg-warn-50" />
          <div className="relative">
            <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">{tx.title}</h1>
            <p className="mt-2 max-w-2xl text-sm text-ink-2 sm:text-base">{tx.subtitle}</p>
            <form
              className="mt-6 flex flex-col gap-2 sm:flex-row"
              onSubmit={(e) => {
                e.preventDefault();
                if (text.trim()) run(text);
              }}
            >
              <TextInput
                value={text}
                onChange={setText}
                placeholder={tx.placeholder}
                size="lg"
                className="flex-1"
              />
              <Button
                variant="primary"
                type="submit"
                loading={parse.isPending}
                disabled={!text.trim()}
                className="h-12 px-6"
                icon={<IconChevronRight />}
              >
                {tx.run}
              </Button>
            </form>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs text-ink-3">{tx.examples}</span>
              {EXAMPLES.map((ex) => (
                <button
                  type="button"
                  key={ex}
                  onClick={() => {
                    setText(ex);
                    run(ex);
                  }}
                  className={`max-w-full truncate rounded-full border px-3 py-1 text-xs transition duration-150 active:scale-95 ${
                    ex === text
                      ? "border-brand-600 bg-brand-50 text-brand-800"
                      : "border-line bg-white text-ink-2 hover:border-brand-200 hover:bg-brand-50 hover:text-brand-800"
                  }`}
                >
                  {visible(ex)}
                </button>
              ))}
            </div>
            {parse.error && (
              <div className="mt-3 inline-flex items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger">
                <IconAlert className="h-4 w-4" /> {errorText(parse.error, t, language)}
              </div>
            )}
          </div>
        </section>
      )}

      {/* сцена */}
      {d && phase === "play" && (
        <section
          className={`animate-fade-up overflow-hidden rounded-[24px] border border-line bg-white shadow-sm ${
            full ? "flex h-[calc(100dvh-1.5rem)] flex-col sm:h-[calc(100dvh-2.5rem)]" : ""
          }`}
        >
          <div className="h-1 shrink-0 bg-line-soft">
            <div
              className="h-full bg-brand-500 transition-[width] duration-500 ease-[var(--ease-out-soft)]"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
          <AddressBar raw={d.raw} label={tx.another} onBack={reset} extra={fullBtn} />
          <nav
            ref={nav}
            className="flex shrink-0 gap-1 overflow-x-auto border-t border-line-soft px-3 py-3 [scrollbar-width:none] sm:px-5"
          >
            {STAGES.map((s, i) => {
              const done = i < stage;
              const cur = i === stage;
              return (
                <button
                  key={s}
                  type="button"
                  data-stage={i}
                  onClick={() => goStage(i)}
                  className={`inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition duration-300 ${
                    cur
                      ? "bg-brand-600 text-white"
                      : done
                        ? "text-ink-2 hover:bg-canvas"
                        : "text-ink-3 hover:bg-canvas"
                  }`}
                >
                  <span
                    className={`grid h-5 w-5 place-items-center rounded-full text-[0.625rem] font-bold ${
                      cur ? "bg-white text-brand-700" : done ? "bg-brand-100 text-brand-800" : "bg-line-soft"
                    }`}
                  >
                    {done ? <IconCheck className="h-3 w-3" /> : i + 1}
                  </span>
                  {tx.stages[s].title}
                </button>
              );
            })}
          </nav>

          {/* высота сцены фиксирована на всех этапах: длинное содержимое прокручивается внутри */}
          <div
            className={`grid gap-6 border-t border-line-soft p-5 sm:p-7 lg:grid-cols-[23rem_minmax(0,1fr)] ${
              full ? "min-h-0 flex-1 overflow-y-auto lg:overflow-visible" : "lg:h-[34rem]"
            }`}
          >
            <FitBox
              key={`info-${id}`}
              fitKey={`${id}|${language}|${full}`}
              className="order-2 animate-fade-up lg:order-none"
            >
              <div className="text-xs font-semibold uppercase tracking-wider text-brand-700">
                {fmt(tx.stageOf, { n: stage + 1, total: STAGES.length })}
              </div>
              <h2 className="mt-1 text-3xl font-semibold tracking-tight">{st.title}</h2>
              <p className="mt-3 text-sm leading-relaxed text-ink-2">{st.lead}</p>
              <div className="mt-4 rounded-2xl bg-canvas p-4 ring-1 ring-line-soft">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700">
                    <StageIcon id={id} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[0.625rem] font-semibold uppercase tracking-wider text-ink-3">
                      {tx.tool}
                    </span>
                    <span className="block font-semibold leading-snug">{st.tool}</span>
                  </span>
                </div>
                <div className="mt-3 border-t border-line-soft pt-3">
                  <div className="mb-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-ink-3">
                    {tx.toolHow}
                  </div>
                  <ul className="grid gap-1.5">
                    {st.toolPoints.map((p) => (
                      <li key={p} className="flex gap-2 text-xs leading-snug text-ink-2">
                        <span className="mt-[0.35rem] h-1 w-1 shrink-0 rounded-full bg-brand-500" />
                        <span>{fmt(p, { th: Math.round(threshold * 100) })}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </FitBox>
            <div
              key={`stage-${id}`}
              className={`min-w-0 animate-fade-in overflow-y-auto rounded-2xl bg-white p-5 ring-1 ring-line [scrollbar-width:thin] sm:p-6 lg:h-full ${
                full ? "min-h-[28rem] lg:min-h-0" : "h-[28rem]"
              }`}
            >
              <StageView id={id} tick={tick} d={d} tx={tx} health={h} />
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-line-soft px-5 py-3">
            <StageBtn onClick={() => goStage(stage - 1)} disabled={stage === 0} label={tx.prev}>
              <path d="m15 6-6 6 6 6" />
            </StageBtn>
            <StageBtn onClick={() => setPlaying((p) => !p)} label={playing ? tx.pause : tx.play} primary>
              {playing ? <path d="M9 6v12M15 6v12" /> : <path d="M8 5.5v13l10-6.5z" />}
            </StageBtn>
            <StageBtn onClick={() => goStage(stage + 1)} label={tx.next} attention={waiting}>
              <path d="m9 6 6 6-6 6" />
            </StageBtn>
            <div className="ml-2 inline-flex items-center gap-1 rounded-full bg-canvas p-0.5 text-xs ring-1 ring-line-soft">
              <span className="px-2 text-ink-3">{tx.speed}</span>
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpeed(s)}
                  className={`rounded-full px-2.5 py-1 font-semibold transition ${speed === s ? "bg-white text-ink shadow-sm ring-1 ring-line" : "text-ink-3 hover:text-ink"}`}
                >
                  {s}×
                </button>
              ))}
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={autoNext}
              onClick={toggleAuto}
              title={tx.autoNextHint}
              className="inline-flex items-center gap-2 rounded-full px-2 py-1 text-xs font-medium text-ink-2 transition hover:bg-canvas"
            >
              <span
                className={`relative h-4 w-7 rounded-full transition-colors duration-200 ${autoNext ? "bg-brand-600" : "bg-line"}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-transform duration-200 ${autoNext ? "translate-x-3" : ""}`}
                />
              </span>
              {tx.autoNext}
            </button>
            {waiting ? (
              <span className="animate-fade-in text-xs text-brand-700">{tx.waitNext}</span>
            ) : (
              <span className="hidden text-xs text-ink-3 xl:inline">{tx.demoNote}</span>
            )}
            <button
              type="button"
              onClick={finish}
              className="ml-auto inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold text-brand-700 transition hover:bg-brand-50"
            >
              {tx.skip}
              <IconChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </section>
      )}

      {/* отчёт */}
      {d && r && phase === "done" && (
        <>
          <section className="animate-fade-up overflow-hidden rounded-[24px] border border-line bg-white shadow-sm">
            <AddressBar raw={d.raw} label={tx.another} onBack={reset} extra={fullBtn} />
          </section>
          <Analysis r={r} d={d} tx={tx} health={h} threshold={threshold} />
          <div className="flex flex-wrap justify-center gap-2 pb-6">
            <Button variant="primary" onClick={start}>
              {tx.replay}
            </Button>
            <Button onClick={reset}>{tx.another}</Button>
          </div>
        </>
      )}
    </div>
  );
}

// разбираемый адрес над сценой вместо строки ввода; кнопка возвращает к вводу
function AddressBar({
  raw,
  label,
  onBack,
  extra,
}: { raw: string; label: string; onBack: () => void; extra?: ReactNode }) {
  return (
    <div className="flex shrink-0 items-center gap-3 px-5 py-3 sm:px-7">
      <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink sm:text-base" title={visible(raw)}>
        {visible(raw)}
      </span>
      {extra}
      <Button size="sm" onClick={onBack} className="shrink-0">
        {label}
      </Button>
    </div>
  );
}

// экран, под который свёрстана сцена: на большем всё увеличивается пропорционально, как слайд
const STAGE_W = 1200;
const STAGE_H = 760;
const MAX_SCALE = 1.8;

/**
 * Полноэкранный режим элемента (для показа на проекторе). Без Fullscreen API (iPhone) переключателя нет: null.
 * Состояние берётся из события браузера: выход по Esc тоже его меняет. На весь экран растёт корневой шрифт:
 * вёрстка в rem, поэтому текст, отступы и элементы увеличиваются вместе (брейкпоинты в rem от него не зависят).
 */
function useFullscreen(ref: RefObject<HTMLElement | null>): [boolean, (() => void) | null] {
  const [full, setFull] = useState(false);
  useEffect(() => {
    const on = () => setFull(!!ref.current && document.fullscreenElement === ref.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, [ref]);
  useEffect(() => {
    if (!full) return;
    const root = document.documentElement;
    const fit = () => {
      const k = Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
      root.style.fontSize = `${Math.min(MAX_SCALE, Math.max(1, k)) * 100}%`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
      root.style.fontSize = "";
    };
  }, [full]);
  if (!document.fullscreenEnabled) return [false, null];
  const toggle = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else void ref.current?.requestFullscreen().catch(() => undefined);
  };
  return [full, toggle];
}

// мельче не уменьшаем: текст должен читаться с экрана
const FIT_MIN = 0.72;

/**
 * Колонка как слайд: без прокрутки. Если содержимое выше колонки (длинный язык, низкий экран), оно уменьшается
 * целиком (scale), а ширина под масштаб растёт, чтобы строки не стали короче. Пересчёт при смене этапа, языка,
 * полноэкранного режима и размера. Ниже lg высота колонки не задана: масштаб 1.
 */
function FitBox({ fitKey, className, children }: { fitKey: string; className: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: fitKey меняет содержимое, мерить надо заново
  useLayoutEffect(() => {
    const outer = box.current;
    const inner = body.current;
    if (!outer || !inner) return;
    const fit = () => {
      let s = 1;
      inner.style.transform = "";
      inner.style.width = "";
      const avail = outer.clientHeight;
      for (let i = 0; i < 4; i++) {
        const h = inner.offsetHeight;
        if (h * s <= avail + 1) break;
        s = Math.max(FIT_MIN, Math.min(s, avail / h) * 0.995);
        inner.style.width = `${100 / s}%`;
        inner.style.transform = `scale(${s})`;
        if (s === FIT_MIN) break;
      }
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(outer);
    return () => ro.disconnect();
  }, [fitKey]);
  return (
    <div ref={box} className={`min-h-0 overflow-hidden ${className}`}>
      <div ref={body} className="origin-top-left">
        {children}
      </div>
    </div>
  );
}

// автопереход: выбор зрителя помним в браузере; хранилища может не быть (приватный режим)
const AUTO_KEY = "jana.demo.autoNext";
function readAutoNext(): boolean {
  try {
    return localStorage.getItem(AUTO_KEY) !== "0";
  } catch {
    return true;
  }
}
function saveAutoNext(v: boolean) {
  try {
    localStorage.setItem(AUTO_KEY, v ? "1" : "0");
  } catch {
    // не запомнили: работает до перезагрузки
  }
}

function StageBtn({
  children,
  onClick,
  label,
  disabled,
  primary,
  attention,
}: {
  children: ReactNode;
  onClick: () => void;
  label: string;
  disabled?: boolean;
  primary?: boolean;
  attention?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={`grid h-9 w-9 place-items-center rounded-full transition active:scale-90 disabled:opacity-30 ${
        primary
          ? "bg-brand-600 text-white hover:bg-brand-700"
          : attention
            ? "bg-brand-50 text-brand-700 ring-2 ring-brand-500 ring-offset-2 hover:bg-brand-100"
            : "bg-line-soft text-ink hover:bg-line"
      }`}
    >
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill={primary ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {children}
      </svg>
    </button>
  );
}
