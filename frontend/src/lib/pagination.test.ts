import { describe, expect, it } from "vitest";

import { ELLIPSIS, normalizePage, pageSequence, type PageEntry } from "./pagination";

const E = ELLIPSIS;
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, index) => from + index);

describe("pageSequence", () => {
  it("returns an empty sequence for zero pages", () => {
    expect(pageSequence(1, 0)).toEqual([]);
  });

  it("handles a single page", () => {
    expect(pageSequence(1, 1)).toEqual([1]);
  });

  it("shows every page up to seven pages", () => {
    for (let total = 1; total <= 7; total += 1) {
      for (let current = 1; current <= total; current += 1) {
        expect(pageSequence(current, total)).toEqual(range(1, total));
      }
    }
  });

  it("uses an ellipsis above seven pages", () => {
    expect(pageSequence(1, 8)).toContain(E);
  });

  it("matches the worked example at the beginning", () => {
    expect(pageSequence(1, 11)).toEqual([1, 2, 3, 4, 5, 6, E, 11]);
    expect(pageSequence(2, 11)).toEqual([1, 2, 3, 4, 5, 6, E, 11]);
    expect(pageSequence(3, 11)).toEqual([1, 2, 3, 4, 5, 6, E, 11]);
  });

  it("transitions into the middle", () => {
    expect(pageSequence(4, 11)).toEqual([1, 2, 3, 4, 5, 6, E, 11]);
    expect(pageSequence(5, 11)).toEqual([1, E, 3, 4, 5, 6, 7, E, 11]);
  });

  it("centers the window", () => {
    expect(pageSequence(6, 11)).toEqual([1, E, 4, 5, 6, 7, 8, E, 11]);
  });

  it("transitions into the end", () => {
    expect(pageSequence(7, 11)).toEqual([1, E, 5, 6, 7, 8, 9, E, 11]);
    expect(pageSequence(8, 11)).toEqual([1, E, 6, 7, 8, 9, 10, 11]);
  });

  it("handles the penultimate and last pages", () => {
    expect(pageSequence(10, 11)).toEqual([1, E, 6, 7, 8, 9, 10, 11]);
    expect(pageSequence(11, 11)).toEqual([1, E, 6, 7, 8, 9, 10, 11]);
  });

  it("handles twenty pages", () => {
    expect(pageSequence(1, 20)).toEqual([1, 2, 3, 4, 5, 6, E, 20]);
    expect(pageSequence(10, 20)).toEqual([1, E, 8, 9, 10, 11, 12, E, 20]);
    expect(pageSequence(19, 20)).toEqual([1, E, 15, 16, 17, 18, 19, 20]);
    expect(pageSequence(20, 20)).toEqual([1, E, 15, 16, 17, 18, 19, 20]);
  });

  it("handles fifty pages", () => {
    expect(pageSequence(1, 50)).toEqual([1, 2, 3, 4, 5, 6, E, 50]);
    expect(pageSequence(25, 50)).toEqual([1, E, 23, 24, 25, 26, 27, E, 50]);
    expect(pageSequence(49, 50)).toEqual([1, E, 45, 46, 47, 48, 49, 50]);
    expect(pageSequence(50, 50)).toEqual([1, E, 45, 46, 47, 48, 49, 50]);
  });

  it("handles one hundred pages", () => {
    expect(pageSequence(1, 100)).toEqual([1, 2, 3, 4, 5, 6, E, 100]);
    expect(pageSequence(50, 100)).toEqual([1, E, 48, 49, 50, 51, 52, E, 100]);
    expect(pageSequence(99, 100)).toEqual([1, E, 95, 96, 97, 98, 99, 100]);
    expect(pageSequence(100, 100)).toEqual([1, E, 95, 96, 97, 98, 99, 100]);
  });

  it("clamps a current page beyond the total", () => {
    expect(pageSequence(999, 20)).toEqual(pageSequence(20, 20));
  });

  it("clamps a current page below one", () => {
    expect(pageSequence(0, 20)).toEqual(pageSequence(1, 20));
  });

  const eachSequence = (totals: number[], check: (sequence: PageEntry[], total: number, current: number) => void) => {
    for (const total of totals) {
      for (let current = 1; current <= total; current += 1) check(pageSequence(current, total), total, current);
    }
  };

  it("never separates truly adjacent numbers", () => {
    eachSequence([8, 9, 11, 20, 50, 100], (sequence) => {
      sequence.slice(1).forEach((entry, index) => {
        const previous = sequence[index];
        if (previous !== E && entry !== E && previous !== undefined) expect(entry - previous).toBe(1);
      });
    });
  });

  it("always hides at least one page behind an ellipsis", () => {
    eachSequence([8, 9, 11, 20, 50, 100], (sequence) => {
      sequence.forEach((entry, index) => {
        if (entry !== E) return;
        const before = sequence[index - 1];
        const after = sequence[index + 1];
        expect(typeof before).toBe("number");
        expect(typeof after).toBe("number");
        expect((after as number) - (before as number)).toBeGreaterThan(1);
      });
    });
  });

  it("always includes the current page", () => {
    eachSequence([8, 11, 20, 50, 100], (sequence, _total, current) => {
      expect(sequence).toContain(current);
    });
  });

  it("always includes the first and last pages", () => {
    eachSequence([8, 11, 20, 50, 100], (sequence, total) => {
      expect(sequence).toContain(1);
      expect(sequence).toContain(total);
    });
  });
});

describe("normalizePage", () => {
  it("defaults a missing page to one", () => {
    expect(normalizePage(null, 5)).toBe(1);
  });

  it("defaults a non numeric page to one", () => {
    expect(normalizePage("abc", 5)).toBe(1);
  });

  it("defaults zero to one", () => {
    expect(normalizePage("0", 5)).toBe(1);
  });

  it("defaults a negative page to one", () => {
    expect(normalizePage("-3", 5)).toBe(1);
  });

  it("clamps a page beyond the total to the last page", () => {
    expect(normalizePage("999", 5)).toBe(5);
  });

  it("passes a valid page through", () => {
    expect(normalizePage("3", 5)).toBe(3);
  });

  it("always normalizes to one when there are no pages", () => {
    expect(normalizePage("1", 0)).toBe(1);
    expect(normalizePage("5", 0)).toBe(1);
    expect(normalizePage(null, 0)).toBe(1);
  });
});
