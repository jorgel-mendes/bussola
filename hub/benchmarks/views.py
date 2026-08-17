"""Dashboard views.

Sprint 1 renders EXACT statistics behind an unmissable warning. Keeping the
warning in the template rather than a code comment is deliberate: it is the
control that stops an exact-value page being mistaken for a safe one, and it
gives the final demo a clean before/after beat.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404, render

from benchmarks.selectors import compute_exact_benchmark, submissions_for
from catalog.models import MetricDefinition
from collaborations.models import Cohort, Collaboration
from ingest.models import ReportingPeriod


def benchmark_index(request):
    """Landing page: pick a collaboration, cohort, metric and period."""
    collaborations = Collaboration.objects.filter(is_active=True)
    if not collaborations:
        return render(request, "benchmarks/index.html", {"collaborations": []})

    selected_collab = request.GET.get("collaboration") or collaborations[0].slug
    collaboration = get_object_or_404(Collaboration, slug=selected_collab, is_active=True)

    # Every subsequent queryset is scoped to the chosen collaboration, so the
    # dashboard cannot combine cohorts and metrics from separate groups.
    cohorts = collaboration.cohorts.all()
    metrics = collaboration.metrics.filter(is_active=True)
    periods = collaboration.periods.all()[:24]

    selected_cohort = request.GET.get("cohort") or (cohorts[0].code if cohorts else None)
    selected_metric = request.GET.get("metric") or (metrics[0].code if metrics else None)
    selected_period = request.GET.get("period") or (periods[0].label if periods else None)

    result = None
    contributions = []
    if selected_cohort and selected_metric and selected_period:
        cohort = get_object_or_404(Cohort, code=selected_cohort, collaboration=collaboration)
        metric = get_object_or_404(
            MetricDefinition, code=selected_metric, collaboration=collaboration
        )
        period = get_object_or_404(
            ReportingPeriod, label=selected_period, collaboration=collaboration
        )
        result = compute_exact_benchmark(cohort, metric, period)

        if not result.suppressed:
            # Sprint 1 only. This list is per-contributor data and must NOT
            # survive into Sprint 2 -- it is exactly what the platform exists to
            # avoid publishing. It is here so the pipeline is visibly working.
            contributions = [
                {"contributor": s.contributor.name, "value": s.value}
                for s in submissions_for(cohort, metric, period).order_by("value")
            ]

    return render(
        request,
        "benchmarks/index.html",
        {
            "collaborations": collaborations,
            "collaboration": collaboration,
            "cohorts": cohorts,
            "metrics": metrics,
            "periods": periods,
            "selected_collaboration": collaboration.slug,
            "selected_cohort": selected_cohort,
            "selected_metric": selected_metric,
            "selected_period": selected_period,
            "result": result,
            "contributions": contributions,
        },
    )
