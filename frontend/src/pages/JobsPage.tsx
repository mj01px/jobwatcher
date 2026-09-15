import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";

import { useJobs, useScoring } from "../api/hooks";
import type { JobView } from "../api/types";
import { AddJobModal } from "../components/AddJobModal";
import { JobList } from "../components/JobList";
import { PageShell } from "../components/PageShell";
import { Pagination } from "../components/Pagination";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";

const VIEW_COPY: Record<JobView, { heading: TranslationKey; intro: TranslationKey }> = {
  all: { heading: "jobs.heading.all", intro: "jobs.intro.all" },
  highlighted: { heading: "jobs.heading.highlighted", intro: "jobs.intro.highlighted" },
  archived: { heading: "jobs.heading.archived", intro: "jobs.intro.archived" },
};

function requestedPage(raw: string | null): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

export function JobsPage({ view }: { view: JobView }) {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = requestedPage(searchParams.get("page"));
  const { data, isError } = useJobs(view, page);
  const { data: scoring } = useScoring();
  const [addOpen, setAddOpen] = useState(false);
  const copy = VIEW_COPY[view];
  const meta = data?.meta;

  // Archiving the last row of a later page steps back one page.
  const handleEmptied = useCallback(() => {
    const current = meta?.page ?? page;
    if (current <= 1) return;
    setSearchParams((params) => {
      const next = new URLSearchParams(params);
      next.set("page", String(current - 1));
      return next;
    });
  }, [meta?.page, page, setSearchParams]);

  const openAdd = useCallback(() => setAddOpen(true), []);
  const closeAdd = useCallback(() => setAddOpen(false), []);

  const intro =
    view === "highlighted" && scoring ? t("jobs.intro.highlightedScore", { minScore: scoring.minScore }) : t(copy.intro);

  return (
    <PageShell title={view === "highlighted" ? "Highlights | Job Watcher" : "Jobs | Job Watcher"} heading={t(copy.heading)}>
      <section className="section-block section-block-first">
        <div className="section-heading">
          <div>
            <p className="eyebrow">
              <span>{meta?.total ?? 0}</span> <span>{t("jobs.records")}</span>
            </p>
            <p className="section-intro">
              <span>{intro}</span>
            </p>
          </div>
          {view === "all" ? (
            <button type="button" className="button button-primary" onClick={openAdd}>
              {t("addJob.open")}
            </button>
          ) : null}
        </div>
        <JobList key={`${view}-${meta?.page ?? page}`} jobs={data?.data} isError={isError} onEmptied={handleEmptied} />
        {meta ? <Pagination current={meta.page} totalPages={meta.totalPages} /> : null}
      </section>
      {view === "all" ? <AddJobModal open={addOpen} onClose={closeAdd} /> : null}
    </PageShell>
  );
}
