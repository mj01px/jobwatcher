import { memo, type ChangeEvent } from "react";

import type { Application, ApplicationStatus } from "../../api/types";
import { useI18n } from "../../i18n/I18nProvider";
import { canReceiveAnswer, waitGroupOf } from "../../lib/applications";
import { ALL_STATUSES } from "../../lib/board";
import { companyLine, KindMark } from "../JobFacts";

export type DrawerFocus = "nextStep" | null;

interface ApplicationRowProps {
  application: Application;
  onOpen: (application: Application, focus: DrawerFocus) => void;
  onMove: (application: Application, status: ApplicationStatus) => void;
  onAnswer: (application: Application) => void;
}

/** Score block for the list: cyan from 25 up, coral below zero, soft otherwise. */
function scoreTone(score: number): string {
  if (score >= 25) return "is-high";
  if (score < 0) return "is-negative";
  return "";
}

export function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

/** One application in the list: wait, job, stage, next step and the answer action. */
export const ApplicationRow = memo(function ApplicationRow({ application, onOpen, onMove, onAnswer }: ApplicationRowProps) {
  const { t, formatDayMonth } = useI18n();
  const { job } = application;
  const group = waitGroupOf(application.daysIdle);
  const hasNextStep = Boolean(application.nextStep || application.nextStepOn);

  const handleOpen = () => onOpen(application, null);
  const handleNextStep = () => onOpen(application, "nextStep");
  const handleMove = (event: ChangeEvent<HTMLSelectElement>) => onMove(application, event.target.value as ApplicationStatus);
  const handleAnswer = () => onAnswer(application);

  const days = application.daysIdle;

  return (
    <article className={`application-row wait-${group}`} data-application-id={application.id}>
      <span className="application-row-bar" aria-hidden="true" />
      <div className="application-wait">
        {days === 0 ? (
          <strong className="is-word">{t("applications.waitToday")}</strong>
        ) : (
          <>
            <strong>{days}</strong>
            <span>{t(days === 1 ? "applications.waitDay" : "applications.waitDays")}</span>
          </>
        )}
      </div>

      <div className="application-job">
        <div className="application-job-meta">
          <KindMark kind={job.sourceKind} />
          <span className="application-company">{companyLine(job)}</span>
          <span className={`score-badge score-badge-small ${scoreTone(job.score)}`.trim()} title={t("job.scoreTitle")}>
            <span className="sr-only">{t("job.score")}</span>
            {job.score}
          </span>
        </div>
        <h3>
          <button type="button" className="application-title" title={job.title} onClick={handleOpen}>
            {job.title}
          </button>
        </h3>
      </div>

      <label className={`application-stage status-${application.status}`}>
        <span className="sr-only">{t("applications.moveTo", { title: job.title })}</span>
        <select value={application.status} onChange={handleMove}>
          {ALL_STATUSES.map((status) => (
            <option key={status} value={status}>
              {t(`applicationStatus.${status}`)}
            </option>
          ))}
        </select>
      </label>

      <div className="application-next">
        {hasNextStep ? (
          <button
            type="button"
            className="application-next-set"
            aria-label={t("applications.editNextStepLabel", { title: job.title })}
            onClick={handleNextStep}
          >
            {application.nextStepOn ? (
              <time className={application.isOverdue ? "is-overdue" : undefined} dateTime={application.nextStepOn}>
                {formatDayMonth(application.nextStepOn)}
              </time>
            ) : null}
            <span>{application.nextStep || t("applications.noNextStep")}</span>
          </button>
        ) : (
          <button
            type="button"
            className="application-define"
            aria-label={t("applications.defineNextStepLabel", { title: job.title })}
            onClick={handleNextStep}
          >
            <PlusIcon />
            <span aria-hidden="true">{t("applications.defineNextStep")}</span>
          </button>
        )}
      </div>

      <div className="application-row-actions">
        {canReceiveAnswer(application.status) ? (
          <button type="button" className="button button-positive button-small" onClick={handleAnswer}>
            {t("applications.receivedAnswer")}
          </button>
        ) : null}
      </div>
    </article>
  );
});
