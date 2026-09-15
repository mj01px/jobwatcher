import { describe, expect, it } from "vitest";

import { makeApplication, makeBoard } from "../test/fixtures";
import {
  canReceiveAnswer,
  countViews,
  filterForView,
  flattenBoard,
  groupByWait,
  waitGroupOf,
} from "./applications";

describe("waiting groups", () => {
  it("splits by idle days at 2 and 10", () => {
    expect([0, 1, 2, 9, 10, 40].map(waitGroupOf)).toEqual(["fresh", "fresh", "recent", "recent", "late", "late"]);
  });

  it("orders groups from the longest wait and hides empty ones", () => {
    const groups = groupByWait([
      makeApplication({ id: 1, daysIdle: 0 }),
      makeApplication({ id: 2, daysIdle: 11 }),
      makeApplication({ id: 3, daysIdle: 1 }),
    ]);

    expect(groups.map((group) => [group.id, group.applications.map((item) => item.id)])).toEqual([
      ["late", [2]],
      ["fresh", [3, 1]],
    ]);
  });

  it("sorts inside a group by idle days desc, then priority asc, then newest id", () => {
    const [late] = groupByWait([
      makeApplication({ id: 1, daysIdle: 11, priority: 3 }),
      makeApplication({ id: 2, daysIdle: 14, priority: 5 }),
      makeApplication({ id: 3, daysIdle: 11, priority: 1 }),
      makeApplication({ id: 4, daysIdle: 11, priority: 3 }),
    ]);

    expect(late?.applications.map((item) => item.id)).toEqual([2, 3, 4, 1]);
  });
});

describe("tabs", () => {
  const applications = [
    makeApplication({ id: 1, status: "applied", daysIdle: 12 }),
    makeApplication({ id: 2, status: "interest", daysIdle: 0 }),
    makeApplication({ id: 3, status: "interview", daysIdle: 3 }),
    makeApplication({ id: 4, status: "offer", daysIdle: 10 }),
  ];

  it("flattens every board column", () => {
    expect(flattenBoard(makeBoard(applications)).map((item) => item.id).sort()).toEqual([1, 2, 3, 4]);
  });

  it("filters each tab", () => {
    const ids = (view: "active" | "stalled" | "inProgress") => filterForView(applications, view).map((item) => item.id);
    expect(ids("active")).toEqual([1, 2, 3, 4]);
    expect(ids("stalled")).toEqual([1, 4]);
    expect(ids("inProgress")).toEqual([3, 4]);
  });

  it("counts each tab", () => {
    expect(countViews(applications)).toEqual({ active: 4, stalled: 2, inProgress: 2 });
  });

  it("offers the answer action only before an answer", () => {
    expect(canReceiveAnswer("interest")).toBe(true);
    expect(canReceiveAnswer("applied")).toBe(true);
    expect(canReceiveAnswer("screening")).toBe(false);
    expect(canReceiveAnswer("rejected")).toBe(false);
  });
});
