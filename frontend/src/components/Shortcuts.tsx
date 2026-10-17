import type { ReactNode } from "react";
import { useI18n } from "../i18n";
import type { TranslationKey } from "../i18n/types";
import { Kbd, Modal } from "./ui";

const ROWS: { keys: ReactNode; label: TranslationKey }[] = [
  {
    keys: (
      <>
        <Kbd>J</Kbd> <Kbd>K</Kbd> · <Kbd>↓</Kbd> <Kbd>↑</Kbd>
      </>
    ),
    label: "kbNav",
  },
  {
    keys: (
      <>
        <Kbd>Alt</Kbd>+<Kbd>↓</Kbd> <Kbd>Alt</Kbd>+<Kbd>↑</Kbd>
      </>
    ),
    label: "kbNavEditor",
  },
  {
    keys: (
      <>
        <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>
      </>
    ),
    label: "kbSave",
  },
  {
    keys: (
      <>
        <Kbd>Ctrl</Kbd>+<Kbd>Shift</Kbd>+<Kbd>Enter</Kbd>
      </>
    ),
    label: "kbDefer",
  },
  { keys: <Kbd>Esc</Kbd>, label: "kbClose" },
  { keys: <Kbd>U</Kbd>, label: "kbUncertain" },
  { keys: <Kbd>/</Kbd>, label: "kbSearch" },
  { keys: <Kbd>?</Kbd>, label: "kbHelp" },
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Modal open={open} onClose={onClose} title={t("shortcutsTitle")}>
      <dl className="divide-y divide-line-soft">
        {ROWS.map((r, i) => (
          <div
            key={r.label}
            className="stagger flex animate-fade-up items-center justify-between gap-4 py-2 text-sm"
            style={{ "--i": i } as React.CSSProperties}
          >
            <dt className="text-ink-2">{t(r.label)}</dt>
            <dd className="flex shrink-0 items-center gap-1 text-xs text-ink-3">{r.keys}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-3">{t("kbPickHint")}</p>
    </Modal>
  );
}
