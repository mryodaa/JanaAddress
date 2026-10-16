import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { FieldName } from "../api/client";
import { en } from "./locales/en";
import { kk } from "./locales/kk";
import { ru } from "./locales/ru";
import type { AvailableLanguage, Language, TranslationDictionary, TranslationKey } from "./types";

const STORAGE_KEY = "jana_address_lang";

const DICTIONARIES: Record<Language, TranslationDictionary> = {
  kk,
  ru,
  en,
};

const DEFAULT_META: AvailableLanguage = { code: "ru", label: "Русский", short: "РУС", locale: "ru-RU" };

export const AVAILABLE_LANGUAGES: AvailableLanguage[] = [
  { code: "kk", label: "Қазақша", short: "ҚАЗ", locale: "kk-KZ" },
  DEFAULT_META,
  { code: "en", label: "English", short: "ENG", locale: "en-US" },
];

export interface I18nContextValue {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
  fieldLabels: Record<FieldName, string>;
  stepLabels: Record<string, string>;
  locale: string;
  sourceLabel: (source: string | null | undefined) => string | null;
  availableLanguages: AvailableLanguage[];
}

const I18nContext = createContext<I18nContextValue | null>(null);

function detectInitialLanguage(): Language {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "kk" || saved === "ru" || saved === "en") {
      return saved;
    }
  } catch {
    /* localStorage недоступен */
  }

  if (typeof navigator !== "undefined" && navigator.language) {
    const browserLang = navigator.language.toLowerCase();
    if (browserLang.startsWith("kk")) return "kk";
    if (browserLang.startsWith("en")) return "en";
    if (browserLang.startsWith("ru")) return "ru";
  }

  return "ru";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(detectInitialLanguage);

  const setLanguage = useCallback((lang: Language) => {
    setLanguageState(lang);
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = language;
    }
  }, [language]);

  const dict = useMemo(() => DICTIONARIES[language] ?? ru, [language]);
  const currentLangMeta = useMemo(
    () => AVAILABLE_LANGUAGES.find((l) => l.code === language) ?? DEFAULT_META,
    [language],
  );

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>): string => {
      let str = dict[key] ?? ru[key] ?? (key as string);
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          str = str.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
        }
      }
      return str;
    },
    [dict],
  );

  const sourceLabel = useCallback(
    (source: string | null | undefined): string | null => {
      if (!source || source === "string") return null;
      if (source === "manual") return dict.sourceManual;
      const [, s] = source.split(":");
      return s ? `${dict.sourceRefBase} · ${s.toUpperCase()}` : dict.sourceRefBase;
    },
    [dict],
  );

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      t,
      fieldLabels: dict.fields,
      stepLabels: dict.steps,
      locale: currentLangMeta.locale,
      sourceLabel,
      availableLanguages: AVAILABLE_LANGUAGES,
    }),
    [language, setLanguage, t, dict, currentLangMeta, sourceLabel],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}
