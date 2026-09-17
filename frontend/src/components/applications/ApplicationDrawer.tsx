import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent, type RefObject } from "react";

import {
  useApplicationDetail,
  useCreateInteraction,
  useDeleteApplication,
  useMoveApplication,
  useReceiveAnswer,
  useUpdateApplication,
} from "../../api/hooks";
import type { Application, ApplicationDetail, ApplicationStatus } from "../../api/types";
import { useI18n } from "../../i18n/I18nProvider";
import { canReceiveAnswer, WAITING_TILE_DAYS } from "../../lib/applications";
import { ACTIVE_STATUSES, CLOSED_STATUSES, isActiveStatus, todayIso } from "../../lib/board";
import { companyLine, KindMark, ScoreBadge } from "../JobFacts";
import { Modal } from "../Modal";
import { OpenJobLink } from "../OpenJobLink";
import { PitchPanel } from "../PitchPanel";
import { useToasts } from "../Toasts";
import type { DrawerFocus } from "./ApplicationRow";

const PRIORITIES = [1, 2, 3, 4, 5] as const;

interface FormState {
  priority: number;
  appliedOn: string;
  nextStep: string;
  nextStepOn: string;
  contact: string;
  hasReferral: boolean;
  notes: string;
}

function toForm(application: Application): FormState {
  return {
    priority: application.priority,
    appliedOn: application.appliedOn ?? "",
    nextStep: application.nextStep,
    nextStepOn: application.nextStepOn ?? "",
    contact: application.contact,
    hasReferral: application.hasReferral,
    notes: application.notes,
  };
}

interface ApplicationDrawerProps {
  /** The row that was clicked, kept current by the page; shown while the detail request runs. */
  application: Application | null;
  open: boolean;
  /** Field to focus when the drawer opens, e.g. from the row's "Definir" button. */
  focus?: DrawerFocus;
  onClose: () => void;
}

export function ApplicationDrawer({ application, open, focus = null, onClose }: ApplicationDrawerProps) {
  const { t } = useI18n();
  const titleId = `${useId()}-title`;
  const closeRef = useRef<HTMLButtonElement>(null);
  const nextStepRef = useRef<HTMLInputElement>(null);
  const nextStepOnRef = useRef<HTMLInputElement>(null);
  const { data: detail, isError } = useApplicationDetail(open && application ? application.id : null);
  // Status and idle days change from the list too, so the page copy wins over a stale detail.
  const shown: Application | ApplicationDetail | null =
    detail && application ? { ...detail, status: application.status, daysIdle: application.daysIdle } : (detail ?? application);
  // Each opening starts a fresh form, so unsaved edits never survive a close.
  const [session, setSession] = useState(0);
  const applicationId = application?.id;
  useEffect(() => {
    if (open) setSession((current) => current + 1);
  }, [open, applicationId]);

  useEffect(() => {
    if (!open || focus !== "nextStep") return undefined;
    // After the modal focused its close button.
    const timer = window.setTimeout(() => nextStepRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open, focus, applicationId, session]);

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} initialFocusRef={closeRef} className="modal-drawer">
      {shown ? (
        <div className="drawer-box">
          <div className="drawer-head">
            <div className="drawer-head-copy">
              <div className="job-meta">
                <KindMark kind={shown.job.sourceKind} />
                <span>{companyLine(shown.job)}</span>
                <span className="tag tag-funnel">{t(`applicationStatus.${shown.status}`)}</span>
              </div>
              <h2 id={titleId}>{shown.job.title}</h2>
            </div>
            <ScoreBadge score={shown.job.score} highlighted={shown.job.isHighlighted} />
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

          <OpenJobLink job={shown.job} />

          {isError ? <p className="load-error">{t("common.loadFailed")}</p> : null}

          <StagePicker application={shown} />

          <WaitingTile application={shown} nextStepOnRef={nextStepOnRef} />

          {/* Row and detail carry the same form fields, so the form never remounts when the detail lands. */}
          <ApplicationForm
            key={`${shown.id}-${session}`}
            application={shown}
            nextStepRef={nextStepRef}
            nextStepOnRef={nextStepOnRef}
            onRemoved={onClose}
          />

          {open ? <PitchPanel jobId={shown.job.id} /> : null}
        </div>
      ) : null}
    </Modal>
  );
}

