import type { ScoringGroup } from "../api/types";

/** Limits enforced by PUT /settings/scoring (docs/API.md and docs/API-v3.md). */
export const GROUP_KEY_PATTERN = /^[a-z0-9_]{1,40}$/;
export const WEIGHT_MIN = -100;
export const WEIGHT_MAX = 100;
export const MAX_TERMS = 300;
export const TERM_MAX_LENGTH = 80;
/** Backend default for `stackGroups`; sent with a reset to the default profile. */
export const DEFAULT_STACK_GROUPS: readonly string[] = ["core", "adjacent"];

/** One group as edited on screen: terms as one per line text, weight as typed. */
export interface GroupDraft {
  /** Stable React key; the group key itself is editable. */
  uid: string;
  key: string;
  weight: string;
  terms: string;
  /** Counts as stack: a highlight needs a hit in at least one stack group. */
  stack: boolean;
}

export interface ScoringDraft {
  groups: GroupDraft[];
  minScore: string;
}

export type ScoringIssue =
  | { kind: "keyInvalid"; uid: string }
  | { kind: "keyDuplicate"; uid: string }
  | { kind: "weightInvalid"; uid: string }
  | { kind: "termsEmpty"; uid: string }
  | { kind: "termsTooMany"; uid: string }
  | { kind: "termTooLong"; uid: string; term: string }
  | { kind: "minScoreInvalid" }
  | { kind: "noGroups" }
  | { kind: "stackUnknown"; keys: string[] };

let uidCounter = 0;
export function nextGroupUid(): string {
  uidCounter += 1;
  return `group-${uidCounter}`;
}

export function splitTerms(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function toDraft(
  groups: Record<string, ScoringGroup>,
  minScore: number,
  stackGroups: readonly string[] = [],
): ScoringDraft {
  return {
    groups: Object.entries(groups).map(([key, group]) => ({
      uid: nextGroupUid(),
      key,
      weight: String(group.weight),
      terms: group.terms.join("\n"),
      stack: stackGroups.includes(key),
    })),
    minScore: String(minScore),
  };
}

function parseInteger(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  return Number.parseInt(trimmed, 10);
}

/** Every problem the API would reject, so the form can point at the field. */
export function validateScoringDraft(draft: ScoringDraft): ScoringIssue[] {
  const issues: ScoringIssue[] = [];
  if (draft.groups.length === 0) issues.push({ kind: "noGroups" });

  const seen = new Set<string>();
  for (const group of draft.groups) {
    const key = group.key.trim();
    if (!GROUP_KEY_PATTERN.test(key)) {
      issues.push({ kind: "keyInvalid", uid: group.uid });
    } else if (seen.has(key)) {
      issues.push({ kind: "keyDuplicate", uid: group.uid });
    }
    seen.add(key);

    const weight = parseInteger(group.weight);
    if (weight === null || weight < WEIGHT_MIN || weight > WEIGHT_MAX) {
      issues.push({ kind: "weightInvalid", uid: group.uid });
    }

    const terms = splitTerms(group.terms);
    if (terms.length === 0) issues.push({ kind: "termsEmpty", uid: group.uid });
    if (terms.length > MAX_TERMS) issues.push({ kind: "termsTooMany", uid: group.uid });
    const tooLong = terms.find((term) => term.length > TERM_MAX_LENGTH);
    if (tooLong !== undefined) issues.push({ kind: "termTooLong", uid: group.uid, term: tooLong });
  }

  if (parseInteger(draft.minScore) === null) issues.push({ kind: "minScoreInvalid" });

  const unknown = validateStackGroups(draftStackGroups(draft), [...seen]);
  if (unknown.length > 0) issues.push({ kind: "stackUnknown", keys: unknown });
  return issues;
}

/** Stack group keys that are not groups of the profile; the API answers 400 for them. */
export function validateStackGroups(stackGroups: readonly string[], groupKeys: readonly string[]): string[] {
  const known = new Set(groupKeys);
  return stackGroups.filter((key) => !known.has(key));
}

/**
 * The `stackGroups` PUT value. Flags live on the groups, so removing or renaming
 * a group never leaves a dangling key. Blank keys are skipped (keyInvalid covers them).
 */
export function draftStackGroups(draft: ScoringDraft): string[] {
  const keys = draft.groups.filter((group) => group.stack).map((group) => group.key.trim());
  return [...new Set(keys)].filter(Boolean);
}

/** The PUT body for a valid draft. Call only after validateScoringDraft returned no issues. */
export function draftToGroups(draft: ScoringDraft): Record<string, ScoringGroup> {
  const groups: Record<string, ScoringGroup> = {};
  for (const group of draft.groups) {
    groups[group.key.trim()] = {
      weight: parseInteger(group.weight) ?? 0,
      terms: splitTerms(group.terms),
    };
  }
  return groups;
}

export function draftMinScore(draft: ScoringDraft): number {
  return parseInteger(draft.minScore) ?? 0;
}
