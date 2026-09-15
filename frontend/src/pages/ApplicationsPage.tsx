import { useCallback, useMemo, useState, type ChangeEvent } from "react";
import { NavLink } from "react-router";

import { useBoard, useClosedApplications, useMoveApplication, useReceiveAnswer, useUpdateApplication } from "../api/hooks";
import type { Application, ApplicationStatus } from "../api/types";
import { ApplicationDrawer } from "../components/applications/ApplicationDrawer";
import { ApplicationRow, type DrawerFocus } from "../components/applications/ApplicationRow";
import { companyLine, KindMark } from "../components/JobFacts";
import { PageShell } from "../components/PageShell";
import { useToasts } from "../components/Toasts";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";
import {
  countViews,
  filterForView,
  flattenBoard,
  groupByWait,
  type ApplicationsView,
  type WaitGroupId,
} from "../lib/applications";
import { ACTIVE_STATUSES } from "../lib/board";

export type { ApplicationsView } from "../lib/applications";

type BoardView = Exclude<ApplicationsView, "closed">;

const tabClass = ({ isActive }: { isActive: boolean }) => (isActive ? "view-tab is-active" : "view-tab");

const TABS: readonly { view: ApplicationsView; to: string; label: TranslationKey }[] = [
  { view: "active", to: "/applications", label: "applications.tab.active" },
  { view: "stalled", to: "/applications/stalled", label: "applications.tab.stalled" },
  { view: "inProgress", to: "/applications/in-progress", label: "applications.tab.inProgress" },
  { view: "closed", to: "/applications/closed", label: "applications.tab.closed" },
];

const GROUP_COPY: Record<WaitGroupId, { label: TranslationKey; hint: TranslationKey }> = {
  late: { label: "applications.group.late", hint: "applications.group.lateHint" },
  recent: { label: "applications.group.recent", hint: "applications.group.recentHint" },
  fresh: { label: "applications.group.fresh", hint: "applications.group.freshHint" },
};

const VIEW_COPY: Record<BoardView, { eyebrow: TranslationKey; intro: TranslationKey; emptyTitle: TranslationKey; emptyText: TranslationKey }> = {
  active: {
    eyebrow: "applications.eyebrow.active",
    intro: "applications.intro.active",
    emptyTitle: "applications.emptyActiveTitle",
    emptyText: "applications.emptyActiveText",
  },
  stalled: {
    eyebrow: "applications.eyebrow.stalled",
    intro: "applications.intro.stalled",
    emptyTitle: "applications.emptyStalledTitle",
    emptyText: "applications.emptyStalledText",
  },
  inProgress: {
    eyebrow: "applications.eyebrow.inProgress",
    intro: "applications.intro.inProgress",
    emptyTitle: "applications.emptyInProgressTitle",
    emptyText: "applications.emptyInProgressText",
  },
};

interface Selection {
  id: number;
  snapshot: Application;
  focus: DrawerFocus;
}

