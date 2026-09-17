import { Link, NavLink, Outlet } from "react-router";

import { useRunCompletionRefresh, useStatus, useVisitPings } from "../api/hooks";
import markUrl from "../assets/job-watcher-mark.svg";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";

interface NavItem {
  to: string;
  mark: string;
  label: TranslationKey;
  end: boolean;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", mark: "01", label: "nav.overview", end: true },
  { to: "/jobs/highlighted", mark: "02", label: "nav.highlighted", end: true },
  // Not `end`: the closed tab lives under /applications/closed.
  { to: "/applications", mark: "03", label: "nav.applications", end: false },
  { to: "/jobs", mark: "04", label: "nav.jobs", end: true },
  { to: "/jobs/archived", mark: "05", label: "nav.archived", end: true },
  { to: "/sources", mark: "06", label: "nav.sources", end: true },
  { to: "/settings", mark: "07", label: "nav.settings", end: true },
  { to: "/activity", mark: "08", label: "nav.activity", end: true },
];

const navLinkClass = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link active" : "nav-link");

export function Layout() {
  const { t } = useI18n();
  const { data: status } = useStatus();
  useRunCompletionRefresh(status?.isRunning);
  useVisitPings();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="Job Watcher home">
          <img className="brand-mark" src={markUrl} alt="" />
          <span className="brand-name">
            JOB
            <br />
            WATCHER
          </span>
        </Link>

        <nav className="main-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} className={navLinkClass} to={item.to} end={item.end}>
              <span className="nav-mark">{item.mark}</span>
              <span>{t(item.label)}</span>
              {item.to === "/activity" && status?.isRunning ? (
                <span className="nav-pulse" aria-hidden="true" />
              ) : null}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
