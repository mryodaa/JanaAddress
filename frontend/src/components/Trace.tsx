import { type ReactNode, useState } from "react";
import type { FieldName, StepTrace } from "../api/client";
import { useI18n } from "../i18n";
import { FIELD_COLORS, visible } from "../lib/fields";
import {
  asField,
  parseArbiter,
  parseDisputes,
  parseLayout,
  parseTaggerSpans,
  parseTokens,
  quoted,
} from "../lib/trace";
import { DEMO_TEXTS } from "./demo/texts";
import { FieldDot, Skeleton, SourceTag } from "./ui";

// служебные ключи changes, которые показываются отдельно или только в технических деталях
const HIDDEN_KEYS = new Set(["parts", "unparsed", "features", "orientation", "removed_chars", "confidence"]);

export function totalMs(trace: StepTrace[]): number {
  return trace.reduce((a, s) => a + s.ms, 0);
}

export function TraceSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-12 w-full rounded-xl" />
      ))}
    </div>
  );
}

interface FieldChange {
  field: FieldName;
  value: unknown;
  source: string | undefined;
}

function fieldChanges(s: StepTrace): FieldChange[] {
  return Object.entries(s.changes ?? {}).flatMap(([k, v]) => {
    const f = asField(k);
    if (!f) return [];
    const o = v && typeof v === "object" && "value" in v ? (v as { value: unknown; source?: string }) : null;
    return [{ field: f, value: o ? o.value : v, source: o?.source }];
  });
}

/** Шаг ничего не изменил и ничего не сообщил: сворачиваем в общую строку. */
function isQuiet(s: StepTrace): boolean {
  if (s.step === "confidence") return false;
  const ch = s.changes ?? {};
  const meaningful = Object.keys(ch).filter((k) => !HIDDEN_KEYS.has(k) || (k === "removed_chars" && ch[k]));
  return meaningful.length === 0 && !(s.notes ?? []).length;
}

const KIND_CLS: Record<string, string> = {
  w: "bg-white text-ink ring-line",
  n: "bg-brand-50 text-brand-800 ring-brand-200",
  s: "bg-canvas text-ink-3 ring-line-soft",
  p: "bg-canvas text-ink-3 ring-line-soft",
};

function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-xs ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}

function FieldChips({ changes }: { changes: FieldChange[] }) {
  const { fieldLabels } = useI18n();
  return (
    <div className="flex flex-wrap gap-1.5">
      {changes.map((c) => (
        <span
          key={c.field}
          className={`inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1 text-xs ring-1 ring-inset ${FIELD_COLORS[c.field].mark}`}
        >
          <span className="opacity-70">{fieldLabels[c.field]}</span>
          <span className="truncate font-semibold">{c.value == null ? "null" : String(c.value)}</span>
          {c.source && c.source !== "string" && <SourceTag source={c.source} />}
        </span>
      ))}
    </div>
  );
}

