import { describe, expect, it } from "vitest";

import { en, pt, translate } from "./dictionary";

const EM_DASH = String.fromCharCode(0x2014);

describe("dictionary", () => {
  it("has the same keys in English and Portuguese", () => {
    expect(Object.keys(pt).sort()).toEqual(Object.keys(en).sort());
  });

  it("has no blank translations", () => {
    for (const dictionary of [en, pt]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(value.trim(), key).not.toBe("");
      }
    }
  });

  it("keeps the same placeholders in both languages", () => {
    const placeholders = (value: string) => (value.match(/\{\w+\}/g) ?? []).sort();
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(pt[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it("never uses the em dash character", () => {
    for (const dictionary of [en, pt]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(value.includes(EM_DASH), key).toBe(false);
      }
    }
  });

  it("fills placeholders", () => {
    expect(translate("en", "toast.archived", { title: "Backend Developer" })).toBe("Backend Developer archived.");
    expect(translate("pt", "toast.applied", { title: "Dev" })).toBe("Dev foi para Candidaturas.");
  });

  it("leaves unknown placeholders untouched", () => {
    expect(translate("en", "toast.archived", { other: "x" })).toBe("{title} archived.");
  });
});
