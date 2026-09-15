import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { useGeneratePitch, usePitch } from "../api/hooks";
import { useI18n } from "../i18n/I18nProvider";

const INSTRUCTION_MAX_LENGTH = 300;
const COPIED_FEEDBACK_MS = 2000;

type PitchErrorKind = "dossier" | "gemini" | "unavailable" | "generic" | "copy";

function errorKind(error: unknown): PitchErrorKind {
  if (!(error instanceof ApiError)) return "generic";
  switch (error.code) {
    case "DOSSIER_EMPTY":
      return "dossier";
    case "GEMINI_NOT_CONFIGURED":
      return "gemini";
    case "AI_UNAVAILABLE":
      return "unavailable";
    default:
      return "generic";
  }
}

/** Cover letter for one job: generate, regenerate with an instruction, copy. One version per job. */
export function PitchPanel({ jobId }: { jobId: number }) {
  const { t, formatDateTime } = useI18n();
  const headingId = useId();
  const { data: pitch, isPending, isError } = usePitch(jobId);
  const generate = useGeneratePitch(jobId);
  const [instruction, setInstruction] = useState("");
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState<PitchErrorKind | null>(null);
  const copiedTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (copiedTimer.current !== null) window.clearTimeout(copiedTimer.current);
    },
    [],
  );

  const handleInstructionChange = (event: ChangeEvent<HTMLInputElement>) => setInstruction(event.target.value);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProblem(null);
    generate.mutate(instruction.trim(), {
      onSuccess: () => setInstruction(""),
      onError: (error) => setProblem(errorKind(error)),
    });
  };

  const handleCopy = async () => {
    if (!pitch) return;
    try {
      await navigator.clipboard.writeText(pitch.text);
      setCopied(true);
      if (copiedTimer.current !== null) window.clearTimeout(copiedTimer.current);
      copiedTimer.current = window.setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
    } catch {
      setProblem("copy");
    }
  };

  const onCopyClick = () => {
    void handleCopy();
  };

  return (
    <section className="pitch-panel" aria-labelledby={headingId}>
      <div className="panel-heading">
        <p className="eyebrow">{t("pitch.eyebrow")}</p>
        <h3 id={headingId}>{t("pitch.title")}</h3>
      </div>

      <form className="pitch-form" onSubmit={handleSubmit}>
        <label>
          <span>{t("pitch.instruction")}</span>
          <input
            name="instruction"
            maxLength={INSTRUCTION_MAX_LENGTH}
            placeholder={t("pitch.instructionPlaceholder")}
            value={instruction}
            onChange={handleInstructionChange}
          />
        </label>
        <button type="submit" className="button button-primary" disabled={generate.isPending}>
          {generate.isPending ? t("pitch.generating") : pitch ? t("pitch.regenerate") : t("pitch.generate")}
        </button>
      </form>

      {problem === "dossier" ? (
        <p className="form-error" role="alert">
          {t("pitch.error.dossier")} <Link to="/settings">{t("pitch.goToSettings")}</Link>
        </p>
      ) : null}
      {problem === "gemini" ? (
        <p className="form-error" role="alert">
          {t("pitch.error.gemini")} <Link to="/settings">{t("pitch.goToSettings")}</Link>
        </p>
      ) : null}
      {problem === "unavailable" ? (
        <p className="form-error" role="alert">
          {t("pitch.error.unavailable")}
        </p>
      ) : null}
      {problem === "generic" ? (
        <p className="form-error" role="alert">
          {t("pitch.error.generic")}
        </p>
      ) : null}
      {problem === "copy" ? (
        <p className="form-error" role="alert">
          {t("pitch.error.copy")}
        </p>
      ) : null}

      {generate.isPending ? <p className="panel-note">{t("pitch.writing")}</p> : null}
      {isError ? <p className="load-error">{t("common.loadFailed")}</p> : null}
      {!isPending && !isError && !pitch && !generate.isPending ? (
        <p className="panel-empty">{t("pitch.empty")}</p>
      ) : null}

      {pitch ? (
        <article className="pitch-version">
          <div className="pitch-version-meta">
            <span>
              {pitch.chars} / {pitch.maxChars} {t("pitch.chars")}
            </span>
            <span>{pitch.model}</span>
            <time dateTime={pitch.createdAt}>{formatDateTime(pitch.createdAt)}</time>
            <button type="button" className="button button-quiet button-small" onClick={onCopyClick}>
              {copied ? t("pitch.copied") : t("pitch.copy")}
            </button>
          </div>
          {pitch.instruction ? (
            <p className="pitch-instruction">
              {t("pitch.adjustment")}: {pitch.instruction}
            </p>
          ) : null}
          <p className="pitch-text">{pitch.text}</p>
        </article>
      ) : null}
    </section>
  );
}
