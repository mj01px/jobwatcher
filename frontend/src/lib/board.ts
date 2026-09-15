import type { Application, ApplicationStatus, Board } from "../api/types";

/** Active stages, in funnel order. */
export const ACTIVE_STATUSES = [
  "interest",
  "applied",
  "screening",
  "challenge",
  "interview",
  "offer",
] as const satisfies readonly ApplicationStatus[];

export const CLOSED_STATUSES = ["rejected", "withdrawn"] as const satisfies readonly ApplicationStatus[];

export const ALL_STATUSES: readonly ApplicationStatus[] = [...ACTIVE_STATUSES, ...CLOSED_STATUSES];

export function isActiveStatus(status: ApplicationStatus): boolean {
  return (ACTIVE_STATUSES as readonly ApplicationStatus[]).includes(status);
}

/** Same order as the endpoint: priority first, most recently updated next. */
export function compareCards(a: Application, b: Application): number {
  return a.priority - b.priority || b.updatedAt.localeCompare(a.updatedAt) || b.id - a.id;
}

/** Today in the browser's local time, as YYYY-MM-DD. */
export function todayIso(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * The board with one application already in its new status, before the API
 * answers. Rejected and withdrawn have no column: moving there takes the card
 * off the board and out of the overdue list, since a closed application is
 * never overdue. Counts follow the move. Unknown ids and same status moves
 * return the board untouched.
 */
export function moveInBoard(board: Board, id: number, status: ApplicationStatus, now: Date = new Date()): Board {
  const current = board.columns.flatMap((column) => column.applications).find((item) => item.id === id);
  if (!current || current.status === status) return board;

  const staysActive = isActiveStatus(status);
  const moved: Application = {
    ...current,
    status,
    // Mirrors the API: moving to applied without a date stamps today.
    appliedOn: status === "applied" && current.appliedOn === null ? todayIso(now) : current.appliedOn,
    isOverdue: staysActive && current.isOverdue,
  };

  const columns = board.columns.map((column) => {
    const applications = column.applications.filter((item) => item.id !== id);
    if (staysActive && column.status === status) applications.push(moved);
    applications.sort(compareCards);
    return { ...column, applications };
  });

  const overdue = staysActive
    ? board.overdue.map((item) => (item.id === id ? moved : item))
    : board.overdue.filter((item) => item.id !== id);

  const counts = { ...board.counts };
  counts[current.status] = Math.max(0, (counts[current.status] ?? 0) - 1);
  counts[status] = (counts[status] ?? 0) + 1;

  return { ...board, columns, overdue, counts };
}
