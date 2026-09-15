import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { queryKeys } from "../api/hooks";
import type { Job } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { useJobActions } from "./JobActionsProvider";
import { JobRow } from "./JobRow";

type RowState = "removing" | "hidden" | "entering";

interface JobListProps {
  jobs: Job[] | undefined;
  isError?: boolean;
  /** Called when the last visible row was archived away. */
  onEmptied?: () => void;
}

export function JobList({ jobs, isError = false, onEmptied }: JobListProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { lastOpenedId, subscribeRows } = useJobActions();
  const [rowStates, setRowStates] = useState<Record<number, RowState>>({});

  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  useEffect(
    () =>
      subscribeRows({
        remove: (jobId) => {
          if (!jobsRef.current?.some((job) => job.id === jobId)) return;
          setRowStates((current) => ({ ...current, [jobId]: "removing" }));
        },
        restore: (jobId) => {
          if (!jobsRef.current?.some((job) => job.id === jobId)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
            return;
          }
          setRowStates((current) => ({ ...current, [jobId]: "entering" }));
        },
      }),
    [queryClient, subscribeRows],
  );

  const handleRemoved = useCallback((jobId: number) => {
    setRowStates((current) => ({ ...current, [jobId]: "hidden" }));
  }, []);

  const handleEntered = useCallback((jobId: number) => {
    setRowStates((current) => {
      const next = { ...current };
      delete next[jobId];
      return next;
    });
  }, []);

  const visibleJobs = (jobs ?? []).filter((job) => rowStates[job.id] !== "hidden");
  const emptiedByRemoval = jobs !== undefined && jobs.length > 0 && visibleJobs.length === 0;

  const onEmptiedRef = useRef(onEmptied);
  onEmptiedRef.current = onEmptied;
  useEffect(() => {
    if (emptiedByRemoval) onEmptiedRef.current?.();
  }, [emptiedByRemoval]);

  if (isError && !jobs) {
    return <p className="load-error">{t("common.loadFailed")}</p>;
  }

  return (
    <div className="job-list">
      {visibleJobs.map((job) => (
        <JobRow
          key={job.id}
          job={job}
          removing={rowStates[job.id] === "removing"}
          entering={rowStates[job.id] === "entering"}
          isLastOpened={lastOpenedId !== null && String(job.id) === lastOpenedId}
          onRemoved={handleRemoved}
          onEntered={handleEntered}
        />
      ))}
      {jobs !== undefined && visibleJobs.length === 0 ? (
        <div className="empty-state">
          <span className="empty-number">00</span>
          <h2>{t("job.emptyTitle")}</h2>
          <p>{t("job.emptyText")}</p>
        </div>
      ) : null}
    </div>
  );
}
