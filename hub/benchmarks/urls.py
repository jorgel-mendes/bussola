"""Dashboard routes."""

from django.urls import path

from benchmarks import views

app_name = "benchmarks"

urlpatterns = [
    path("", views.benchmark_index, name="index"),
]
