import type { CollectedSourceKind, SourceKind } from "../api/types";

export const SOURCE_KINDS = ["inhire", "gupy", "github"] as const satisfies readonly CollectedSourceKind[];

export const SOURCE_KIND_LABELS: Record<SourceKind, string> = {
  inhire: "InHire",
  gupy: "Gupy",
  github: "GitHub",
  manual: "Manual",
};

const GITHUB_REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

/** Same rules as POST /sources, so the form can say what is wrong before sending. */
export function validateSourceTarget(kind: CollectedSourceKind, raw: string): boolean {
  const target = raw.trim();
  switch (kind) {
    case "inhire": {
      let url: URL;
      try {
        url = new URL(target);
      } catch {
        return false;
      }
      return (url.protocol === "http:" || url.protocol === "https:") && url.hostname.toLowerCase().endsWith(".inhire.app");
    }
    case "gupy":
      return target.length >= 2 && target.length <= 100;
    case "github":
      return GITHUB_REPO.test(target);
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

/** Link to what a source watches, for the Sources page. */
export function sourceHref(kind: CollectedSourceKind, target: string): string {
  switch (kind) {
    case "inhire":
      return target;
    case "gupy":
      return `https://portal.gupy.io/job-search/term=${encodeURIComponent(target)}`;
    case "github":
      return `https://github.com/${target}/issues`;
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}
