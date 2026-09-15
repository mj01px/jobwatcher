import { memo, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";

import type { Job } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import {
  ROW_COLLAPSE_PHASE_MS,
  ROW_ENTER_MS,
  ROW_LEAVE_PHASE_MS,
  nextFrame,
  prefersReducedMotion,
} from "../lib/motion";
import { companyLine, JobChips, KindMark, ScoreBadge } from "./JobFacts";
import { useJobActions, type FunnelEntry } from "./JobActionsProvider";
import { OpenJobLink } from "./OpenJobLink";

type RowPhase = "idle" | "leaving" | "collapsing" | "entering";

interface JobRowProps {
  job: Job;
  removing: boolean;
  entering: boolean;
  isLastOpened: boolean;
  onRemoved: (jobId: number) => void;
  onEntered: (jobId: number) => void;
}

export const JobRow = memo(function JobRow({ job, removing, entering, isLastOpened, onRemoved, onEntered }: JobRowProps) {
  const { t, formatDateTime } = useI18n();
  const { moveToFunnel, openArchiveModal, restoreJob, openJobDetail, isPromptDismissed, dismissPrompt } = useJobActions();
  const rowRef = useRef<HTMLElement>(null);
  const [phase, setPhase] = useState<RowPhase>(entering ? "entering" : "idle");
  const [busy, setBusy] = useState(false);

  // Exit: fade and slide, then collapse the height, then unmount.
  useLayoutEffect(() => {
    if (!removing) return undefined;
    const row = rowRef.current;
    if (!row || prefersReducedMotion()) {
      onRemoved(job.id);
      return undefined;
    }
    row.style.height = `${row.offsetHeight}px`;
    row.style.overflow = "hidden";
    void row.offsetHeight; // force reflow before animating
    setPhase("leaving");
    let collapseTimer = 0;
    const leaveTimer = window.setTimeout(() => {
      setPhase("collapsing");
      row.style.height = "0px";
      collapseTimer = window.setTimeout(() => onRemoved(job.id), ROW_COLLAPSE_PHASE_MS);
    }, ROW_LEAVE_PHASE_MS);
    return () => {
      window.clearTimeout(leaveTimer);
      window.clearTimeout(collapseTimer);
    };
  }, [removing, job.id, onRemoved]);

  // Enter (after Undo): start faded at zero height, then grow into place.
  useLayoutEffect(() => {
    if (!entering) return undefined;
    const row = rowRef.current;
    if (!row || prefersReducedMotion()) {
      setPhase("idle");
      onEntered(job.id);
      return undefined;
    }
    // Undo can land mid exit, so clear any leftover exit sizing before measuring.
    row.style.height = "";
    row.style.overflow = "";
    const targetHeight = row.offsetHeight;
    row.style.height = "0px";
    row.style.overflow = "hidden";
    void row.offsetHeight; // force reflow before animating
    let settleTimer = 0;
    const cancelFrame = nextFrame(() => {
      row.style.height = `${targetHeight}px`;
      setPhase("idle");
      settleTimer = window.setTimeout(() => {
        row.style.height = "";
        row.style.overflow = "";
        onEntered(job.id);
      }, ROW_ENTER_MS);
    });
    return () => {
      cancelFrame();
      window.clearTimeout(settleTimer);
    };
  }, [entering, job.id, onEntered]);

  const handleFunnel = async (status: FunnelEntry) => {
    setBusy(true);
    try {
      await moveToFunnel(job, status);
    } catch {
      setBusy(false);
    }
  };

  const handleRestore = async () => {
    setBusy(true);
    try {
      await restoreJob(job);
    } catch {
      setBusy(false);
    }
  };

  const onAppliedClick = () => {
    void handleFunnel("applied");
  };
  const onInterestedClick = () => {
    void handleFunnel("interest");
  };
  const onRestoreClick = () => {
    void handleRestore();
  };
  const onArchiveClick = () => {
    openArchiveModal(job);
  };
  const onTitleClick = () => {
    openJobDetail(job);
  };
  const onNotNowClick = () => {
    dismissPrompt(job.id);
  };

  const className = [
    "job-row",
    job.isNew ? "is-new" : "",
    job.isHighlighted ? "is-highlighted" : "",
    isLastOpened ? "is-last-opened" : "",
    phase === "leaving" || phase === "collapsing" ? "is-leaving" : "",
    phase === "collapsing" ? "is-collapsing" : "",
    phase === "entering" ? "is-entering" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const isActive = job.status === "active";
  const inFunnel = job.application !== null;
  // After "Open job" the row itself asks, instead of a modal (docs/API-v3.md, section 6).
  const showPrompt = isLastOpened && isActive && !inFunnel && !isPromptDismissed(job.id);

  return (
    <article ref={rowRef} className={className} data-job-id={job.id} data-status={job.status}>
      <div className="job-state" aria-hidden="true" />
      <div className="job-copy">
        <div className="job-meta">
          <KindMark kind={job.sourceKind} />
          <span>{companyLine(job)}</span>
          {job.isNew ? <span className="tag tag-new">{t("job.new")}</span> : null}
          {job.reopenedAt && isActive ? <span className="tag tag-reopened">{t("job.reopened")}</span> : null}
          {job.isHighlighted ? <span className="tag tag-highlight">{t("job.highlight")}</span> : null}
          {job.firstVisitedAt ? <span className="tag tag-visited">{t("job.visited")}</span> : null}
          {isLastOpened ? <span className="tag tag-last-opened">{t("job.lastOpened")}</span> : null}
          {job.application ? (
            <span className="tag tag-funnel">{t(`applicationStatus.${job.application.status}`)}</span>
          ) : null}
          {job.archiveReason ? <span className="tag tag-muted">{t(`reason.${job.archiveReason}`)}</span> : null}
        </div>
        <h2>
          <button type="button" className="job-title-button" onClick={onTitleClick}>
            {job.title}
          </button>
        </h2>
        <JobChips job={job} />
        <p>
          {t("job.firstSeen")} <time dateTime={job.firstSeenAt}>{formatDateTime(job.firstSeenAt)}</time>
          {job.scoreTags.length > 0 ? (
            <span className="job-tags-inline" title={job.scoreTags.join(", ")}>
              {" · "}
              {job.scoreTags.slice(0, 4).join(", ")}
            </span>
          ) : null}
        </p>
      </div>
      <div className="job-actions">
        <ScoreBadge score={job.score} highlighted={job.isHighlighted} />
        <OpenJobLink job={job} />
        {inFunnel ? (
          <Link className="button button-quiet" to="/applications">
            {t("job.viewInFunnel")}
          </Link>
        ) : isActive ? (
          <>
            <button type="button" className="button button-positive" disabled={busy} onClick={onAppliedClick}>
              <span aria-hidden="true">✓</span>
              <span>{t("job.applied")}</span>
            </button>
            <button type="button" className="button button-quiet" disabled={busy} onClick={onInterestedClick}>
              {t("job.interested")}
            </button>
            <button type="button" className="button button-quiet" onClick={onArchiveClick}>
              {t("job.archive")}
            </button>
          </>
        ) : null}
        {!isActive ? (
          <button type="button" className="button button-quiet" disabled={busy} onClick={onRestoreClick}>
            {t("job.restore")}
          </button>
        ) : null}
      </div>
      {showPrompt ? (
        <div className="apply-prompt" role="group" aria-label={t("job.prompt.question")}>
          <p>{t("job.prompt.question")}</p>
          <div className="apply-prompt-actions">
            <button type="button" className="button button-positive button-small" disabled={busy} onClick={onAppliedClick}>
              <span aria-hidden="true">✓</span>
              <span>{t("job.prompt.applied")}</span>
            </button>
            <button type="button" className="button button-quiet button-small" disabled={busy} onClick={onInterestedClick}>
              {t("job.prompt.interested")}
            </button>
            <button type="button" className="button button-quiet button-small" onClick={onNotNowClick}>
              {t("job.prompt.notNow")}
            </button>
          </div>
        </div>
      ) : null}
      {job.archiveNote ? <p className="archive-note">{job.archiveNote}</p> : null}
    </article>
  );
});
