import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nProvider, LANGUAGE_STORAGE_KEY, toLanguage, useI18n } from "./I18nProvider";

function NavLabel() {
  const { t, language } = useI18n();
  return (
    <p>
      {language}: {t("nav.highlighted")}
    </p>
  );
}

describe("default language", () => {
  it("is Brazilian Portuguese unless English was chosen", () => {
    expect(toLanguage(null)).toBe("pt");
    expect(toLanguage(undefined)).toBe("pt");
    expect(toLanguage("garbage")).toBe("pt");
    expect(toLanguage("pt")).toBe("pt");
    expect(toLanguage("en")).toBe("en");
  });

  it("renders Portuguese with nothing stored and sets the document language", () => {
    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    );

    expect(screen.getByText("pt: Destaques")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("pt-BR");
  });

  it("keeps a stored English choice", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    );

    expect(screen.getByText("en: Highlights")).toBeInTheDocument();
  });
});
