import { Fragment } from "react";

import { ACTIVITY_HISTORY_LIMIT, useCheckRuns, useSources, useStatus } from "../api/hooks";
import type { CheckRun, MonitorStatus, RunProgress, Source, SourceRunState } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";
import { KindMark } from "../components/JobFacts";
import { CheckNowForm, PageShell } from "../components/PageShell";

const STATE_LABELS: Record<SourceRunState, TranslationKey> = {
  pending: "activity.waiting",
  collecting: "activity.collecting",
  done: "activity.done",
  error: "activity.failed",
};

export function ActivityPage() {
  const { t } = useI18n();
  const { data: status } = useStatus();
  const running = status?.isRunning ?? false;
  // Poll every 3s while a check runs so progress stays live.
  const { data: history } = useCheckRuns(ACTIVITY_HISTORY_LIMIT, running);
  const { data: sources } = useSources(running);

  return (
    <PageShell title="Activity | Job Watcher" heading={t("activity.heading")}>
      <section className="section-block section-block-first">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("activity.liveStatus")}</p>
            <h2>{t("activity.currentCheck")}</h2>
          </div>
          {status && !running ? <CheckNowForm /> : null}
        </div>
        {status ? running ? <LiveRun status={status} /> : <IdleState status={status} /> : null}
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("activity.history")}</p>
            <h2>{t("activity.recentChecks")}</h2>
          </div>
        </div>
        {history && history.length > 0 ? <HistoryTable runs={history} /> : null}
        {history && history.length === 0 ? <p className="section-intro">{t("activity.noChecks")}</p> : null}
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("activity.perSource")}</p>
            <h2>{t("activity.lastResult")}</h2>
          </div>
        </div>
        <SourceResults sources={sources ?? []} />
      </section>
    </PageShell>
  );
}

function LiveRun({ status }: { status: MonitorStatus }) {
  const { t } = useI18n();
  return (
    <>
      {status.isStalled ? (
        <p className="activity-banner is-warning">
          <span>{t("activity.stuck")}</span>
        </p>
      ) : (
        <p className="activity-banner is-calm">
          <span>{t("activity.running")}</span>
        </p>
      )}
      {status.progress ? (
        <Progress progress={status.progress} />
      ) : (
        <p className="activity-banner is-calm">{t("activity.startingUp")}</p>
      )}
    </>
  );
}

