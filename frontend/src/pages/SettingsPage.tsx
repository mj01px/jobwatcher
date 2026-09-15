import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import { useProfileSettings, useSaveProfile, useSaveScoring, useSaveSecrets, useScoring } from "../api/hooks";
import type { ProfileSettings, SecretsInput } from "../api/types";
import { PageShell } from "../components/PageShell";
import type { TranslationKey } from "../i18n/dictionary";
import { useI18n } from "../i18n/I18nProvider";
import {
  DEFAULT_STACK_GROUPS,
  draftMinScore,
  draftStackGroups,
  draftToGroups,
  MAX_TERMS,
  nextGroupUid,
  splitTerms,
  TERM_MAX_LENGTH,
  toDraft,
  validateScoringDraft,
  WEIGHT_MAX,
  WEIGHT_MIN,
  type GroupDraft,
  type ScoringDraft,
  type ScoringIssue,
} from "../lib/scoringForm";

const PITCH_MIN = 300;
const PITCH_MAX = 5000;

export function SettingsPage() {
  const { t } = useI18n();

  return (
    <PageShell title="Settings | Job Watcher" heading={t("settings.heading")}>
      <div className="settings-grid">
        <ScoringEditor />
        <div className="settings-side">
          <section className="info-panel">
            <p className="eyebrow">{t("settings.automation")}</p>
            <h2>{t("settings.daily")}</h2>
            <div className="time-grid">
              <strong>09</strong>
              <strong>12</strong>
              <strong>15</strong>
              <strong>18</strong>
            </div>
            <p>{t("settings.dailyText")}</p>
            <p>{t("settings.catchUp")}</p>
          </section>
          <SecretsPanel />
        </div>
        <ProfilePanel />
      </div>
    </PageShell>
  );
}

const ISSUE_KEYS: Record<ScoringIssue["kind"], TranslationKey> = {
  keyInvalid: "scoring.issue.keyInvalid",
  keyDuplicate: "scoring.issue.keyDuplicate",
  weightInvalid: "scoring.issue.weightInvalid",
  termsEmpty: "scoring.issue.termsEmpty",
  termsTooMany: "scoring.issue.termsTooMany",
  termTooLong: "scoring.issue.termTooLong",
  minScoreInvalid: "scoring.issue.minScoreInvalid",
  noGroups: "scoring.issue.noGroups",
  stackUnknown: "scoring.issue.stackUnknown",
};

