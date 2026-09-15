import { describe, expect, it } from "vitest";

import { sourceHref, validateSourceTarget } from "./sources";

describe("validateSourceTarget", () => {
  it("accepts only http(s) InHire career pages", () => {
    expect(validateSourceTarget("inhire", "https://cora.inhire.app/vagas")).toBe(true);
    expect(validateSourceTarget("inhire", " http://cielo.inhire.app/tecnologia/vagas ")).toBe(true);
    expect(validateSourceTarget("inhire", "https://evil.com/vagas")).toBe(false);
    expect(validateSourceTarget("inhire", "ftp://cora.inhire.app/vagas")).toBe(false);
    expect(validateSourceTarget("inhire", "cora.inhire.app")).toBe(false);
  });

  it("accepts Gupy terms between 2 and 100 characters", () => {
    expect(validateSourceTarget("gupy", "py")).toBe(true);
    expect(validateSourceTarget("gupy", "x")).toBe(false);
    expect(validateSourceTarget("gupy", "  a  ")).toBe(false);
    expect(validateSourceTarget("gupy", "a".repeat(100))).toBe(true);
    expect(validateSourceTarget("gupy", "a".repeat(101))).toBe(false);
  });

  it("accepts GitHub owner/repo", () => {
    expect(validateSourceTarget("github", "backend-br/vagas")).toBe(true);
    expect(validateSourceTarget("github", "react.brasil/vagas_2")).toBe(true);
    expect(validateSourceTarget("github", "backend-br")).toBe(false);
    expect(validateSourceTarget("github", "https://github.com/backend-br/vagas")).toBe(false);
    expect(validateSourceTarget("github", "a/b/c")).toBe(false);
  });
});

describe("sourceHref", () => {
  it("links each source to what it watches", () => {
    expect(sourceHref("inhire", "https://cora.inhire.app/vagas")).toBe("https://cora.inhire.app/vagas");
    expect(sourceHref("github", "backend-br/vagas")).toBe("https://github.com/backend-br/vagas/issues");
    expect(sourceHref("gupy", "dev python")).toContain("dev%20python");
  });
});
