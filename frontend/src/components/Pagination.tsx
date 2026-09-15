import { Link, useLocation } from "react-router";

import { ELLIPSIS, pageSequence } from "../lib/pagination";

interface PaginationProps {
  current: number;
  totalPages: number;
}

export function Pagination({ current, totalPages }: PaginationProps) {
  const location = useLocation();
  if (totalPages <= 1) return null;

  const hrefFor = (page: number) => {
    const params = new URLSearchParams(location.search);
    params.set("page", String(page));
    return `${location.pathname}?${params.toString()}`;
  };

  // An ellipsis can appear twice, so its key uses the page number before it.
  let previousPage = 0;
  return (
    <nav className="pagination" aria-label="Pagination">
      {pageSequence(current, totalPages).map((entry) => {
        if (entry === ELLIPSIS) {
          return (
            <span key={`ellipsis-after-${previousPage}`} className="pagination-ellipsis" aria-hidden="true">
              {ELLIPSIS}
            </span>
          );
        }
        previousPage = entry;
        if (entry === current) {
          return (
            <span key={entry} className="pagination-item is-current" aria-current="page">
              {entry}
            </span>
          );
        }
        return (
          <Link key={entry} className="pagination-item" to={hrefFor(entry)}>
            {entry}
          </Link>
        );
      })}
    </nav>
  );
}
