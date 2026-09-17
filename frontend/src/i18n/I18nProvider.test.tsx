import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nProvider, useI18n } from "./I18nProvider";

function NavLabel() {
  const { t } = useI18n();
  return <p>{t("nav.highlighted")}</p>;
}

describe("interface language", () => {
  it("renders Brazilian Portuguese and sets the document language", () => {
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    );

    expect(screen.getByText("Destaques")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("pt-BR");
  });

  it("translates keys to their Portuguese copy", () => {
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    );

    // "Highlights" in English; the interface only ever renders the Portuguese.
    expect(screen.queryByText("Highlights")).not.toBeInTheDocument();
    expect(screen.getByText("Destaques")).toBeInTheDocument();
  });
});
