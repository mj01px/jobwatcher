import { useState, type ChangeEvent, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useCreateSource, useDeleteSource, useSources, useUpdateSource } from "../api/hooks";
import type { CollectedSourceKind, Source } from "../api/types";
import { KindMark } from "../components/JobFacts";
import { PageShell } from "../components/PageShell";
import { useI18n } from "../i18n/I18nProvider";
import { SOURCE_KINDS, sourceHref, validateSourceTarget } from "../lib/sources";

export function SourcesPage() {
  const { t } = useI18n();
  const { data: sources, isError } = useSources();

  return (
    <PageShell title="Sources | Job Watcher" heading={t("sources.heading")}>
      <div className="split-layout">
        <div>
          {isError && !sources ? <p className="load-error">{t("common.loadFailed")}</p> : null}
          {SOURCE_KINDS.map((kind, index) => {
            const ofKind = (sources ?? []).filter((source) => source.kind === kind);
            return (
              <section key={kind} className={`section-block${index === 0 ? " section-block-first" : ""}`}>
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">
                      <span>{ofKind.length}</span> <span>{t(`sources.kindEyebrow.${kind}`)}</span>
                    </p>
                    <h2>{t(`sources.kindTitle.${kind}`)}</h2>
                    <p className="section-intro">{t(`sources.kindIntro.${kind}`)}</p>
                  </div>
                </div>
                <div className="company-list">
                  {ofKind.map((source, position) => (
                    <SourceRow key={source.id} source={source} position={position + 1} />
                  ))}
                  {sources && ofKind.length === 0 ? <p className="panel-empty">{t("sources.emptyKind")}</p> : null}
                </div>
              </section>
            );
          })}
        </div>
        <AddSourcePanel />
      </div>
    </PageShell>
  );
}

function SourceRow({ source, position }: { source: Source; position: number }) {
  const { t } = useI18n();
  const updateSource = useUpdateSource();
  const deleteSource = useDeleteSource();
  const busy = updateSource.isPending || deleteSource.isPending;

  const handleToggle = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateSource.mutate({ id: source.id, input: { isActive: !source.isActive } });
  };

  const handleRemove = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    deleteSource.mutate(source.id);
  };

  // Checked at least once and still nothing worth a look: a candidate to pause.
  const noYield = source.lastCheckedAt !== null && source.highlightedJobs === 0;

  return (
    <article
      className={`company-row kind-row-${source.kind}${source.isActive ? "" : " is-paused"}${noYield ? " is-no-yield" : ""}`}
    >
      <div>
        <p className="company-index">
          {String(position).padStart(2, "0")} <KindMark kind={source.kind} />
        </p>
        <h2>{source.name}</h2>
        <a href={sourceHref(source.kind, source.target)} target="_blank" rel="noopener noreferrer">
          {source.target}
        </a>
        <p className="company-status">
          <span>{source.activeJobs}</span> <span>{t("sources.activeJobs")}</span>
          {source.lastError ? (
            <span className="status-error" title={source.lastError}>
              {t("sources.issue")}
            </span>
          ) : null}
        </p>
        <ul className="source-yield" aria-label={t("sources.yield")}>
          <li className={source.highlightedJobs > 0 ? "is-yield" : ""}>
            <strong>{source.highlightedJobs}</strong>
            <span>{t("sources.highlightedJobs")}</span>
          </li>
          <li className={source.applications > 0 ? "is-yield" : ""}>
            <strong>{source.applications}</strong>
            <span>{t("sources.applications")}</span>
          </li>
          <li>
            <strong>{source.lastRunJobs ?? "-"}</strong>
            <span>{source.lastRunJobs === null ? t("sources.neverChecked") : t("sources.lastRunJobs")}</span>
          </li>
        </ul>
        {noYield ? <p className="no-yield-note">{t("sources.noHighlights")}</p> : null}
      </div>
      <div className="row-actions">
        <form onSubmit={handleToggle}>
          <button className="button button-quiet" type="submit" disabled={busy}>
            <span>{t(source.isActive ? "sources.pause" : "sources.resume")}</span>
          </button>
        </form>
        <form onSubmit={handleRemove}>
          <button className="button button-danger" type="submit" disabled={busy}>
            {t("sources.remove")}
          </button>
        </form>
      </div>
    </article>
  );
}

type AddProblem = "name" | "target" | "server";

function AddSourcePanel() {
  const { t } = useI18n();
  const createSource = useCreateSource();
  const [kind, setKind] = useState<CollectedSourceKind>("inhire");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [problem, setProblem] = useState<AddProblem | null>(null);
  const [serverMessage, setServerMessage] = useState("");

  const handleKindChange = (event: ChangeEvent<HTMLInputElement>) => {
    setKind(event.target.value as CollectedSourceKind);
    setProblem(null);
  };
  const handleNameChange = (event: ChangeEvent<HTMLInputElement>) => setName(event.target.value);
  const handleTargetChange = (event: ChangeEvent<HTMLInputElement>) => setTarget(event.target.value);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) {
      setProblem("name");
      return;
    }
    if (!validateSourceTarget(kind, target)) {
      setProblem("target");
      return;
    }
    setProblem(null);
    createSource.mutate(
      { kind, name: name.trim(), target: target.trim() },
      {
        onSuccess: () => {
          setName("");
          setTarget("");
        },
        onError: (error) => {
          setServerMessage(error instanceof ApiError ? (error.details[0]?.issue ?? error.message) : "");
          setProblem("server");
        },
      },
    );
  };

  return (
    <aside className="form-panel">
      <p className="eyebrow">{t("sources.newSource")}</p>
      <h2>{t("sources.add")}</h2>
      <form className="stack-form" noValidate onSubmit={handleSubmit}>
        <fieldset className="kind-picker">
          <legend>{t("sources.kind")}</legend>
          <div className="reason-grid">
            {SOURCE_KINDS.map((option) => (
              <label key={option} className={`reason-chip${kind === option ? " is-selected" : ""}`}>
                <input type="radio" name="kind" value={option} checked={kind === option} onChange={handleKindChange} />
                <span>{t(`sources.kindTitle.${option}`)}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          <span>{t("sources.name")}</span>
          <input
            name="name"
            required
            maxLength={120}
            placeholder={t(`sources.namePlaceholder.${kind}`)}
            value={name}
            onChange={handleNameChange}
          />
        </label>
        <label>
          <span>{t(`sources.target.${kind}`)}</span>
          <input
            name="target"
            required
            placeholder={t(`sources.targetPlaceholder.${kind}`)}
            value={target}
            onChange={handleTargetChange}
          />
        </label>
        <p className="field-hint">{t(`sources.hint.${kind}`)}</p>
        {problem === "name" ? (
          <p className="form-error" role="alert">
            {t("sources.invalidName")}
          </p>
        ) : null}
        {problem === "target" ? (
          <p className="form-error" role="alert">
            {t(`sources.invalid.${kind}`)}
          </p>
        ) : null}
        {problem === "server" ? (
          <p className="form-error" role="alert">
            {serverMessage || t("toast.actionFailed")}
          </p>
        ) : null}
        <button className="button button-primary button-wide" type="submit" disabled={createSource.isPending}>
          {t("sources.addSource")}
        </button>
      </form>
    </aside>
  );
}
