import { Component, type ErrorInfo, type ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  override render(): ReactNode {
    return this.state.hasError ? <ErrorFallback /> : this.props.children;
  }
}

function ErrorFallback() {
  const { t } = useI18n();
  return (
    <div className="main-content">
      <div className="empty-state" role="alert">
        <span className="empty-number">!!</span>
        <h2>{t("error.title")}</h2>
        <p>{t("error.text")}</p>
      </div>
    </div>
  );
}
