import { useId, useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { useAts, useGenerateAts } from "../api/hooks";
import type { AtsVerdict } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";

type AtsErrorKind = "resumeRequired" | "resumeInvalid" | "notConfigured" | "unavailable" | "generic";

const ACCEPT = ".pdf,.docx,.txt";

const VERDICT_KEY: Record<AtsVerdict, TranslationKey> = {
  forte: "ats.verdict.forte",
  moderado: "ats.verdict.moderado",
  fraco: "ats.verdict.fraco",
};

function errorKind(error: unknown): AtsErrorKind {
  if (!(error instanceof ApiError)) return "generic";
  switch (error.code) {
    case "RESUME_REQUIRED":
      return "resumeRequired";
    case "RESUME_INVALID":
      return "resumeInvalid";
    case "AI_NOT_CONFIGURED":
    case "GEMINI_NOT_CONFIGURED":
      return "notConfigured";
    case "AI_UNAVAILABLE":
      return "unavailable";
    default:
      return "generic";
  }
}

/** A list of keywords as chips, or a muted "none" when empty. */
function KeywordChips({ items, tone }: { items: string[]; tone: "matched" | "missing" }) {
  const { t } = useI18n();
  if (items.length === 0) return <p className="ats-none">{t("ats.none")}</p>;
  return (
    <ul className={`ats-chips ats-chips-${tone}`}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/** A bulleted list rendered only when it has items. */
function BulletList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="ats-block">
      <p className="ats-block-label">{label}</p>
      <ul className="ats-bullets">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/** ATS analysis for one job: upload a resume and score it against this posting. One report per job. */
export function AtsPanel({ jobId }: { jobId: number }) {
  const { t, formatDateTime } = useI18n();
  const headingId = useId();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: report, isPending, isError } = useAts(jobId);
  const analyze = useGenerateAts(jobId);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<AtsErrorKind | null>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
    setProblem(null);
  };

  const handleAnalyze = () => {
    setProblem(null);
    if (!file) {
      setProblem("resumeRequired");
      return;
    }
    analyze.mutate(file, { onError: (error) => setProblem(errorKind(error)) });
  };

  return (
    <section className="ats-panel" aria-labelledby={headingId}>
      <div className="panel-heading">
        <p className="eyebrow">{t("ats.eyebrow")}</p>
        <h3 id={headingId}>{t("ats.title")}</h3>
      </div>
      <p className="panel-note">{t("ats.help")}</p>

      <div className="ats-upload">
        <label htmlFor={inputId} className="button button-quiet">
          {file ? t("ats.changeFile") : t("ats.pickFile")}
        </label>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          className="sr-only"
          accept={ACCEPT}
          onChange={handleFileChange}
        />
        {file ? <span className="ats-filename">{file.name}</span> : null}
        <button
          type="button"
          className="button button-primary"
          disabled={analyze.isPending}
          onClick={handleAnalyze}
        >
          {analyze.isPending ? t("ats.analyzing") : report ? t("ats.reanalyze") : t("ats.analyze")}
        </button>
      </div>
      <p className="field-hint">{t("ats.fileHint")}</p>

      {problem === "resumeRequired" ? (
        <p className="form-error" role="alert">
          {t("ats.error.resumeRequired")}
        </p>
      ) : null}
      {problem === "resumeInvalid" ? (
        <p className="form-error" role="alert">
          {t("ats.error.resumeInvalid")}
        </p>
      ) : null}
      {problem === "notConfigured" ? (
        <p className="form-error" role="alert">
          {t("ats.error.notConfigured")} <Link to="/settings">{t("ats.goToSettings")}</Link>
        </p>
      ) : null}
      {problem === "unavailable" ? (
        <p className="form-error" role="alert">
          {t("ats.error.unavailable")}
        </p>
      ) : null}
      {problem === "generic" ? (
        <p className="form-error" role="alert">
          {t("ats.error.generic")}
        </p>
      ) : null}

      {analyze.isPending ? <p className="panel-note">{t("ats.working")}</p> : null}
      {isError ? <p className="load-error">{t("common.loadFailed")}</p> : null}
      {!isPending && !isError && !report && !analyze.isPending ? (
        <p className="panel-empty">{t("ats.empty")}</p>
      ) : null}

      {report ? (
        <article className={`ats-report ats-${report.verdict}`}>
          <div className="ats-score-row">
            <div className="ats-score" aria-hidden="true">
              <strong>{report.score}</strong>
              <span>/100</span>
            </div>
            <div className="ats-verdict">
              <p className="ats-verdict-label">{t(VERDICT_KEY[report.verdict])}</p>
              <p className="ats-verdict-score">
                {report.score} / 100 {t("ats.scoreLabel")}
              </p>
            </div>
          </div>

          {report.summary ? <p className="ats-summary">{report.summary}</p> : null}

          <div className="ats-keywords">
            <div className="ats-block">
              <p className="ats-block-label">{t("ats.matched")}</p>
              <KeywordChips items={report.matchedKeywords} tone="matched" />
            </div>
            <div className="ats-block">
              <p className="ats-block-label">{t("ats.missing")}</p>
              <KeywordChips items={report.missingKeywords} tone="missing" />
            </div>
          </div>

          <BulletList label={t("ats.strengths")} items={report.strengths} />
          <BulletList label={t("ats.gaps")} items={report.gaps} />
          <BulletList label={t("ats.suggestions")} items={report.suggestions} />

          <div className="ats-meta">
            {report.resumeFilename ? (
              <span>
                {t("ats.resumeLabel")}: {report.resumeFilename}
              </span>
            ) : null}
            <span>{report.model}</span>
            <time dateTime={report.createdAt}>{formatDateTime(report.createdAt)}</time>
          </div>
        </article>
      ) : null}
    </section>
  );
}
