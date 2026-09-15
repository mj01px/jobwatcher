from __future__ import annotations

from django.urls import path

from pipeline import views

urlpatterns = [
    path(
        "jobs/<int:job_id>/application",
        views.JobApplicationCreateView.as_view(),
        name="job-application",
    ),
    path("jobs/<int:job_id>/pitch", views.JobPitchView.as_view(), name="job-pitch"),
    path("applications/board", views.ApplicationBoardView.as_view(), name="applications-board"),
    path("applications/closed", views.ApplicationClosedView.as_view(), name="applications-closed"),
    path(
        "applications/<int:application_id>",
        views.ApplicationDetailView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<int:application_id>/interactions",
        views.ApplicationInteractionsView.as_view(),
        name="application-interactions",
    ),
    path(
        "interactions/<int:interaction_id>",
        views.InteractionDetailView.as_view(),
        name="interaction-detail",
    ),
]