export function ApplicationsPage({ view }: { view: ApplicationsView }) {
  const { t } = useI18n();
  const { data: board, isError: boardFailed } = useBoard();
  const { data: closed, isError: closedFailed } = useClosedApplications();
  const [selection, setSelection] = useState<Selection | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const active = useMemo(() => (board ? flattenBoard(board) : []), [board]);
  const counts = useMemo(() => countViews(active), [active]);

  const openApplication = useCallback((application: Application, focus: DrawerFocus) => {
    setSelection({ id: application.id, snapshot: application, focus });
    setDrawerOpen(true);
  }, []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  // The drawer follows the latest copy (optimistic moves land on the board first).
  const shown = selection
    ? (active.find((item) => item.id === selection.id) ??
      closed?.find((item) => item.id === selection.id) ??
      selection.snapshot)
    : null;

  return (
    <PageShell title="Applications | Job Watcher" heading={t("applications.heading")}>
      <nav className="view-tabs" aria-label={t("applications.views")}>
        {TABS.map((tab) => {
          const count = tab.view === "closed" ? (closed?.length ?? null) : board ? counts[tab.view] : null;
          return (
            <NavLink key={tab.view} className={tabClass} to={tab.to} end>
              <span>{t(tab.label)}</span>
              {count !== null ? <span className={`view-tab-count count-${tab.view}`}>{count}</span> : null}
            </NavLink>
          );
        })}
      </nav>

      {view === "closed" ? (
        <ClosedView closed={closed} failed={closedFailed} onOpen={openApplication} />
      ) : (
        <ListView
          view={view}
          applications={board ? filterForView(active, view) : null}
          stalledCount={counts.stalled}
          failed={boardFailed}
          onOpen={openApplication}
        />
      )}

      <ApplicationDrawer
        application={shown}
        open={drawerOpen}
        focus={selection?.focus ?? null}
        onClose={closeDrawer}
      />
    </PageShell>
  );
}

function ListView({
  view,
  applications,
  stalledCount,
  failed,
  onOpen,
}: {
  view: BoardView;
  applications: Application[] | null;
  stalledCount: number;
  failed: boolean;
  onOpen: (application: Application, focus: DrawerFocus) => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToasts();
  // mutate is stable across renders, so the memoized rows do not rerender on every poll.
  const { mutate: moveApplication } = useMoveApplication();
  const { mutate: receiveAnswer } = useReceiveAnswer();
  const copy = VIEW_COPY[view];

  const handleMove = useCallback(
    (application: Application, status: ApplicationStatus) => {
      moveApplication({ id: application.id, status }, { onError: () => showToast(t("toast.actionFailed")) });
    },
    [moveApplication, showToast, t],
  );

  const handleAnswer = useCallback(
    (application: Application) => {
      receiveAnswer(
        { id: application.id, title: t("applications.answerTitle") },
        {
          onSuccess: () => showToast(t("applications.movedToScreening", { title: application.job.title })),
          onError: () => showToast(t("toast.actionFailed")),
        },
      );
    },
    [receiveAnswer, showToast, t],
  );

  const groups = applications ? groupByWait(applications) : [];

  return (
    <section className="section-block section-block-first">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{t(copy.eyebrow, { count: applications?.length ?? 0 })}</p>
          <p className="section-intro">{t(copy.intro)}</p>
        </div>
        {stalledCount > 0 ? (
          <span className="heading-alert heading-alert-pink">{t("applications.followUpAlert", { count: stalledCount })}</span>
        ) : null}
      </div>

      {failed && !applications ? <p className="load-error">{t("common.loadFailed")}</p> : null}

      {applications && applications.length === 0 ? (
        <div className="empty-state">
          <span className="empty-number">00</span>
          <h2>{t(copy.emptyTitle)}</h2>
          <p>{t(copy.emptyText)}</p>
        </div>
      ) : null}

      {groups.length > 0 ? (
        <div className="application-list">
          <div className="application-list-head" aria-hidden="true">
            <span />
            <span>{t("applications.column.wait")}</span>
            <span>{t("applications.column.job")}</span>
            <span>{t("applications.column.stage")}</span>
            <span>{t("applications.column.nextStep")}</span>
            <span />
          </div>
          {groups.map((group) => (
            <section key={group.id} className={`application-group wait-${group.id}`} aria-label={t(GROUP_COPY[group.id].label)}>
              <header className="application-group-head">
                <h2>{t(GROUP_COPY[group.id].label)}</h2>
                <span>{t(GROUP_COPY[group.id].hint)}</span>
              </header>
              {group.applications.map((application) => (
                <ApplicationRow
                  key={application.id}
                  application={application}
                  onOpen={onOpen}
                  onMove={handleMove}
                  onAnswer={handleAnswer}
                />
              ))}
            </section>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ClosedView({
  closed,
  failed,
  onOpen,
}: {
  closed: Application[] | undefined;
  failed: boolean;
  onOpen: (application: Application, focus: DrawerFocus) => void;
}) {
  const { t } = useI18n();

  return (
    <section className="section-block section-block-first">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span>{closed?.length ?? 0}</span> <span>{t("applications.closedRecords")}</span>
          </p>
          <p className="section-intro">{t("applications.closedIntro")}</p>
        </div>
      </div>
      {failed && !closed ? <p className="load-error">{t("common.loadFailed")}</p> : null}
      <div className="job-list">
        {(closed ?? []).map((application) => (
          <ClosedRow key={application.id} application={application} onOpen={onOpen} />
        ))}
        {closed && closed.length === 0 ? (
          <div className="empty-state">
            <span className="empty-number">00</span>
            <h2>{t("applications.closedEmptyTitle")}</h2>
            <p>{t("applications.closedEmptyText")}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ClosedRow({
  application,
  onOpen,
}: {
  application: Application;
  onOpen: (application: Application, focus: DrawerFocus) => void;
}) {
  const { t, formatDateTime } = useI18n();
  const { showToast } = useToasts();
  const updateApplication = useUpdateApplication();
  const [target, setTarget] = useState<ApplicationStatus>("applied");
  const { job } = application;

  const handleTarget = (event: ChangeEvent<HTMLSelectElement>) => setTarget(event.target.value as ApplicationStatus);
  const handleOpen = () => onOpen(application, null);
  const handleRestore = () => {
    updateApplication.mutate(
      { id: application.id, input: { status: target } },
      {
        onSuccess: () =>
          showToast(t("applications.restored", { title: job.title, status: t(`applicationStatus.${target}`) })),
        onError: () => showToast(t("toast.actionFailed")),
      },
    );
  };

  return (
    <article className={`job-row closed-row status-${application.status}`}>
      <div className="job-state" aria-hidden="true" />
      <div className="job-copy">
        <div className="job-meta">
          <KindMark kind={job.sourceKind} />
          <span>{companyLine(job)}</span>
          <span className={`tag ${application.status === "rejected" ? "tag-overdue" : "tag-muted"}`}>
            {t(`applicationStatus.${application.status}`)}
          </span>
        </div>
        <h2>
          <button type="button" className="job-title-button" onClick={handleOpen}>
            {job.title}
          </button>
        </h2>
        <p>
          {t("applications.closedOn")} <time dateTime={application.updatedAt}>{formatDateTime(application.updatedAt)}</time>
        </p>
      </div>
      <div className="job-actions">
        <label className="inline-select">
          <span className="sr-only">{t("applications.restoreTo")}</span>
          <select value={target} onChange={handleTarget}>
            {ACTIVE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {t(`applicationStatus.${status}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="button button-quiet" disabled={updateApplication.isPending} onClick={handleRestore}>
          {t("applications.restore")}
        </button>
      </div>
    </article>
  );
}
