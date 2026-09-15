import type { MouseEvent } from "react";

import type { Job } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { useJobActions } from "./JobActionsProvider";

/** "Open job": a normal new tab link, unless the desktop app opens it itself. */
export function OpenJobLink({ job }: { job: Job }) {
  const { t } = useI18n();
  const { openJob } = useJobActions();

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (openJob(job)) event.preventDefault();
  };

  return (
    <a className="button button-link" href={job.url} target="_blank" rel="noopener noreferrer" onClick={handleClick}>
      <span>{t("job.open")}</span>
      <span aria-hidden="true">↗</span>
    </a>
  );
}
