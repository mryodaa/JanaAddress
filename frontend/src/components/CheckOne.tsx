import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { type ExplainRecord, FIELD_NAMES, api } from "../api/client";
import { useI18n } from "../i18n";
import { confModel } from "../lib/confidence";
import { errorText } from "../lib/errors";
import { useDebounced, usePresence } from "../lib/motion";
import { outputJson, useCopy } from "../lib/output";
import { ConfidenceExplain } from "./ConfidenceExplain";
import { useToast } from "./Toast";
import { DEMO_TEXTS, fmt } from "./demo/texts";
import { IconAlert, IconCheck, IconChevronRight, IconCopy } from "./icons";
import {
  BusyBar,
  Button,
  Card,
  ConfidenceBadge,
  Disclosure,
  FieldDot,
  Highlighted,
  Legend,
  Skeleton,
  SourceTag,
  TextInput,
  Unparsed,
} from "./ui";

const EXAMPLES = [
  "город Алматы/Алматы қаласы, Мкр Аксай 3а, 59, кв 70",
  "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
  "Туран 55/6 магазин береке 4подьезд 9этаж",
  "Турксибский район, Рыбинский переулок, дом 4",
  "Илийский район, Боралдай, ул. Ленина 1/2",
];

export function CheckOne({ threshold }: { threshold: number }) {
  const { t, fieldLabels, language } = useI18n();
  const toast = useToast();
  // старт с пустого поля: сначала видны примеры, после ввода они плавно сворачиваются
  const [text, setText] = useState("");
  // разбор на лету с паузой; Enter и клик по примеру разбирают сразу
  const live = useDebounced(text, 400);
  const [forced, setForced] = useState("");
  const [whyOpen, setWhyOpen] = useState(false);
  const query = (forced === text ? text : live).trim();
  const { copied, copy: copyText } = useCopy();

  const m = useQuery({
    queryKey: ["parse", query],
    queryFn: () => api.parseOne(query),
    enabled: !!query,
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
  const r = query ? m.data : undefined;
  // результат уходит с анимацией (поле очистили): держим последний, пока идёт исчезновение
  const lastR = useRef<ExplainRecord | undefined>(undefined);
  if (r) lastR.current = r;
  const presence = usePresence(!!r, 180);
  const shown = r ?? (presence.mounted ? lastR.current : undefined);
  const showExamples = !text.trim();
  const conf = shown ? confModel(shown.trace, shown.confidence) : null;

  async function copy() {
    if (!r) return;
    if (await copyText(outputJson(r))) toast(t("copied"));
    else toast(t("copyFailed"), "error");
  }

  return (
    <div className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)] gap-4 pt-2 sm:pt-4">
      <div className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("checkTitle")}</h1>
        <p className="mt-1.5 text-sm text-ink-2 sm:text-base">{t("checkSubtitle")}</p>
      </div>
      <Card className="relative animate-fade-up overflow-hidden [animation-delay:60ms]">
        <BusyBar active={m.isFetching} className="absolute inset-x-0 top-0" />
        {/* разбор идёт на лету, кнопка не нужна; форма оставлена ради Enter (разобрать без паузы) */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setForced(text);
          }}
        >
          <TextInput value={text} onChange={setText} placeholder={t("inputPlaceholder")} size="lg" />
        </form>
        {/* примеры нужны только до ввода; высота сворачивается плавно, контент ниже не прыгает */}
        <div className="reveal" data-open={showExamples} aria-hidden={!showExamples}>
          <div className={`transition-opacity duration-200 ${showExamples ? "opacity-100" : "opacity-0"}`}>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs text-ink-3">{t("examples")}</span>
              {EXAMPLES.map((ex) => (
                <button
                  type="button"
                  key={ex}
                  onClick={() => {
                    setText(ex);
                    setForced(ex);
                  }}
                  tabIndex={showExamples ? 0 : -1}
                  className="max-w-full truncate rounded-full border border-line bg-white px-3 py-1 text-xs text-ink-2 transition duration-150 hover:border-brand-200 hover:bg-brand-50 hover:text-brand-800 active:scale-95"
                >
                  {ex}
                </button>
              ))}
            </div>
            <div className="mt-2 text-[11px] text-ink-3">{t("liveHint")}</div>
          </div>
        </div>
        {m.error && (
          <div className="mt-3 inline-flex animate-fade-up items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger">
            <IconAlert className="h-4 w-4 shrink-0" />
            {errorText(m.error, t, language)}
          </div>
        )}
      </Card>

      {!shown && m.isFetching && <Skeleton className="h-80 w-full animate-fade-in rounded-[20px]" />}

      {shown && (
        <div
          className={`grid grid-cols-[minmax(0,1fr)] gap-4 transition-opacity duration-200 ${
            presence.leaving ? "animate-fade-out" : m.isPlaceholderData ? "opacity-60" : ""
          }`}
        >
          <Card className="animate-fade-up">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div
                key={String(shown.raw_address)}
                className="animate-fade-in text-base leading-relaxed sm:text-lg"
              >
                <Highlighted raw={String(shown.raw_address)} fields={shown.fields ?? {}} />
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <ConfidenceBadge value={shown.confidence} threshold={threshold} />
                <Button
                  size="sm"
                  onClick={copy}
                  icon={
                    copied ? <IconCheck className="h-4 w-4 animate-check-pop text-brand-600" /> : <IconCopy />
                  }
                >
                  {copied ? t("copied") : t("copyJson")}
                </Button>
              </div>
            </div>
            <Legend />
            <dl className="mt-4 grid grid-cols-1 gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
              {FIELD_NAMES.map((f, i) => (
                <div
                  key={f}
                  className="stagger flex animate-fade-up items-baseline gap-2 border-b border-line-soft py-2"
                  style={{ "--i": i } as React.CSSProperties}
                >
                  <dt className="flex w-36 shrink-0 items-center gap-1.5 text-xs text-ink-2">
                    <FieldDot field={f} />
                    {fieldLabels[f]}
                  </dt>
                  <dd className="min-w-0 text-sm font-medium break-words">
                    {shown[f] ?? <span className="font-mono text-xs font-normal text-ink-3">null</span>}
                    <SourceTag source={shown.fields?.[f]?.source} />
                  </dd>
                </div>
              ))}
            </dl>
            <Unparsed items={shown.unparsed} className="mt-3" />
            {/* почему такая уверенность: баллы признаков, сумма, порог */}
            {conf && (
              <div className="mt-4">
                <Disclosure
                  title={fmt(DEMO_TEXTS[language].cx.title, { pct: Math.round(shown.confidence * 100) })}
                  open={whyOpen}
                  onToggle={() => setWhyOpen((v) => !v)}
                >
                  <ConfidenceExplain
                    model={conf}
                    threshold={threshold}
                    trace={shown.trace ?? undefined}
                    values={shown}
                  />
                </Disclosure>
              </div>
            )}
            {/* объяснение по шагам живёт на «Демо»: туда с этим же адресом, показ стартует сам */}
            <div className="mt-4 flex justify-end border-t border-line-soft pt-3">
              <a
                href={`#/demo?q=${encodeURIComponent(String(shown.raw_address ?? ""))}`}
                className="group inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-semibold text-brand-700 transition-colors hover:bg-brand-50"
              >
                {t("howParsed")}
                <IconChevronRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
              </a>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
