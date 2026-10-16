import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { FIELD_NAMES, api } from "../api/client";
import { useI18n } from "../i18n";
import { FIELD_COLORS } from "../lib/fields";
import { Trace } from "./Trace";
import { Button, Card, ConfidenceBadge, Highlighted, Legend, SourceTag } from "./ui";

const EXAMPLES = [
  "город Алматы/Алматы қаласы, Мкр Аксай 3а, 59, кв 70",
  "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
  "Туран 55/6 магазин береке 4подьезд 9этаж",
  "Турксибский район, Рыбинский переулок, дом 4",
  "Илийский район, Боралдай, ул. Ленина 1/2",
];

export function CheckOne({ threshold }: { threshold: number }) {
  const { t, fieldLabels } = useI18n();
  const [text, setText] = useState(EXAMPLES[0] ?? "");
  const m = useMutation({ mutationFn: api.parseOne });
  const r = m.data;

  return (
    <div className="mx-auto grid max-w-5xl gap-4">
      <Card>
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            m.mutate(text);
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("inputPlaceholder")}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200"
          />
          <Button variant="primary" type="submit" disabled={!text.trim() || m.isPending}>
            {t("parseButton")}
          </Button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              type="button"
              key={ex}
              onClick={() => {
                setText(ex);
                m.mutate(ex);
              }}
              className="max-w-full truncate rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 hover:bg-brand-50 hover:text-brand-800"
            >
              {ex}
            </button>
          ))}
        </div>
        {m.error && <div className="mt-2 text-sm text-rose-700">{m.error.message}</div>}
      </Card>

      {r && (
        <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
          <Card>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="text-base leading-relaxed">
                <Highlighted raw={String(r.raw_address)} fields={r.fields ?? {}} />
              </div>
              <ConfidenceBadge value={r.confidence} threshold={threshold} />
            </div>
            <Legend />
            <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
              {FIELD_NAMES.map((f) => (
                <div key={f} className="flex items-baseline gap-2 border-b border-slate-100 pb-1.5">
                  <dt className="flex w-36 shrink-0 items-center gap-1.5 text-xs text-slate-500">
                    <span className={`h-2 w-2 rounded-sm ${FIELD_COLORS[f].dot}`} />
                    {fieldLabels[f]}
                  </dt>
                  <dd className="min-w-0 text-sm font-medium break-words">
                    {r[f] ?? <span className="font-normal text-slate-300">null</span>}
                    <SourceTag source={r.fields?.[f]?.source} />
                  </dd>
                </div>
              ))}
            </dl>
            {(r.unparsed ?? []).length > 0 && (
              <div className="mt-3 text-xs text-slate-500">
                {t("unparsed")} {(r.unparsed ?? []).map((u) => `«${u}»`).join(", ")}
              </div>
            )}
          </Card>
          <Card title={t("pipelineSteps")}>
            <Trace trace={r.trace ?? []} />
          </Card>
        </div>
      )}
    </div>
  );
}
