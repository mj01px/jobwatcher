import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { readStorage, writeStorage } from "../lib/storage";
import { translate, type Language, type TranslationKey, type TranslationVars } from "./dictionary";

export const LANGUAGE_STORAGE_KEY = "job-watcher-language";

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: TranslationKey, vars?: TranslationVars) => string;
  formatDateTime: (value: string | null | undefined) => string;
  /** Formats a date only value (YYYY-MM-DD) without shifting it across time zones. */
  formatDate: (value: string | null | undefined) => string;
  /** Day and month only (03/09 in Portuguese), same time zone rule as formatDate. */
  formatDayMonth: (value: string | null | undefined) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

/** Brazilian Portuguese unless English was chosen (docs/API-v3.md, section 7). */
export function toLanguage(value: string | null | undefined): Language {
  return value === "en" ? "en" : "pt";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => toLanguage(readStorage(LANGUAGE_STORAGE_KEY)));

  useEffect(() => {
    document.documentElement.lang = language === "pt" ? "pt-BR" : "en";
    document.documentElement.dataset.language = language;
  }, [language]);

  const setLanguage = useCallback((next: Language) => {
    writeStorage(LANGUAGE_STORAGE_KEY, next);
    setLanguageState(next);
  }, []);

  const value = useMemo<I18nValue>(() => {
    const formatter = new Intl.DateTimeFormat(language === "pt" ? "pt-BR" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const dateFormatter = new Intl.DateTimeFormat(language === "pt" ? "pt-BR" : "en-US", { dateStyle: "medium" });
    const dayMonthFormatter = new Intl.DateTimeFormat(language === "pt" ? "pt-BR" : "en-US", {
      day: "2-digit",
      month: "2-digit",
    });
    const localDate = (raw: string): Date | null => {
      const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
      if (!match) return null;
      const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
      return Number.isNaN(date.valueOf()) ? null : date;
    };
    return {
      language,
      setLanguage,
      t: (key, vars) => translate(language, key, vars),
      formatDateTime: (raw) => {
        if (!raw) return "";
        const date = new Date(raw);
        return Number.isNaN(date.valueOf()) ? raw : formatter.format(date);
      },
      formatDate: (raw) => {
        if (!raw) return "";
        const date = localDate(raw);
        return date ? dateFormatter.format(date) : raw;
      },
      formatDayMonth: (raw) => {
        if (!raw) return "";
        const date = localDate(raw);
        return date ? dayMonthFormatter.format(date) : raw;
      },
    };
  }, [language, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
