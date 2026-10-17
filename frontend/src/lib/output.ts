import { useEffect, useState } from "react";
import { type ExplainRecord, FIELD_NAMES } from "../api/client";

/** То же, что уходит в экспорт: без trace и пояснений. */
export function outputJson(r: ExplainRecord): string {
  const out: Record<string, unknown> = { id: r.id, raw_address: r.raw_address };
  for (const f of FIELD_NAMES) out[f] = r[f] ?? null;
  out.confidence = r.confidence;
  return JSON.stringify(out, null, 2);
}

/** Копирование в буфер с отметкой «скопировано» на полторы секунды; результат: удалось ли. */
export function useCopy(ms = 1500): { copied: boolean; copy: (text: string) => Promise<boolean> } {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), ms);
    return () => clearTimeout(timer);
  }, [copied, ms]);
  async function copy(text: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      return true;
    } catch {
      return false;
    }
  }
  return { copied, copy };
}