function ScoringEditor() {
  const { t } = useI18n();
  const { data, isError } = useScoring();
  const saveScoring = useSaveScoring();
  const [draft, setDraft] = useState<ScoringDraft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [issues, setIssues] = useState<ScoringIssue[]>([]);
  const [status, setStatus] = useState<"saved" | "reset" | "failed" | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  // Server data fills the form until the person starts editing.
  useEffect(() => {
    if (data && !dirty) setDraft(toDraft(data.groups, data.minScore, data.stackGroups));
  }, [data, dirty]);

  const edit = (next: (current: ScoringDraft) => ScoringDraft) => {
    setDraft((current) => (current ? next(current) : current));
    setDirty(true);
    setStatus(null);
  };

  const updateGroup = (uid: string, patch: Partial<GroupDraft>) =>
    edit((current) => ({
      ...current,
      groups: current.groups.map((group) => (group.uid === uid ? { ...group, ...patch } : group)),
    }));

  const removeGroup = (uid: string) =>
    edit((current) => ({ ...current, groups: current.groups.filter((group) => group.uid !== uid) }));

  const addGroup = () =>
    edit((current) => ({
      ...current,
      groups: [...current.groups, { uid: nextGroupUid(), key: "", weight: "5", terms: "", stack: false }],
    }));

  const handleMinScore = (event: ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    edit((current) => ({ ...current, minScore: value }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft) return;
    const found = validateScoringDraft(draft);
    setIssues(found);
    if (found.length > 0) return;
    saveScoring.mutate(
      { groups: draftToGroups(draft), minScore: draftMinScore(draft), stackGroups: draftStackGroups(draft) },
      {
        onSuccess: () => {
          setDirty(false);
          setStatus("saved");
        },
        onError: () => setStatus("failed"),
      },
    );
  };

  const handleReset = () => {
    if (!confirmReset) {
      setConfirmReset(true);
      return;
    }
    setConfirmReset(false);
    saveScoring.mutate(
      {
        groups: null,
        minScore: draft ? draftMinScore(draft) : (data?.minScore ?? 0),
        stackGroups: [...DEFAULT_STACK_GROUPS],
      },
      {
        onSuccess: () => {
          setIssues([]);
          setDirty(false);
          setStatus("reset");
        },
        onError: () => setStatus("failed"),
      },
    );
  };

  const issuesFor = (uid: string) => issues.filter((issue) => "uid" in issue && issue.uid === uid);
  const generalIssues = issues.filter((issue) => !("uid" in issue));

  return (
    <section className="form-panel form-panel-wide scoring-panel">
      <p className="eyebrow">{t("settings.profileSignals")}</p>
      <div className="panel-title-row">
        <h2>{t("scoring.title")}</h2>
        {data?.isDefault ? <span className="tag tag-muted">{t("scoring.default")}</span> : null}
      </div>
      <p>{t("scoring.help")}</p>
      {isError && !data ? <p className="load-error">{t("common.loadFailed")}</p> : null}

      {draft ? (
        <form className="stack-form" noValidate onSubmit={handleSubmit}>
          <label className="min-score-field">
            <span>{t("scoring.minScore")}</span>
            <input type="number" inputMode="numeric" step={1} value={draft.minScore} onChange={handleMinScore} />
          </label>
          <p className="field-hint">{t("scoring.minScoreHelp")}</p>
          <p className="field-hint">{t("scoring.stackHelp")}</p>

          <div className="scoring-groups">
            {draft.groups.map((group) => {
              const groupIssues = issuesFor(group.uid);
              const termCount = splitTerms(group.terms).length;
              const weight = Number.parseInt(group.weight, 10);
              return (
                <fieldset
                  key={group.uid}
                  className={`scoring-group${weight < 0 ? " is-penalty" : ""}${group.stack ? " is-stack" : ""}${groupIssues.length ? " has-issue" : ""}`}
                >
                  <legend className="sr-only">{group.key || t("scoring.newGroup")}</legend>
                  <div className="scoring-group-head">
                    <label>
                      <span>{t("scoring.groupKey")}</span>
                      <input
                        value={group.key}
                        maxLength={40}
                        placeholder="core"
                        onChange={(event) => updateGroup(group.uid, { key: event.target.value })}
                      />
                    </label>
                    <label className="weight-field">
                      <span>{t("scoring.weight")}</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={WEIGHT_MIN}
                        max={WEIGHT_MAX}
                        step={1}
                        value={group.weight}
                        onChange={(event) => updateGroup(group.uid, { weight: event.target.value })}
                      />
                    </label>
                    <button type="button" className="button button-danger" onClick={() => removeGroup(group.uid)}>
                      {t("scoring.removeGroup")}
                    </button>
                  </div>
                  <label className="stack-toggle">
                    <input
                      type="checkbox"
                      checked={group.stack}
                      onChange={(event) => updateGroup(group.uid, { stack: event.target.checked })}
                    />
                    <span>{t("scoring.countsAsStack")}</span>
                  </label>
                  <label>
                    <span>
                      {t("scoring.terms")} ({termCount}/{MAX_TERMS})
                    </span>
                    <textarea
                      rows={Math.min(10, Math.max(3, termCount + 1))}
                      value={group.terms}
                      onChange={(event) => updateGroup(group.uid, { terms: event.target.value })}
                    />
                  </label>
                  {groupIssues.map((issue) => (
                    <p key={issue.kind} className="form-error" role="alert">
                      {t(ISSUE_KEYS[issue.kind], {
                        term: issue.kind === "termTooLong" ? issue.term : "",
                        max: issue.kind === "termTooLong" ? TERM_MAX_LENGTH : MAX_TERMS,
                        min: WEIGHT_MIN,
                        weightMax: WEIGHT_MAX,
                      })}
                    </p>
                  ))}
                </fieldset>
              );
            })}
          </div>

          <button type="button" className="button button-quiet" onClick={addGroup}>
            {t("scoring.addGroup")}
          </button>

          {generalIssues.map((issue) => (
            <p key={issue.kind} className="form-error" role="alert">
              {t(ISSUE_KEYS[issue.kind], {
                term: "",
                max: MAX_TERMS,
                min: WEIGHT_MIN,
                weightMax: WEIGHT_MAX,
                keys: issue.kind === "stackUnknown" ? issue.keys.join(", ") : "",
              })}
            </p>
          ))}
          {status === "failed" ? (
            <p className="form-error" role="alert">
              {t("toast.actionFailed")}
            </p>
          ) : null}

          <div className="form-actions-row">
            <button type="button" className="button button-danger" disabled={saveScoring.isPending} onClick={handleReset}>
              {confirmReset ? t("scoring.confirmReset") : t("scoring.reset")}
            </button>
            <span className="form-saved" aria-live="polite">
              {status === "saved" ? t("scoring.saved") : status === "reset" ? t("scoring.resetDone") : ""}
            </span>
            <button className="button button-primary" type="submit" disabled={saveScoring.isPending}>
              {saveScoring.isPending ? t("scoring.saving") : t("scoring.save")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function ProfilePanel() {
  const { t } = useI18n();
  const { data, isError } = useProfileSettings();

  return (
    <section className="form-panel form-panel-wide profile-panel">
      <p className="eyebrow">{t("profile.eyebrow")}</p>
      <h2>{t("profile.title")}</h2>
      <p>{t("profile.help")}</p>
      {isError && !data ? <p className="load-error">{t("common.loadFailed")}</p> : null}
      {/* The form keeps its own copy after the first load, so a refetch never wipes typing. */}
      {data ? <ProfileForm profile={data} /> : null}
    </section>
  );
}

function ProfileForm({ profile }: { profile: ProfileSettings }) {
  const { t } = useI18n();
  const saveProfile = useSaveProfile();
  const [dossier, setDossier] = useState(profile.dossier);
  const [pitchMaxChars, setPitchMaxChars] = useState(String(profile.pitchMaxChars));
  const [geminiModel, setGeminiModel] = useState(profile.geminiModel);
  const [status, setStatus] = useState<"saved" | "failed" | "invalid" | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const size = Number.parseInt(pitchMaxChars, 10);
    if (!Number.isInteger(size) || size < PITCH_MIN || size > PITCH_MAX) {
      setStatus("invalid");
      return;
    }
    saveProfile.mutate(
      { dossier, pitchMaxChars: size, geminiModel: geminiModel.trim() },
      { onSuccess: () => setStatus("saved"), onError: () => setStatus("failed") },
    );
  };

  return (
    <form className="stack-form" noValidate onSubmit={handleSubmit}>
      <label>
        <span>
          {t("profile.dossier")} ({dossier.length.toLocaleString()} {t("pitch.chars")})
        </span>
        <textarea
          rows={16}
          value={dossier}
          placeholder={t("profile.dossierPlaceholder")}
          onChange={(event) => {
            setDossier(event.target.value);
            setStatus(null);
          }}
        />
      </label>
      <div className="form-grid">
        <label>
          <span>{t("profile.pitchMaxChars")}</span>
          <input
            type="number"
            inputMode="numeric"
            min={PITCH_MIN}
            max={PITCH_MAX}
            step={50}
            value={pitchMaxChars}
            onChange={(event) => {
              setPitchMaxChars(event.target.value);
              setStatus(null);
            }}
          />
        </label>
        <label>
          <span>{t("profile.geminiModel")}</span>
          <input
            value={geminiModel}
            maxLength={80}
            onChange={(event) => {
              setGeminiModel(event.target.value);
              setStatus(null);
            }}
          />
        </label>
      </div>
      {status === "invalid" ? (
        <p className="form-error" role="alert">
          {t("profile.invalidSize", { min: PITCH_MIN, max: PITCH_MAX })}
        </p>
      ) : null}
      {status === "failed" ? (
        <p className="form-error" role="alert">
          {t("toast.actionFailed")}
        </p>
      ) : null}
      <div className="form-actions-row">
        <span className="form-saved" aria-live="polite">
          {status === "saved" ? t("common.saved") : ""}
        </span>
        <button className="button button-primary" type="submit" disabled={saveProfile.isPending}>
          {t("profile.save")}
        </button>
      </div>
    </form>
  );
}

type SecretField = keyof SecretsInput;

function SecretsPanel() {
  const { t } = useI18n();
  const { data } = useProfileSettings();
  const saveSecrets = useSaveSecrets();
  const [values, setValues] = useState<Record<SecretField, string>>({ geminiApiKey: "", githubToken: "" });
  const [status, setStatus] = useState<"saved" | "failed" | null>(null);

  const configured: Record<SecretField, boolean> = {
    geminiApiKey: data?.geminiConfigured ?? false,
    githubToken: data?.githubConfigured ?? false,
  };

  const send = (input: SecretsInput) => {
    saveSecrets.mutate(input, {
      onSuccess: () => {
        setValues({ geminiApiKey: "", githubToken: "" });
        setStatus("saved");
      },
      onError: () => setStatus("failed"),
    });
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input: SecretsInput = {};
    if (values.geminiApiKey.trim()) input.geminiApiKey = values.geminiApiKey.trim();
    if (values.githubToken.trim()) input.githubToken = values.githubToken.trim();
    if (Object.keys(input).length === 0) return;
    send(input);
  };

  const fields: { key: SecretField; label: TranslationKey; help: TranslationKey }[] = [
    { key: "geminiApiKey", label: "secrets.gemini", help: "secrets.geminiHelp" },
    { key: "githubToken", label: "secrets.github", help: "secrets.githubHelp" },
  ];

  return (
    <section className="info-panel secrets-panel">
      <p className="eyebrow">{t("secrets.eyebrow")}</p>
      <h2>{t("secrets.title")}</h2>
      <p>{t("secrets.help")}</p>
      <form className="stack-form" noValidate onSubmit={handleSubmit}>
        {fields.map((field) => (
          <div key={field.key} className="secret-field">
            <label>
              <span>
                {t(field.label)}{" "}
                <em className={configured[field.key] ? "secret-on" : "secret-off"}>
                  {configured[field.key] ? t("secrets.configured") : t("secrets.notConfigured")}
                </em>
              </span>
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={configured[field.key] ? t("secrets.replacePlaceholder") : ""}
                value={values[field.key]}
                onChange={(event) => {
                  const value = event.target.value;
                  setValues((current) => ({ ...current, [field.key]: value }));
                  setStatus(null);
                }}
              />
            </label>
            <p className="field-hint">{t(field.help)}</p>
            {configured[field.key] ? (
              <button
                type="button"
                className="button button-danger button-small"
                disabled={saveSecrets.isPending}
                onClick={() => send({ [field.key]: "" })}
              >
                {t("secrets.remove")}
              </button>
            ) : null}
          </div>
        ))}
        {status === "failed" ? (
          <p className="form-error" role="alert">
            {t("toast.actionFailed")}
          </p>
        ) : null}
        <div className="form-actions-row">
          <span className="form-saved" aria-live="polite">
            {status === "saved" ? t("common.saved") : ""}
          </span>
          <button className="button button-primary" type="submit" disabled={saveSecrets.isPending}>
            {t("secrets.save")}
          </button>
        </div>
      </form>
    </section>
  );
}
