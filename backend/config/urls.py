from __future__ import annotations

from django.urls import include, path, re_path

from watcher.views import healthcheck, spa_index

urlpatterns = [
    path("healthz", healthcheck, name="healthz"),
    # Pipeline routes first: watcher.urls ends with the API catch all (404 envelope).
    path("api/v1/", include("pipeline.urls")),
    path("api/v1/", include("watcher.urls")),
    re_path(r"^(?!api/|api$|healthz|admin|static/).*$", spa_index, name="spa"),
]
