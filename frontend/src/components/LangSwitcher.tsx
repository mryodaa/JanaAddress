import { useI18n } from "../i18n";

export function LangSwitcher() {
  const { language, setLanguage, availableLanguages } = useI18n();

  return (
    <div
      aria-label="Language selection"
      className="inline-flex items-center rounded-lg bg-brand-700/60 p-0.5 text-xs font-medium"
    >
      {availableLanguages.map((l) => {
        const active = language === l.code;
        return (
          <button
            type="button"
            key={l.code}
            onClick={() => setLanguage(l.code)}
            title={l.label}
            className={`rounded-md px-2 py-0.5 transition ${
              active
                ? "bg-white font-semibold text-brand-800 shadow-xs"
                : "text-white/80 hover:bg-white/10 hover:text-white"
            }`}
          >
            {l.short}
          </button>
        );
      })}
    </div>
  );
}
