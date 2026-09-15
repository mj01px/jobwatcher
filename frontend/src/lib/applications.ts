import type { Application, ApplicationStatus, Board } from "../api/types";

/** Tabs of the applications page, in order. */
export type ApplicationsView = "active" | "stalled" | "inProgress" | "closed";

/** Days without movement after which an application asks for a follow-up. */
export const STALLED_DAYS = 10;
/** From this many idle days on, the drawer shows the waiting tile. */
export const WAITING_TILE_DAYS = 2;

export const IN_PROGRESS_STATUSES = ["screening", "challenge", "interview", "offer"] as const satisfies readonly ApplicationStatus[];

/** Waiting groups, from the longest wait to the freshest. */
export type WaitGroupId = "late" | "recent" | "fresh";
export const WAIT_GROUP_ORDER: readonly WaitGroupId[] = ["late", "recent", "fresh"];

export interface WaitGroup {
  id: WaitGroupId;
  applications: Application[];
}

export interface ViewCounts {
  active: number;
  stalled: number;
  inProgress: number;
}

export function waitGroupOf(daysIdle: number): WaitGroupId {
  if (daysIdle >= STALLED_DAYS) return "late";
  if (daysIdle >= 2) return "recent";
  return "fresh";
}

/** Every active application on the board, whatever its column. */
export function flattenBoard(board: Board): Application[] {
  return board.columns.flatMap((column) => column.applications);
}

export function isStalled(application: Application): boolean {
  return application.daysIdle >= STALLED_DAYS;
}

export function isInProgress(application: Application): boolean {
  return (IN_PROGRESS_STATUSES as readonly ApplicationStatus[]).includes(application.status);
}

/** The active applications a board tab lists. The closed tab reads its own endpoint. */
export function filterForView(applications: readonly Application[], view: Exclude<ApplicationsView, "closed">): Application[] {
  if (view === "stalled") return applications.filter(isStalled);
  if (view === "inProgress") return applications.filter(isInProgress);
  return [...applications];
}

export function countViews(applications: readonly Application[]): ViewCounts {
  return {
    active: applications.length,
    stalled: applications.filter(isStalled).length,
    inProgress: applications.filter(isInProgress).length,
  };
}

/** Longest wait first, then the highest priority, then the newest id. */
export function compareByWait(a: Application, b: Application): number {
  return b.daysIdle - a.daysIdle || a.priority - b.priority || b.id - a.id;
}

/** Applications split into waiting groups in display order; empty groups are left out. */
export function groupByWait(applications: readonly Application[]): WaitGroup[] {
  const sorted = [...applications].sort(compareByWait);
  return WAIT_GROUP_ORDER.map((id) => ({
    id,
    applications: sorted.filter((application) => waitGroupOf(application.daysIdle) === id),
  })).filter((group) => group.applications.length > 0);
}

/** "Recebi resposta" only makes sense before the company answered. */
export function canReceiveAnswer(status: ApplicationStatus): boolean {
  return status === "interest" || status === "applied";
}