function Progress({ progress }: { progress: RunProgress }) {
  const { t, formatDateTime } = useI18n();
  const percent = progress.total ? (100 * progress.settled) / progress.total : 0;

  return (
    <>
      <div className="progress-block">
        <div className="progress-line">
          <strong>
            {progress.settled} / {progress.total}
          </strong>
          <span>{t("activity.sourcesChecked")}</span>
          {progress.startedAt ? (
            <time dateTime={progress.startedAt}>{formatDateTime(progress.startedAt)}</time>
          ) : null}
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-valuenow={progress.settled}
          aria-valuemin={0}
          aria-valuemax={progress.total}
        >
          <span className="progress-fill" style={{ width: `${percent}%` }} />
        </div>
        <div className="progress-legend">
          <span>
            <span className="dot dot-done" />
            {progress.counts.done} <span>{t("activity.done")}</span>
          </span>
          <span>
            <span className="dot dot-collecting" />
            {progress.counts.collecting} <span>{t("activity.collecting")}</span>
          </span>
          <span>
            <span className="dot dot-pending" />
            {progress.counts.pending} <span>{t("activity.waiting")}</span>
          </span>
          <span>
            <span className="dot dot-error" />
            {progress.counts.error} <span>{t("activity.failed")}</span>
          </span>
        </div>
      </div>

      <ul className="activity-companies">
        {progress.sources.map((source) => (
          <li key={source.sourceId} className={`activity-company state-${source.state}`}>
            <span className={`dot dot-${source.state}`} />
            <KindMark kind={source.kind} />
            <span className="activity-company-name">{source.name}</span>
            {source.state === "done" ? (
              <span className="activity-company-meta">
                {source.jobs ?? 0} <span>{t("activity.jobs")}</span>
              </span>
            ) : (
              <span className="activity-company-meta">{t(STATE_LABELS[source.state])}</span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function IdleState({ status }: { status: MonitorStatus }) {
  const { t, formatDateTime } = useI18n();
  const lastRun = status.lastRun;
  const lastRunTime = lastRun ? (lastRun.finishedAt ?? lastRun.startedAt ?? lastRun.requestedAt) : null;

  return (
    <div className="idle-grid">
      <div className="idle-card">
        <p className="eyebrow">{t("activity.state")}</p>
        <p className="idle-headline">{t("activity.noCheck")}</p>
        <p>{t("activity.noCheckText")}</p>
      </div>
      <div className="idle-card">
        <p className="eyebrow">{t("activity.nextCheck")}</p>
        {status.nextRunAt ? (
          <p className="idle-headline">
            <time dateTime={status.nextRunAt}>{formatDateTime(status.nextRunAt)}</time>
          </p>
        ) : (
          <p className="idle-headline">{t("activity.notScheduled")}</p>
        )}
        <p>{t("activity.nextCheckText")}</p>
      </div>
      {lastRun && lastRunTime ? (
        <div className="idle-card">
          <p className="eyebrow">{t("activity.lastCheck")}</p>
          <p className="idle-headline">
            <time dateTime={lastRunTime}>{formatDateTime(lastRunTime)}</time>
          </p>
          <p>
            <span>{t("activity.found")}</span> {lastRun.jobsFound} · <span>{t("activity.new")}</span>{" "}
            {lastRun.jobsNew} · <span>{t("activity.archived")}</span> {lastRun.jobsArchived}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function RunBadge({ run }: { run: CheckRun }) {
  const { t } = useI18n();
  switch (run.status) {
    case "success":
      return <span className="run-badge run-ok">{t("activity.status.success")}</span>;
    case "partial":
      return <span className="run-badge run-warn">{t("activity.status.partial")}</span>;
    case "failed":
      return <span className="run-badge run-bad">{t("activity.status.failed")}</span>;
    default:
      return <span className="run-badge run-live">{t("activity.status.running")}</span>;
  }
}

function HistoryTable({ runs }: { runs: CheckRun[] }) {
  const { t, formatDateTime } = useI18n();
  return (
    <div className="activity-table-wrap">
      <table className="activity-table">
        <thead>
          <tr>
            <th>{t("activity.col.started")}</th>
            <th>{t("activity.col.duration")}</th>
            <th>{t("activity.col.status")}</th>
            <th>{t("activity.col.checked")}</th>
            <th>{t("activity.col.found")}</th>
            <th>{t("activity.col.new")}</th>
            <th>{t("activity.col.archived")}</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const started = run.startedAt ?? run.requestedAt;
            return (
              <Fragment key={run.id}>
                <tr>
                  <td>
                    <time dateTime={started}>{formatDateTime(started)}</time>
                  </td>
                  <td>
                    {run.durationSeconds !== null ? `${run.durationSeconds}s` : <span>{t("activity.runningShort")}</span>}
                  </td>
                  <td>
                    <RunBadge run={run} />
                  </td>
                  <td>
                    {run.sourcesChecked} / {run.sourcesTotal}
                  </td>
                  <td>{run.jobsFound}</td>
                  <td>{run.jobsNew}</td>
                  <td>{run.jobsArchived}</td>
                </tr>
                {run.error ? (
                  <tr className="activity-error-row">
                    <td colSpan={7}>{run.error}</td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SourceResults({ sources }: { sources: Source[] }) {
  const { t, formatDateTime } = useI18n();
  return (
    <div className="activity-table-wrap">
      <table className="activity-table">
        <thead>
          <tr>
            <th>{t("activity.col.source")}</th>
            <th>{t("activity.col.kind")}</th>
            <th>{t("activity.col.activeJobs")}</th>
            <th>{t("activity.col.lastChecked")}</th>
            <th>{t("activity.col.state")}</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <Fragment key={source.id}>
              <tr>
                <td>{source.name}</td>
                <td>
                  <KindMark kind={source.kind} />
                </td>
                <td>{source.activeJobs}</td>
                <td>
                  {source.lastCheckedAt ? (
                    <time dateTime={source.lastCheckedAt}>{formatDateTime(source.lastCheckedAt)}</time>
                  ) : (
                    <span>{t("activity.never")}</span>
                  )}
                </td>
                <td>
                  {!source.isActive ? (
                    <span className="run-badge run-muted">{t("activity.paused")}</span>
                  ) : source.lastError ? (
                    <span className="run-badge run-bad">{t("activity.error")}</span>
                  ) : (
                    <span className="run-badge run-ok">{t("activity.ok")}</span>
                  )}
                </td>
              </tr>
              {source.lastError ? (
                <tr className="activity-error-row">
                  <td colSpan={5}>{source.lastError}</td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
