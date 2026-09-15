import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useCreateJob } from "../api/hooks";
import type { Seniority, WorkMode } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { Modal } from "./Modal";
import { useToasts } from "./Toasts";

const WORK_MODES = ["unknown", "remote", "hybrid", "onsite"] as const satisfies readonly WorkMode[];
const SENIORITIES = ["unknown", "internship", "junior", "mid", "senior"] as const satisfies readonly Seniority[];

interface FormState {
  title: string;
  url: string;
  companyName: string;
  location: string;
  workMode: WorkMode;
  seniority: Seniority;
  description: string;
}

const EMPTY_FORM: FormState = {
  title: "",
  url: "",
  companyName: "",
  location: "",
  workMode: "unknown",
  seniority: "unknown",
  description: "",
};

type FormProblem = "required" | "url" | "conflict" | "generic";

function isHttpUrl(raw: string): boolean {
  try {
    const url = new URL(raw.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/** Manual entry for what the collectors miss. The job lands in All jobs, scored. */
export function AddJobModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const { showToast } = useToasts();
  const idPrefix = useId();
  const titleId = `${idPrefix}-title`;
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const createJob = useCreateJob();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [problem, setProblem] = useState<FormProblem | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setProblem(null);
  }, [open]);

  const update =
    <K extends keyof FormState>(key: K) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const value = event.target.value as FormState[K];
      setForm((current) => ({ ...current, [key]: value }));
    };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.title.trim() || !form.url.trim()) {
      setProblem("required");
      return;
    }
    if (!isHttpUrl(form.url)) {
      setProblem("url");
      return;
    }
    setProblem(null);
    createJob.mutate(
      {
        title: form.title.trim(),
        url: form.url.trim(),
        companyName: form.companyName.trim(),
        location: form.location.trim(),
        workMode: form.workMode,
        seniority: form.seniority,
        description: form.description.trim(),
      },
      {
        onSuccess: (result) => {
          showToast(t("addJob.added", { title: result.data.title }));
          onClose();
        },
        onError: (error) => setProblem(error instanceof ApiError && error.code === "CONFLICT" ? "conflict" : "generic"),
      },
    );
  };

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} initialFocusRef={firstFieldRef} className="modal-wide">
      <form className="modal-box" noValidate onSubmit={handleSubmit}>
        <div className="modal-head">
          <h2 id={titleId}>{t("addJob.title")}</h2>
          <button type="button" className="modal-close" aria-label={t("common.close")} onClick={onClose}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <p className="modal-hint">{t("addJob.intro")}</p>
        <div className="form-grid">
          <label className="form-grid-wide">
            <span>{t("addJob.jobTitle")}</span>
            <input ref={firstFieldRef} name="title" required maxLength={300} value={form.title} onChange={update("title")} />
          </label>
          <label className="form-grid-wide">
            <span>{t("addJob.url")}</span>
            <input
              type="url"
              name="url"
              required
              maxLength={1000}
              placeholder="https://"
              value={form.url}
              onChange={update("url")}
            />
          </label>
          <label>
            <span>{t("addJob.company")}</span>
            <input name="companyName" maxLength={200} value={form.companyName} onChange={update("companyName")} />
          </label>
          <label>
            <span>{t("addJob.location")}</span>
            <input name="location" maxLength={200} value={form.location} onChange={update("location")} />
          </label>
          <label>
            <span>{t("addJob.workMode")}</span>
            <select name="workMode" value={form.workMode} onChange={update("workMode")}>
              {WORK_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {t(`workMode.${mode}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("addJob.seniority")}</span>
            <select name="seniority" value={form.seniority} onChange={update("seniority")}>
              {SENIORITIES.map((level) => (
                <option key={level} value={level}>
                  {t(`seniority.${level}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="form-grid-wide">
            <span>{t("addJob.description")}</span>
            <textarea name="description" rows={6} value={form.description} onChange={update("description")} />
          </label>
        </div>
        {problem ? (
          <p className="modal-error" role="alert">
            {t(`addJob.error.${problem}`)}
          </p>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="button button-quiet" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className="button button-primary" disabled={createJob.isPending}>
            {t("addJob.submit")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
