import { PageShell } from "../components/PageShell";
import { useI18n } from "../i18n/I18nProvider";

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <PageShell title="Job Watcher" heading="Job Watcher">
      <div className="empty-state">
        <span className="empty-number">404</span>
        <h2>{t("notFound.title")}</h2>
        <p>{t("notFound.text")}</p>
      </div>
    </PageShell>
  );
}
