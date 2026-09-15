import { describe, expect, it } from "vitest";

import { makeApplication, makeBoard, makeJob } from "../test/fixtures";
import { compareCards, isActiveStatus, moveInBoard, todayIso } from "./board";

const NOW = new Date(2026, 8, 14, 10, 0, 0);

function idsIn(board: ReturnType<typeof makeBoard>, status: string): number[] {
  return board.columns.find((column) => column.status === status)?.applications.map((item) => item.id) ?? [];
}

describe("moveInBoard", () => {
  it("moves a card to another active column and updates the counts", () => {
    const board = makeBoard([
      makeApplication({ id: 1, status: "applied" }),
      makeApplication({ id: 2, status: "applied" }),
      makeApplication({ id: 3, status: "screening" }),
    ]);

    const next = moveInBoard(board, 1, "screening", NOW);

    expect(idsIn(next, "applied")).toEqual([2]);
    expect(idsIn(next, "screening").sort()).toEqual([1, 3]);
    expect(next.counts.applied).toBe(1);
    expect(next.counts.screening).toBe(2);
    expect(next.columns.flatMap((column) => column.applications).find((item) => item.id === 1)?.status).toBe(
      "screening",
    );
  });

  it("keeps the original board untouched", () => {
    const board = makeBoard([makeApplication({ id: 1, status: "applied" })]);
    const snapshot = JSON.stringify(board);

    moveInBoard(board, 1, "offer", NOW);

    expect(JSON.stringify(board)).toBe(snapshot);
  });

  it("takes a card off the board and out of overdue when it closes", () => {
    const board = makeBoard([
      makeApplication({ id: 1, status: "interview", isOverdue: true }),
      makeApplication({ id: 2, status: "interview", isOverdue: true }),
    ]);

    const next = moveInBoard(board, 1, "rejected", NOW);

    expect(next.columns.flatMap((column) => column.applications).map((item) => item.id)).toEqual([2]);
    expect(next.overdue.map((item) => item.id)).toEqual([2]);
    expect(next.counts.rejected).toBe(1);
    expect(next.counts.interview).toBe(1);
  });

  it("keeps the overdue flag while the card stays active", () => {
    const board = makeBoard([makeApplication({ id: 1, status: "applied", isOverdue: true })]);

    const next = moveInBoard(board, 1, "interview", NOW);

    expect(next.overdue.map((item) => [item.id, item.status])).toEqual([[1, "interview"]]);
    expect(idsIn(next, "interview")).toEqual([1]);
  });

  it("stamps today as applied on when moving to applied without a date", () => {
    const board = makeBoard([makeApplication({ id: 1, status: "interest", appliedOn: null })]);

    const next = moveInBoard(board, 1, "applied", NOW);

    expect(next.columns.find((column) => column.status === "applied")?.applications[0]?.appliedOn).toBe("2026-09-14");
  });

  it("does not overwrite an existing applied date", () => {
    const board = makeBoard([makeApplication({ id: 1, status: "screening", appliedOn: "2026-08-01" })]);

    const next = moveInBoard(board, 1, "applied", NOW);

    expect(next.columns.find((column) => column.status === "applied")?.applications[0]?.appliedOn).toBe("2026-08-01");
  });

  it("sorts the destination column by priority, then most recently updated", () => {
    const board = makeBoard([
      makeApplication({ id: 1, status: "applied", priority: 2, updatedAt: "2026-09-01T00:00:00Z" }),
      makeApplication({ id: 2, status: "offer", priority: 1, updatedAt: "2026-09-02T00:00:00Z" }),
      makeApplication({ id: 3, status: "offer", priority: 2, updatedAt: "2026-09-05T00:00:00Z" }),
    ]);

    const next = moveInBoard(board, 1, "offer", NOW);

    expect(idsIn(next, "offer")).toEqual([2, 3, 1]);
  });

  it("returns the same board for unknown ids and same status moves", () => {
    const board = makeBoard([makeApplication({ id: 1, status: "applied" })]);

    expect(moveInBoard(board, 99, "offer", NOW)).toBe(board);
    expect(moveInBoard(board, 1, "applied", NOW)).toBe(board);
  });
});

describe("board helpers", () => {
  it("knows which statuses are active", () => {
    expect(isActiveStatus("interest")).toBe(true);
    expect(isActiveStatus("offer")).toBe(true);
    expect(isActiveStatus("rejected")).toBe(false);
    expect(isActiveStatus("withdrawn")).toBe(false);
  });

  it("orders ties by id when priority and update time match", () => {
    const a = makeApplication({ id: 1, job: makeJob({ id: 1 }) });
    const b = makeApplication({ id: 2, job: makeJob({ id: 2 }) });
    expect([a, b].sort(compareCards).map((item) => item.id)).toEqual([2, 1]);
  });

  it("formats today in local time", () => {
    expect(todayIso(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});
