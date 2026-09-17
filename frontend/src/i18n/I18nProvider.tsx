import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";

import { translate, type TranslationKey, type TranslationVars } from "./dictionary";

interface I18nValue {
  t: (key: TranslationKey, vars?: TranslationVars) => string;
  formatDateTime: (value: string | null | undefined) => string;
  /** Formats a date only value (YYYY-MM-DD) without shifting it across time zones. */
  formatDate: (value: string | null | undefined) => string;
  /** Day and month only (03/09), same time zone rule as formatDate. */
  formatDayMonth: (value: string | null | undefined) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

// The interface is Brazilian Portuguese only; there is no language switch.
export function I18nProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = "pt-BR";
    document.documentElement.dataset.language = "pt";
  }, []);

  const value = useMemo<I18nValue>(() => {
    const formatter = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" });
    const dateFormatter = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" });
    const dayMonthFormatter = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });
    const localDate = (raw: string): Date | null => {
      const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
      if (!match) return null;
      const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
      return Number.isNaN(date.valueOf()) ? null : date;
    };
    return {
      t: (key, vars) => translate("pt", key, vars),
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
  }, []);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
