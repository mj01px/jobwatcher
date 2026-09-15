import { Link } from "react-router";

import { useOverview } from "../api/hooks";
import type { Application } from "../api/types";
import { companyLine } from "../components/JobFacts";
import { JobList } from "../components/JobList";
import { PageShell } from "../components/PageShell";
import { useI18n } from "../i18n/I18nProvider";

export function OverviewPage() {
  const { t } = useI18n();
  const { data, isError } = useOverview();
  const stats = data?.jobStats;
  const pipeline = data?.pipelineStats;

  return (
    <PageShell title="Overview | Job Watcher" heading={t("overview.heading")}>
      <section className="tile-grid" aria-label="Monitoring summary">
        <Link className="metric-tile tile-yellow" to="/jobs">
          <span className="metric-label">{t("overview.newThisCheck")}</span>
          <strong>{stats?.new ?? 0}</strong>
          <span className="metric-foot">{t("overview.openOpportunities")}</span>
        </Link>
        <Link className="metric-tile tile-blue" to="/jobs/highlighted">
          <span className="metric-label">{t("overview.forProfile")}</span>
          <strong>{stats?.highlighted ?? 0}</strong>
          <span className="metric-foot">{t("overview.highlightedRoles")}</span>
        </Link>
        <Link className="metric-tile tile-purple" to="/jobs">
          <span className="metric-label">{t("overview.activeJobs")}</span>
          <strong>{stats?.active ?? 0}</strong>
          <span className="metric-foot">
            {data?.sourceStats.active ?? 0} <span>{t("overview.sourcesMonitored")}</span>
          </span>
        </Link>
        <Link className="metric-tile tile-ink" to="/jobs/archived">
          <span className="metric-label">{t("overview.archive")}</span>
          <strong>{stats?.archived ?? 0}</strong>
          <span className="metric-foot">{t("overview.preserved")}</span>
        </Link>
      </section>

      <section className="tile-grid tile-grid-3" aria-label="Applications summary">
        <Link className="metric-tile tile-teal-dark" to="/applications">
          <span className="metric-label">{t("overview.pipelineActive")}</span>
          <strong>{pipeline?.active ?? 0}</strong>
          <span className="metric-foot">{t("overview.pipelineActiveFoot")}</span>
        </Link>
        <Link
          className={`metric-tile ${pipeline && pipeline.overdue > 0 ? "tile-coral" : "tile-soft"}`}
          to="/applications"
        >
          <span className="metric-label">{t("overview.pipelineOverdue")}</span>
          <strong>{pipeline?.overdue ?? 0}</strong>
          <span className="metric-foot">{t("overview.pipelineOverdueFoot")}</span>
        </Link>
        <Link className="metric-tile tile-cyan" to="/applications">
          <span className="metric-label">{t("overview.pipelineInterviews")}</span>
          <strong>{pipeline?.interviews ?? 0}</strong>
          <span className="metric-foot">{t("overview.pipelineInterviewsFoot")}</span>
        </Link>
      </section>

      <NeedsYou applications={data?.overdueApplications} />

      <section className="section-block">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("overview.latestSignals")}</p>
            <h2>{t("overview.recent")}</h2>
            <p className="section-intro">{t("overview.recentIntro")}</p>
          </div>
          <Link className="text-link" to="/jobs/highlighted">
            {t("overview.viewAll")}
          </Link>
        </div>
        <JobList jobs={data?.recentJobs} isError={isError} />
      </section>
    </PageShell>
  );
}

/**
 * Applications whose next step date already passed. With nothing overdue the
 * block stays, in a positive state, so a quiet day never looks like a failed load.
 */
function NeedsYou({ applications }: { applications: Application[] | undefined }) {
  const { t, formatDate } = useI18n();
  if (applications === undefined) return null;

  return (
    <section className="section-block needs-you">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{t("overview.needsYouEyebrow")}</p>
          <h2>{t("overview.needsYou")}</h2>
        </div>
        <Link className="text-link" to="/applications">
          {t("overview.openFunnel")}
        </Link>
      </div>
      {applications.length === 0 ? (
        <p className="needs-you-clear">{t("overview.needsYouClear")}</p>
      ) : (
        <ul className="needs-you-list">
          {applications.map((application) => (
            <li key={application.id} className="needs-you-item">
              <div>
                <strong>{application.job.title}</strong>
                <span>{companyLine(application.job)}</span>
              </div>
              <p>{application.nextStep || t("applications.noNextStep")}</p>
              {application.nextStepOn ? (
                <time dateTime={application.nextStepOn}>{formatDate(application.nextStepOn)}</time>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