/** The six active stages as numbered blocks, plus the two ways to close. Changes apply at once. */
function StagePicker({ application }: { application: Application }) {
  const { t } = useI18n();
  const { showToast } = useToasts();
  const { mutate: moveApplication, isPending } = useMoveApplication();

  const move = (status: ApplicationStatus) => {
    if (status === application.status) return;
    moveApplication({ id: application.id, status }, { onError: () => showToast(t("toast.actionFailed")) });
  };

  return (
    <section className="drawer-section" aria-label={t("applications.status")}>
      <span className="field-label">{t("applications.status")}</span>
      <div className="stage-blocks">
        {ACTIVE_STATUSES.map((status, index) => {
          const current = status === application.status;
          return (
            <button
              key={status}
              type="button"
              className={`stage-block status-${status}${current ? " is-current" : ""}`}
              aria-pressed={current}
              disabled={isPending}
              onClick={() => move(status)}
            >
              <span className="stage-block-number">{String(index + 1).padStart(2, "0")}</span>
              <span className="stage-block-label">{t(`applicationStatus.${status}`)}</span>
            </button>
          );
        })}
      </div>
      <div className="stage-close">
        <span>{t("applications.closeAs")}</span>
        {CLOSED_STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            className={`stage-close-button${status === application.status ? " is-current" : ""}`}
            aria-pressed={status === application.status}
            disabled={isPending}
            onClick={() => move(status)}
          >
            {t(`applicationStatus.${status}`)}
          </button>
        ))}
      </div>
    </section>
  );
}

