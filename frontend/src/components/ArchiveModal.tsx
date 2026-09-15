import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import type { Job, ManualArchiveReason } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { ARCHIVE_REASONS } from "../lib/archiveReasons";
import { companyLine } from "./JobFacts";
import { Modal } from "./Modal";

interface ArchiveModalProps {
  job: Job | null;
  open: boolean;
  onClose: () => void;
  onConfirm: (reason: ManualArchiveReason, note: string) => Promise<void>;
}

const NOTE_MAX_LENGTH = 500;

export function ArchiveModal({ job, open, onClose, onConfirm }: ArchiveModalProps) {
  const { t } = useI18n();
  const idPrefix = useId();
  const titleId = `${idPrefix}-title`;
  const reasonsLabelId = `${idPrefix}-reasons`;
  const firstReasonRef = useRef<HTMLInputElement>(null);

  const [reason, setReason] = useState<ManualArchiveReason | null>(null);
  const [note, setNote] = useState("");
  const [showValidation, setShowValidation] = useState(false);
  const [showError, setShowError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Every opening starts from a clean form, like resetArchiveModal().
  useEffect(() => {
    if (!open) return;
    setReason(null);
    setNote("");
    setShowValidation(false);
    setShowError(false);
    setSubmitting(false);
  }, [open, job]);

  const handleReasonChange = (event: ChangeEvent<HTMLInputElement>) => {
    setReason(event.target.value as ManualArchiveReason);
  };

  const handleNoteChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setNote(event.target.value);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!reason) {
      setShowValidation(true);
      firstReasonRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setShowError(false);
    setShowValidation(false);
    try {
      await onConfirm(reason, note);
    } catch {
      setShowError(true);
      setSubmitting(false);
    }
  };

  const onFormSubmit = (event: FormEvent<HTMLFormElement>) => {
    void handleSubmit(event);
  };

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} initialFocusRef={firstReasonRef}>
      <form className="modal-box" noValidate onSubmit={onFormSubmit}>
        <div className="modal-head">
          <h2 id={titleId}>{t("archiveModal.title")}</h2>
          <button type="button" className="modal-close" aria-label={t("common.close")} onClick={onClose}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <p className="modal-subject">{job ? `${job.title} · ${companyLine(job)}` : ""}</p>
        <div>
          <p className="modal-field-label" id={reasonsLabelId}>
            {t("archiveModal.reason")}
          </p>
          <div className="reason-grid" role="radiogroup" aria-labelledby={reasonsLabelId}>
            {ARCHIVE_REASONS.map((slug, index) => (
              <label key={slug} className={`reason-chip${reason === slug ? " is-selected" : ""}`}>
                <input
                  ref={index === 0 ? firstReasonRef : undefined}
                  type="radio"
                  name="reason"
                  value={slug}
                  checked={reason === slug}
                  onChange={handleReasonChange}
                />
                <span>{t(`reason.${slug}`)}</span>
              </label>
            ))}
          </div>
        </div>
        <label>
          <span>{t("archiveModal.note")}</span>
          <textarea name="note" rows={3} maxLength={NOTE_MAX_LENGTH} value={note} onChange={handleNoteChange} />
        </label>
        {showValidation ? (
          <p className="modal-error" role="alert">
            {t("archiveModal.validation")}
          </p>
        ) : null}
        {showError ? (
          <p className="modal-error" role="alert">
            {t("archiveModal.error")}
          </p>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="button button-quiet" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className="button button-primary" disabled={submitting}>
            {t("archiveModal.confirm")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
