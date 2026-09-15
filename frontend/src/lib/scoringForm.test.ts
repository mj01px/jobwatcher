import { describe, expect, it } from "vitest";

import {
  draftMinScore,
  draftStackGroups,
  draftToGroups,
  splitTerms,
  toDraft,
  validateScoringDraft,
  validateStackGroups,
  type GroupDraft,
  type ScoringDraft,
} from "./scoringForm";

function group(overrides: Partial<GroupDraft>): GroupDraft {
  return { uid: "g", key: "core", weight: "12", terms: "python\ndjango", stack: false, ...overrides };
}

function draft(groups: GroupDraft[], minScore = "20"): ScoringDraft {
  return { groups, minScore };
}

describe("scoring form", () => {
  it("round trips server groups through the draft", () => {
    const server = {
      core: { weight: 12, terms: ["python", "django"] },
      stack_mismatch: { weight: -20, terms: ["php"] },
    };

    const edited = toDraft(server, 20);

    expect(edited.groups.map((item) => item.key)).toEqual(["core", "stack_mismatch"]);
    expect(new Set(edited.groups.map((item) => item.uid)).size).toBe(2);
    expect(validateScoringDraft(edited)).toEqual([]);
    expect(draftToGroups(edited)).toEqual(server);
    expect(draftMinScore(edited)).toBe(20);
  });

  it("splits terms by line, trimming and dropping blanks", () => {
    expect(splitTerms("  python \r\n\n django rest\n   \n")).toEqual(["python", "django rest"]);
  });

  it("accepts a valid draft", () => {
    expect(validateScoringDraft(draft([group({}), group({ uid: "h", key: "level_mid", weight: "-8" })]))).toEqual([]);
  });

  it("rejects bad group keys and duplicates", () => {
    const issues = validateScoringDraft(
      draft([group({ uid: "a", key: "Core Group" }), group({ uid: "b", key: "core" }), group({ uid: "c", key: " core " })]),
    );

    expect(issues).toContainEqual({ kind: "keyInvalid", uid: "a" });
    expect(issues).toContainEqual({ kind: "keyDuplicate", uid: "c" });
    expect(issues).not.toContainEqual({ kind: "keyDuplicate", uid: "b" });
  });

  it("rejects weights that are not whole numbers inside the range", () => {
    for (const weight of ["", "1.5", "abc", "101", "-101"]) {
      expect(validateScoringDraft(draft([group({ weight })]))).toContainEqual({ kind: "weightInvalid", uid: "g" });
    }
    expect(validateScoringDraft(draft([group({ weight: "-100" })]))).toEqual([]);
    expect(validateScoringDraft(draft([group({ weight: "100" })]))).toEqual([]);
  });

  it("requires terms, caps their count and length", () => {
    expect(validateScoringDraft(draft([group({ terms: "  \n " })]))).toContainEqual({ kind: "termsEmpty", uid: "g" });

    const many = Array.from({ length: 301 }, (_, index) => `term${index}`).join("\n");
    expect(validateScoringDraft(draft([group({ terms: many })]))).toContainEqual({ kind: "termsTooMany", uid: "g" });

    const long = "x".repeat(81);
    expect(validateScoringDraft(draft([group({ terms: `python\n${long}` })]))).toContainEqual({
      kind: "termTooLong",
      uid: "g",
      term: long,
    });
  });

  it("requires a whole minimum score and at least one group", () => {
    expect(validateScoringDraft(draft([group({})], "ten"))).toContainEqual({ kind: "minScoreInvalid" });
    expect(validateScoringDraft(draft([group({})], "-5"))).toEqual([]);
    expect(validateScoringDraft(draft([]))).toContainEqual({ kind: "noGroups" });
  });

  it("marks stack groups from the server and sends them back", () => {
    const server = {
      core: { weight: 12, terms: ["python"] },
      adjacent: { weight: 6, terms: ["react"] },
      domain: { weight: 10, terms: ["fintech"] },
    };

    const edited = toDraft(server, 25, ["core", "adjacent", "gone"]);

    expect(edited.groups.map((item) => [item.key, item.stack])).toEqual([
      ["core", true],
      ["adjacent", true],
      ["domain", false],
    ]);
    expect(draftStackGroups(edited)).toEqual(["core", "adjacent"]);
    expect(validateScoringDraft(edited)).toEqual([]);
  });

  it("follows renames and removals, and skips blank or duplicated keys", () => {
    const renamed = draft([
      group({ uid: "a", key: " stack_main ", stack: true }),
      group({ uid: "b", key: "", stack: true }),
      group({ uid: "c", key: "domain" }),
    ]);

    expect(draftStackGroups(renamed)).toEqual(["stack_main"]);
    expect(draftStackGroups(draft([group({ uid: "a", key: "core", stack: true }), group({ uid: "b", key: "core", stack: true })]))).toEqual(["core"]);
    expect(draftStackGroups(draft([group({ stack: false })]))).toEqual([]);
  });

  it("reports stack groups that are not in the profile", () => {
    expect(validateStackGroups(["core", "adjacent"], ["core", "adjacent", "domain"])).toEqual([]);
    expect(validateStackGroups(["core", "backend"], ["core"])).toEqual(["backend"]);
    expect(validateStackGroups([], [])).toEqual([]);
  });

  it("trims keys when building the request body", () => {
    expect(draftToGroups(draft([group({ key: "  core ", weight: " 7 ", terms: "sql\n" })]))).toEqual({
      core: { weight: 7, terms: ["sql"] },
    });
  });
});
