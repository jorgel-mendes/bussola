"""Ingestion API routes (mounted under /api/v1/)."""

from django.urls import path

from ingest import views

app_name = "ingest"

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("metrics/", views.MetricListView.as_view(), name="metric-list"),
    path("submissions/", views.create_submission, name="submission-create"),
]
