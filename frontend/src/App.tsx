import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { JobActionsProvider } from "./components/JobActionsProvider";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toasts";
import { I18nProvider } from "./i18n/I18nProvider";
import { ActivityPage } from "./pages/ActivityPage";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { JobsPage } from "./pages/JobsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SourcesPage } from "./pages/SourcesPage";

/** v3 bookmark: Overview briefly lived at /overview before returning to the home page. */
function OverviewRedirect() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/", search }} replace />;
}

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 5_000, refetchOnWindowFocus: true },
      mutations: { retry: 0 },
    },
  });
}

export function App() {
  const [queryClient] = useState(createQueryClient);

  return (
    <I18nProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          {/* The router wraps the providers: the job drawer and toasts render links too. */}
          <BrowserRouter>
            <ToastProvider>
              <JobActionsProvider>
                <Routes>
                  <Route element={<Layout />}>
                    {/* Overview is home and first in the sidebar. */}
                    <Route index element={<OverviewPage />} />
                    <Route path="overview" element={<OverviewRedirect />} />
                    <Route path="jobs" element={<JobsPage key="all" view="all" />} />
                    <Route path="jobs/highlighted" element={<JobsPage key="highlighted" view="highlighted" />} />
                    <Route path="jobs/archived" element={<JobsPage key="archived" view="archived" />} />
                    <Route path="applications" element={<ApplicationsPage view="active" />} />
                    <Route path="applications/stalled" element={<ApplicationsPage view="stalled" />} />
                    <Route path="applications/in-progress" element={<ApplicationsPage view="inProgress" />} />
                    <Route path="applications/closed" element={<ApplicationsPage view="closed" />} />
                    <Route path="sources" element={<SourcesPage />} />
                    {/* v1 bookmark */}
                    <Route path="companies" element={<Navigate to="/sources" replace />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route path="activity" element={<ActivityPage />} />
                    <Route path="*" element={<NotFoundPage />} />
                  </Route>
                </Routes>
              </JobActionsProvider>
            </ToastProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </ErrorBoundary>
    </I18nProvider>
  );
}
