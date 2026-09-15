import type { FormEvent, ReactNode } from "react";
import { Link } from "react-router";

import { useStartCheck, useStatus } from "../api/hooks";
import { useI18n } from "../i18n/I18nProvider";
import { useDocumentTitle } from "../lib/useDocumentTitle";

interface PageShellProps {
  title: string;
  heading: ReactNode;
  children: ReactNode;
}

/** Page topbar (eyebrow, heading, check control) plus the worker notice. */
export function PageShell({ title, heading, children }: PageShellProps) {
  const { t } = useI18n();
  const { data: status } = useStatus();
  useDocumentTitle(title);

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">JOB MONITOR</p>
          <h1>{heading}</h1>
        </div>
        {status?.isRunning ? (
          <Link className={`check-status${status.isStalled ? " is-stalled" : ""}`} to="/activity">
            <span className="check-status-label">{t(status.isStalled ? "topbar.stuck" : "topbar.checking")}</span>
            {status.progress ? (
              <span className="check-status-count">
                {status.progress.settled}/{status.progress.total}
              </span>
            ) : null}
            <span className="check-status-more">{t("topbar.viewStatus")}</span>
          </Link>
        ) : (
          <CheckNowForm />
        )}
      </header>
      {status && !status.workerOnline ? (
        <p className="worker-notice" role="status">
          {t("worker.offline")}
        </p>
      ) : null}
      {children}
    </>
  );
}

export function CheckNowForm() {
  const { t } = useI18n();
  const startCheck = useStartCheck();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    startCheck.mutate();
  };

  return (
    <form onSubmit={handleSubmit}>
      <button className="button button-primary" type="submit" disabled={startCheck.isPending}>
        <span>{t("topbar.checkNow")}</span>
      </button>
    </form>
  );
}