function StepBody({ s }: { s: StepTrace }) {
  const { t, fieldLabels, language } = useI18n();
  const notes = s.notes ?? [];
  const ch = (s.changes ?? {}) as Record<string, unknown>;
  const fields = fieldChanges(s);

  switch (s.step) {
    case "layout": {
      const l = parseLayout(notes);
      if (!l) break;
      return (
        <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
          <span className="text-ink-3 line-through">{l.from}</span>
          <span className="text-ink-3">→</span>
          <span className="font-semibold text-ink">{l.to}</span>
        </div>
      );
    }
    case "clean": {
      const cleaned = quoted(notes.find((n) => n.startsWith("clean:")) ?? "")[0];
      return (
        <div className="grid gap-1 text-xs">
          {typeof ch.removed_chars === "number" && ch.removed_chars > 0 && (
            <span className="w-fit rounded-md bg-danger-50 px-1.5 py-0.5 font-medium text-danger">
              {t("traceRemoved", { n: ch.removed_chars })}
            </span>
          )}
          {cleaned && <span className="font-mono text-ink-2">{visible(cleaned)}</span>}
        </div>
      );
    }
    case "tokenize": {
      const toks = parseTokens(notes[0] ?? "");
      return (
        <div>
          <div className="flex flex-wrap gap-1">
            {toks.map((tk, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: токены не переставляются
              <Chip key={i} className={`font-mono ${KIND_CLS[tk.kind] ?? KIND_CLS.w}`}>
                {visible(tk.text)}
              </Chip>
            ))}
          </div>
          <div className="mt-1 text-[11px] text-ink-3">{t("traceTokens", { n: toks.length })}</div>
        </div>
      );
    }
    case "split_bilingual": {
      const q = quoted(notes[0] ?? "");
      if (q.length < 2) break;
      return (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <Chip className="bg-brand-50 text-brand-800 ring-brand-200">{q[0]}</Chip>
          <span className="text-ink-3">{t("traceKept")}</span>
          <Chip className="bg-canvas text-ink-3 line-through ring-line-soft">{q[1]}</Chip>
          <span className="text-ink-3">{t("traceDropped")}</span>
        </div>
      );
    }
    case "parts": {
      const orgs = notes.flatMap((n) => quoted(n).slice(0, 1));
      if (!orgs.length) break;
      return (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {orgs.map((o) => (
            <Chip key={o} className="bg-canvas text-ink-3 line-through ring-line-soft">
              {o}
            </Chip>
          ))}
          <span className="text-ink-3">{t("traceNotAddress")}</span>
        </div>
      );
    }
    case "tagger": {
      const spans = parseTaggerSpans(notes);
      if (!spans.length) break;
      return (
        <div className="flex flex-wrap gap-1.5">
          {spans.map((sp, i) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: спаны не переставляются
              key={i}
              className={`inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1 text-xs ring-1 ring-inset ${
                sp.field ? FIELD_COLORS[sp.field].mark : "bg-canvas text-ink-3 ring-line-soft"
              }`}
            >
              <span className="opacity-70">
                {sp.field ? fieldLabels[sp.field] : sp.label === "KZ_DUP" ? t("traceDup") : t("traceNoise")}
              </span>
              <span className={`truncate font-semibold ${sp.field ? "" : "line-through"}`}>{sp.text}</span>
              <span className="font-mono text-[10px] opacity-60">{sp.p.toFixed(2)}</span>
            </span>
          ))}
        </div>
      );
    }
    case "arbiter": {
      const g = parseArbiter(notes);
      const disputes = parseDisputes(notes);
      if (!g) break;
      const group = (label: string, fs: FieldName[], cls: string) =>
        fs.length ? (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="mr-0.5 text-ink-3">{label}:</span>
            {fs.map((f) => (
              <Chip key={f} className={cls}>
                <FieldDot field={f} />
                {fieldLabels[f]}
              </Chip>
            ))}
          </div>
        ) : null;
      return (
        <div className="grid gap-1.5">
          {group(t("traceAgree"), g.agree, "bg-brand-50 text-brand-800 ring-brand-200")}
          {group(t("traceDispute"), g.dispute, "bg-warn-50 text-warn-800 ring-warn/40")}
          {group(t("traceRulesOnly"), g.rulesOnly, "bg-canvas text-ink-2 ring-line")}
          {group(t("traceModelOnly"), g.modelOnly, "bg-canvas text-ink-2 ring-line")}
          {disputes.map((d) => (
            <div key={d.field} className="rounded-lg bg-warn-50 px-2.5 py-1.5 text-xs">
              <span className="font-medium">{fieldLabels[d.field]}:</span>{" "}
              <span className={d.winner === "rules" ? "font-semibold" : "text-ink-3 line-through"}>
                «{d.rules}»
              </span>{" "}
              <span className="font-mono text-[10px] text-ink-3">{d.rulesScore.toFixed(2)}</span>
              <span className="mx-1 text-ink-3">vs</span>
              <span className={d.winner === "model" ? "font-semibold" : "text-ink-3 line-through"}>
                «{d.model}»
              </span>{" "}
              <span className="font-mono text-[10px] text-ink-3">{d.modelScore.toFixed(2)}</span>
              <span className="ml-1.5 font-semibold text-warn-800">
                → {d.winner === "rules" ? t("traceWinnerRules") : t("traceWinnerModel")}
              </span>
            </div>
          ))}
        </div>
      );
    }
    case "confidence": {
      const parts = Object.entries((ch.parts ?? {}) as Record<string, number>);
      const labels = DEMO_TEXTS[language].confParts;
      return (
        <div className="grid max-w-md gap-1">
          {parts.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-ink-2">
                {labels[k] ?? k.replace(/^(flag|bonus):/, "").replace(/_/g, " ")}
              </span>
              <span
                className={`font-mono font-semibold tabular-nums ${v >= 0 ? "text-brand-700" : "text-danger"}`}
              >
                {v >= 0 ? "+" : ""}
                {v.toFixed(2)}
              </span>
            </div>
          ))}
          {typeof ch.confidence === "number" && (
            <div className="mt-1 flex items-center justify-between border-t border-line-soft pt-1 text-sm font-semibold">
              <span>{t("traceFinal")}</span>
              <span className="tabular-nums">{Math.round(ch.confidence * 100)}%</span>
            </div>
          )}
        </div>
      );
    }
  }

  // шаги правил и справочника: найденные поля метками; прочее только в технических деталях
  const orientation = typeof ch.orientation === "string" ? ch.orientation : null;
  if (fields.length || orientation) {
    return (
      <div className="grid gap-1.5">
        {fields.length > 0 && <FieldChips changes={fields} />}
        {orientation && (
          <div className="text-[11px] text-ink-3">{t("traceOrientation", { v: orientation })}</div>
        )}
      </div>
    );
  }
  return notes.length ? (
    <ul className="space-y-0.5 text-xs text-ink-2">
      {notes.map((n) => (
        <li key={n} className="break-words">
          {n}
        </li>
      ))}
    </ul>
  ) : null;
}

