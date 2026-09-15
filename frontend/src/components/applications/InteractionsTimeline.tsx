import { useId, useState, type ChangeEvent, type FormEvent } from "react";

import { useCreateInteraction, useDeleteInteraction, useUpdateInteraction } from "../../api/hooks";
import type { Interaction } from "../../api/types";
import { useI18n } from "../../i18n/I18nProvider";
import { todayIso } from "../../lib/board";

interface DraftInteraction {
  date: string;
  title: string;
  detail: string;
}

function InteractionForm({
  initial,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: DraftInteraction;
  submitLabel: string;
  busy: boolean;
  onSubmit: (draft: DraftInteraction) => void;
  onCancel?: () => void;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(initial);
  const [missingTitle, setMissingTitle] = useState(false);

  const update = (key: keyof DraftInteraction) => (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const value = event.target.value;
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.title.trim()) {
      setMissingTitle(true);
      return;
    }
    setMissingTitle(false);
    onSubmit({ date: draft.date || todayIso(), title: draft.title.trim(), detail: draft.detail.trim() });
  };

  return (
    <form className="interaction-form" noValidate onSubmit={handleSubmit}>
      <label>
        <span>{t("interactions.date")}</span>
        <input type="date" value={draft.date} onChange={update("date")} />
      </label>
      <label>
        <span>{t("interactions.titleField")}</span>
        <input maxLength={200} placeholder={t("interactions.titlePlaceholder")} value={draft.title} onChange={update("title")} />
      </label>
      <label className="interaction-form-wide">
        <span>{t("interactions.detail")}</span>
        <textarea rows={2} value={draft.detail} onChange={update("detail")} />
      </label>
      {missingTitle ? (
        <p className="form-error interaction-form-wide" role="alert">
          {t("interactions.titleRequired")}
        </p>
      ) : null}
      <div className="interaction-form-actions interaction-form-wide">
        {onCancel ? (
          <button type="button" className="button button-quiet button-small" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        ) : null}
        <button type="submit" className="button button-primary button-small" disabled={busy}>
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function InteractionItem({ interaction }: { interaction: Interaction }) {
  const { t, formatDate } = useI18n();
  const updateInteraction = useUpdateInteraction();
  const deleteInteraction = useDeleteInteraction();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (editing) {
    return (
      <li className="timeline-item is-editing">
        <InteractionForm
          initial={{ date: interaction.date, title: interaction.title, detail: interaction.detail }}
          submitLabel={t("common.save")}
          busy={updateInteraction.isPending}
          onCancel={() => setEditing(false)}
          onSubmit={(draft) =>
            updateInteraction.mutate({ id: interaction.id, input: draft }, { onSuccess: () => setEditing(false) })
          }
        />
      </li>
    );
  }

  return (
    <li className="timeline-item">
      <time dateTime={interaction.date}>{formatDate(interaction.date)}</time>
      <div className="timeline-copy">
        <strong>{interaction.title}</strong>
        {interaction.detail ? <p>{interaction.detail}</p> : null}
      </div>
      <div className="timeline-actions">
        <button type="button" className="button button-quiet button-small" onClick={() => setEditing(true)}>
          {t("common.edit")}
        </button>
        {confirming ? (
          <button
            type="button"
            className="button button-danger button-small"
            disabled={deleteInteraction.isPending}
            onClick={() => deleteInteraction.mutate(interaction.id)}
          >
            {t("common.confirmDelete")}
          </button>
        ) : (
          <button type="button" className="button button-quiet button-small" onClick={() => setConfirming(true)}>
            {t("common.delete")}
          </button>
        )}
      </div>
    </li>
  );
}

/** Timeline of every e-mail, test, interview and answer for one application. */
export function InteractionsTimeline({
  applicationId,
  interactions,
}: {
  applicationId: number;
  interactions: Interaction[];
}) {
  const { t } = useI18n();
  const headingId = useId();
  const createInteraction = useCreateInteraction(applicationId);
  // Remounting the form clears it after each successful add.
  const [formKey, setFormKey] = useState(0);

  return (
    <section className="drawer-section" aria-labelledby={headingId}>
      <div className="panel-heading">
        <p className="eyebrow">{t("interactions.eyebrow")}</p>
        <h3 id={headingId}>{t("interactions.title")}</h3>
      </div>
      <InteractionForm
        key={formKey}
        initial={{ date: todayIso(), title: "", detail: "" }}
        submitLabel={t("interactions.add")}
        busy={createInteraction.isPending}
        onSubmit={(draft) => createInteraction.mutate(draft, { onSuccess: () => setFormKey((key) => key + 1) })}
      />
      {interactions.length === 0 ? (
        <p className="panel-empty">{t("interactions.empty")}</p>
      ) : (
        <ol className="timeline">
          {interactions.map((interaction) => (
            <InteractionItem key={interaction.id} interaction={interaction} />
          ))}
        </ol>
      )}
    </section>
  );
}
