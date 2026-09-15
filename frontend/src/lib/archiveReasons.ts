import type { ManualArchiveReason } from "../api/types";

/**
 * Reasons offered in the archive modal. "applied" is not offered: Applied
 * moves the job into the applications funnel.
 * Old rows archived as applied still display their label.
 */
export const ARCHIVE_REASONS = [
  "not_interested",
  "onsite",
  "hybrid",
  "remote",
  "requirements",
  "compensation",
  "closed",
  "other",
] as const satisfies readonly ManualArchiveReason[];