/** Сырые changes и заметки шага: для разработчика, по кнопке в заголовке. */
function DetailsBody({ s }: { s: StepTrace }) {
  const notes = s.notes ?? [];
  const raw = Object.entries(s.changes ?? {}).filter(([k]) => k !== "features");
  return (
    <div className="mt-2 space-y-0.5 rounded-lg bg-canvas p-2 font-mono text-[11px] text-ink-2">
      {raw.map(([k, v]) => (
        <div key={k} className="break-words">
          <span className="text-brand-700">{k}</span> = {JSON.stringify(v)}
        </div>
      ))}
      {notes.map((n) => (
        <div key={n} className="break-words text-ink-3">
          {n}
        </div>
      ))}
    </div>
  );
}

function Step({ s, name }: { s: StepTrace; name: string }) {
  const { t, stepHints } = useI18n();
  const [open, setOpen] = useState(false);
  const hasDetails = (s.notes ?? []).length > 0 || Object.keys(s.changes ?? {}).some((k) => k !== "features");
  return (
    <li className="relative pb-5 pl-7 last:pb-0">
      <span className="absolute top-1 left-0 h-[15px] w-[15px] rounded-full border-[3px] border-white bg-brand-600 shadow-[0_0_0_1px_var(--color-brand-200)]" />
      {/* в широкой ленте две колонки: слева что за шаг, справа что он нашёл; в узком редакторе одна */}
      <div className="@2xl:grid @2xl:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] @2xl:gap-x-8">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 text-sm font-semibold text-ink">{name}</span>
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-3">
              {s.ms.toFixed(2)} {t("msUnit")}
            </span>
            {hasDetails && (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                title={t("traceDetails")}
                aria-label={t("traceDetails")}
                className={`shrink-0 self-center rounded-md px-1 font-mono text-[10px] font-semibold transition-colors ${
                  open ? "bg-ink text-white" : "text-ink-3 hover:bg-canvas hover:text-brand-700"
                }`}
              >
                {"{ }"}
              </button>
            )}
          </div>
          {stepHints[s.step] && (
            <p className="mb-2 text-xs leading-snug text-ink-3 @2xl:mb-0">{stepHints[s.step]}</p>
          )}
        </div>
        <div className="min-w-0 @2xl:pt-0.5">
          <StepBody s={s} />
          {hasDetails && (
            <div className="reveal" data-open={open}>
              <div>
                <DetailsBody s={s} />
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

type Item = { kind: "step"; s: StepTrace } | { kind: "quiet"; steps: StepTrace[] };

export function Trace({ trace }: { trace: StepTrace[] }) {
  const { t, stepLabels } = useI18n();
  const [showQuiet, setShowQuiet] = useState(false);

  // подряд идущие «пустые» шаги в одну строку: длинная лента из пустых карточек не читается
  const items: Item[] = [];
  for (const s of trace) {
    const last = items[items.length - 1];
    if (isQuiet(s)) {
      if (last?.kind === "quiet") last.steps.push(s);
      else items.push({ kind: "quiet", steps: [s] });
    } else items.push({ kind: "step", s });
  }
  const quietCount = trace.filter(isQuiet).length;
  const name = (s: StepTrace) => (stepLabels[s.step] ?? s.step).replace(/^\d+[a-z]?\.\s*/, "");

  return (
    <div className="@container">
      <div className="mb-3 flex items-center justify-between gap-2 text-xs text-ink-3">
        <span>{t("traceSummary", { n: trace.length, k: trace.length - quietCount })}</span>
        {quietCount > 0 && (
          <button
            type="button"
            onClick={() => setShowQuiet((v) => !v)}
            className="rounded-md px-1.5 py-0.5 font-medium text-brand-700 transition-colors hover:bg-brand-50"
          >
            {showQuiet ? t("traceHideQuiet") : t("traceShowQuiet")} ({quietCount})
          </button>
        )}
      </div>
      <ol className="relative">
        {/* вертикальная лента шагов */}
        <span aria-hidden="true" className="absolute top-2 bottom-2 left-[7px] w-px bg-line" />
        {items.map((it, i) =>
          it.kind === "quiet" ? (
            showQuiet ? (
              it.steps.map((s) => (
                <li
                  key={s.step}
                  className="relative flex animate-fade-in items-center gap-2 pb-2 pl-7 text-xs text-ink-3"
                >
                  <span className="absolute top-1 left-[3px] h-2.5 w-2.5 rounded-full border-2 border-line bg-white" />
                  <span className="min-w-0 flex-1 truncate">
                    {name(s)} <span className="text-ink-3/70">· {t("traceQuietShort")}</span>
                  </span>
                  <span className="font-mono text-[10px] tabular-nums">{s.ms.toFixed(2)}</span>
                </li>
              ))
            ) : (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: группы строятся по порядку шагов
                key={`q${i}`}
                className="relative pb-3 pl-7 text-xs text-ink-3"
              >
                <span className="absolute top-1 left-[3px] h-2.5 w-2.5 rounded-full border-2 border-line bg-white" />
                <button
                  type="button"
                  onClick={() => setShowQuiet(true)}
                  className="text-left transition-colors hover:text-brand-700"
                  title={it.steps.map(name).join(", ")}
                >
                  {it.steps.map(name).join(" · ")} — {t("traceQuietShort")}
                </button>
              </li>
            )
          ) : (
            <Step key={it.s.step} s={it.s} name={name(it.s)} />
          ),
        )}
      </ol>
    </div>
  );
}
