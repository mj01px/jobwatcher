import { useId, useRef } from "react";

import { useJobDetail } from "../api/hooks";
import type { Job } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { companyLine, JobChips, KindMark, ScoreBadge, ScoreTags } from "./JobFacts";
import { Modal } from "./Modal";
import { OpenJobLink } from "./OpenJobLink";
import { PitchPanel } from "./PitchPanel";

interface JobDetailDrawerProps {
  job: Job | null;
  open: boolean;
  onClose: () => void;
}

/** Side panel with the job description, score tags and the cover letter. */
export function JobDetailDrawer({ job, open, onClose }: JobDetailDrawerProps) {
  const { t, formatDateTime } = useI18n();
  const titleId = `${useId()}-title`;
  const closeRef = useRef<HTMLButtonElement>(null);
  const { data: detail, isPending, isError } = useJobDetail(open && job ? job.id : null);
  // The row's copy shows instantly; the detail request fills in the description.
  const shown = detail ?? job;

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} initialFocusRef={closeRef} className="modal-drawer">
      {shown ? (
        <div className="drawer-box">
          <div className="drawer-head">
            <div className="drawer-head-copy">
              <div className="job-meta">
                <KindMark kind={shown.sourceKind} />
                <span>{companyLine(shown)}</span>
              </div>
              <h2 id={titleId}>{shown.title}</h2>
            </div>
            <ScoreBadge score={shown.score} highlighted={shown.isHighlighted} />
            <button
              ref={closeRef}
              type="button"
              className="modal-close"
              aria-label={t("common.close")}
              onClick={onClose}
            >
              <span aria-hidden="true">×</span>
            </button>
          </div>

          <JobChips job={shown} />

          <dl className="detail-facts">
            <div>
              <dt>{t("detail.source")}</dt>
              <dd>{shown.sourceName}</dd>
            </div>
            <div>
              <dt>{t("detail.published")}</dt>
              <dd>{shown.publishedAt ? formatDateTime(shown.publishedAt) : t("detail.unknown")}</dd>
            </div>
            <div>
              <dt>{t("job.firstSeen")}</dt>
              <dd>{formatDateTime(shown.firstSeenAt)}</dd>
            </div>
          </dl>

          <OpenJobLink job={shown} />

          <section className="drawer-section">
            <p className="modal-field-label">{t("detail.scoreTags")}</p>
            <ScoreTags tags={shown.scoreTags} />
          </section>

          <section className="drawer-section">
            <p className="modal-field-label">{t("detail.description")}</p>
            {isError ? <p className="load-error">{t("common.loadFailed")}</p> : null}
            {isPending && !detail ? <p className="panel-note">{t("common.loading")}</p> : null}
            {detail ? (
              detail.description.trim() ? (
                <div className="job-description">{detail.description}</div>
              ) : (
                <p className="panel-empty">{t("detail.noDescription")}</p>
              )
            ) : null}
          </section>

          {open && job ? <PitchPanel jobId={job.id} /> : null}
        </div>
      ) : null}
    </Modal>
  );
}
