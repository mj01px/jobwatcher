from __future__ import annotations

from django.urls import path, re_path

from watcher import views

urlpatterns = [
    path("status", views.StatusView.as_view(), name="status"),
    path("overview", views.OverviewView.as_view(), name="overview"),
    path("jobs", views.JobListView.as_view(), name="jobs"),
    path("jobs/<int:job_id>", views.JobDetailView.as_view(), name="job-detail"),
    path("jobs/<int:job_id>/archive", views.JobArchiveView.as_view(), name="job-archive"),
    path("jobs/<int:job_id>/restore", views.JobRestoreView.as_view(), name="job-restore"),
    path("jobs/<int:job_id>/visit", views.JobVisitView.as_view(), name="job-visit"),
    path("sources", views.SourceListView.as_view(), name="sources"),
    path("sources/<int:source_id>", views.SourceDetailView.as_view(), name="source-detail"),
    path("settings/scoring", views.ScoringSettingsView.as_view(), name="settings-scoring"),
    path("settings/profile", views.ProfileSettingsView.as_view(), name="settings-profile"),
    path("settings/secrets", views.SecretsSettingsView.as_view(), name="settings-secrets"),
    path("check-runs", views.CheckRunListView.as_view(), name="check-runs"),
    path("visits", views.VisitView.as_view(), name="visits"),
    re_path(r"^.*$", views.ApiNotFoundView.as_view(), name="api-not-found"),
]
