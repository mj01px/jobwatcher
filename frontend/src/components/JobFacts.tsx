import type { Job, SourceKind } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { SOURCE_KIND_LABELS } from "../lib/sources";

/** Score as a square block: cyan when highlighted, coral when negative. */
export function ScoreBadge({ score, highlighted }: { score: number; highlighted: boolean }) {
  const { t } = useI18n();
  const tone = highlighted ? "is-high" : score < 0 ? "is-negative" : "";
  return (
    <span className={`score-badge ${tone}`.trim()} title={t("job.scoreTitle")}>
      <span className="sr-only">{t("job.score")}</span>
      {score}
    </span>
  );
}

export function KindMark({ kind }: { kind: SourceKind }) {
  return <span className={`kind-mark kind-${kind}`}>{SOURCE_KIND_LABELS[kind]}</span>;
}

/** Location, work mode and seniority, only when the job states them. */
export function JobChips({ job }: { job: Job }) {
  const { t } = useI18n();
  const chips: { key: string; label: string }[] = [];
  if (job.location.trim()) chips.push({ key: "location", label: job.location });
  if (job.workMode !== "unknown") chips.push({ key: "workMode", label: t(`workMode.${job.workMode}`) });
  if (job.seniority !== "unknown") chips.push({ key: "seniority", label: t(`seniority.${job.seniority}`) });
  if (chips.length === 0) return null;
  return (
    <ul className="fact-chips" aria-label={t("job.facts")}>
      {chips.map((chip) => (
        <li key={chip.key} className="fact-chip">
          {chip.label}
        </li>
      ))}
    </ul>
  );
}

export function ScoreTags({ tags }: { tags: readonly string[] }) {
  const { t } = useI18n();
  if (tags.length === 0) return <p className="muted-line">{t("job.noTags")}</p>;
  return (
    <ul className="score-tags" aria-label={t("job.scoreTags")}>
      {tags.map((tag) => (
        <li key={tag}>{tag}</li>
      ))}
    </ul>
  );
}

/** The posting's company, falling back to the source name when unknown. */
export function companyLine(job: Job): string {
  return job.companyName.trim() || job.sourceName;
}