/** Days without an answer, with the follow-up actions. Hidden while the wait is still short. */
function WaitingTile({
  application,
  nextStepOnRef,
}: {
  application: Application;
  nextStepOnRef: RefObject<HTMLInputElement | null>;
}) {
  const { t, formatDayMonth } = useI18n();
  const { showToast } = useToasts();
  const createInteraction = useCreateInteraction(application.id);
  const { mutate: receiveAnswer, isPending: answering } = useReceiveAnswer();

  if (!isActiveStatus(application.status) || application.daysIdle < WAITING_TILE_DAYS) return null;

  const handleFollowUp = () => {
    createInteraction.mutate(
      { date: todayIso(), title: t("applications.followUpTitle") },
      {
        onSuccess: () => {
          showToast(t("applications.followUpLogged"));
          nextStepOnRef.current?.focus();
        },
        onError: () => showToast(t("toast.actionFailed")),
      },
    );
  };

  const handleAnswer = () => {
    receiveAnswer(
      { id: application.id, title: t("applications.answerTitle") },
      {
        onSuccess: () => showToast(t("applications.movedToScreening", { title: application.job.title })),
        onError: () => showToast(t("toast.actionFailed")),
      },
    );
  };

  return (
    <section className="waiting-tile" aria-label={t("applications.waitingLabel")}>
      <div className="waiting-tile-count">
        <span>{t("applications.waitingLabel")}</span>
        <strong>{application.daysIdle}</strong>
        <span>{t("applications.waitingSince", { date: formatDayMonth(application.updatedAt) })}</span>
      </div>
      <div className="waiting-tile-body">
        <p>{t("applications.waitingText")}</p>
        <div className="waiting-tile-actions">
          <button type="button" className="button button-primary" disabled={createInteraction.isPending} onClick={handleFollowUp}>
            {t("applications.logFollowUp")}
          </button>
          {canReceiveAnswer(application.status) ? (
            <button type="button" className="button button-positive" disabled={answering} onClick={handleAnswer}>
              {t("applications.receivedAnswer")}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ApplicationForm({
  application,
  nextStepRef,
  nextStepOnRef,
  onRemoved,
}: {
  application: Application;
  nextStepRef: RefObject<HTMLInputElement | null>;
  nextStepOnRef: RefObject<HTMLInputElement | null>;
  onRemoved: () => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToasts();
  const updateApplication = useUpdateApplication();
  const deleteApplication = useDeleteApplication();
  const [form, setForm] = useState<FormState>(() => toForm(application));
  const [saved, setSaved] = useState(false);
  const [failed, setFailed] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  useEffect(() => {
    if (!saved) return undefined;
    const timer = window.setTimeout(() => setSaved(false), 2000);
    return () => window.clearTimeout(timer);
  }, [saved]);

  const update =
    <K extends keyof FormState>(key: K, parse: (raw: string) => FormState[K]) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const value = parse(event.target.value);
      setForm((current) => ({ ...current, [key]: value }));
    };
  const text = (raw: string) => raw;

  const handleReferral = (event: ChangeEvent<HTMLInputElement>) => {
    const checked = event.target.checked;
    setForm((current) => ({ ...current, hasReferral: checked }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFailed(false);
    // Status is not part of the form: the stage blocks change it right away.
    updateApplication.mutate(
      {
        id: application.id,
        input: {
          priority: form.priority,
          appliedOn: form.appliedOn || null,
          nextStep: form.nextStep.trim(),
          nextStepOn: form.nextStepOn || null,
          contact: form.contact.trim(),
          hasReferral: form.hasReferral,
          notes: form.notes,
        },
      },
      { onSuccess: () => setSaved(true), onError: () => setFailed(true) },
    );
  };

  const handleRemove = () => {
    deleteApplication.mutate(application.id, {
      onSuccess: () => {
        showToast(t("applications.removed", { title: application.job.title }));
        onRemoved();
      },
      onError: () => setFailed(true),
    });
  };

  return (
    <form className="application-form" onSubmit={handleSubmit}>
      <label className="application-form-wide">
        <span>{t("applications.nextStep")}</span>
        <input
          ref={nextStepRef}
          maxLength={300}
          placeholder={t("applications.nextStepPlaceholder")}
          value={form.nextStep}
          onChange={update("nextStep", text)}
        />
      </label>
      <label>
        <span>{t("applications.nextStepOn")}</span>
        <input ref={nextStepOnRef} type="date" value={form.nextStepOn} onChange={update("nextStepOn", text)} />
      </label>
      <fieldset className="priority-field">
        <legend>{t("applications.priority")}</legend>
        <div className="priority-buttons">
          {PRIORITIES.map((priority) => (
            <button
              key={priority}
              type="button"
              className={`priority-button${form.priority === priority ? " is-current" : ""}`}
              aria-pressed={form.priority === priority}
              aria-label={t("applications.priorityValue", { value: priority })}
              onClick={() => setForm((current) => ({ ...current, priority }))}
            >
              {priority}
            </button>
          ))}
        </div>
      </fieldset>
      <label>
        <span>{t("applications.appliedOn")}</span>
        <input type="date" value={form.appliedOn} onChange={update("appliedOn", text)} />
      </label>
      <label>
        <span>{t("applications.contact")}</span>
        <input
          maxLength={200}
          placeholder={t("applications.contactPlaceholder")}
          value={form.contact}
          onChange={update("contact", text)}
        />
      </label>
      <label className="checkbox-field application-form-wide">
        <input type="checkbox" checked={form.hasReferral} onChange={handleReferral} />
        <span>{t("applications.hasReferral")}</span>
      </label>
      <label className="application-form-wide">
        <span>{t("applications.notes")}</span>
        <textarea
          rows={4}
          placeholder={t("applications.notesPlaceholder")}
          value={form.notes}
          onChange={update("notes", text)}
        />
      </label>

      {failed ? (
        <p className="form-error application-form-wide" role="alert">
          {t("toast.actionFailed")}
        </p>
      ) : null}

      <div className="application-form-actions application-form-wide">
        {confirmingRemove ? (
          <button
            type="button"
            className="button button-danger"
            disabled={deleteApplication.isPending}
            onClick={handleRemove}
          >
            {t("applications.confirmRemove")}
          </button>
        ) : (
          <button type="button" className="button button-quiet" onClick={() => setConfirmingRemove(true)}>
            {t("applications.remove")}
          </button>
        )}
        <span className="form-saved" aria-live="polite">
          {saved ? t("common.saved") : ""}
        </span>
        <button type="submit" className="button button-primary" disabled={updateApplication.isPending}>
          {t("common.save")}
        </button>
      </div>
    </form>
  );
}
