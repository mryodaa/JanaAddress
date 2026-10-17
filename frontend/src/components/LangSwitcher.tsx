import { useI18n } from "../i18n";
import type { Language } from "../i18n/types";
import { Segmented } from "./ui";

export function LangSwitcher() {
  const { t, language, setLanguage, availableLanguages } = useI18n();

  return (
    <Segmented<Language>
      ariaLabel={t("langAria")}
      size="sm"
      value={language}
      onChange={setLanguage}
      options={availableLanguages.map((l) => ({
        value: l.code,
        label: <span title={l.label}>{l.short}</span>,
      }))}
    />
  );
}
