"""Dashboard views.

Sprint 2: every figure on this page is a differentially private release that
was published by an explicit operator action and charged to the collaboration's
privacy budget. Nothing here computes a statistic.

That is a privacy property, not an implementation detail. If rendering the page
released statistics, a browser refresh would spend epsilon and a crawler would
exhaust a collaboration's budget in seconds. Releasing is
`manage.py release_period`; viewing reads what was already published.

What was removed in this sprint, and why it mattered: Sprint 1's version
rendered a <details> block listing every contributor's exact submitted value.
It was there to prove the pipeline worked. It is the single most direct
disclosure the platform could make -- the precise thing the product exists to
prevent -- and it is gone (S2-12).
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404, render

from benchmarks.models import BenchmarkRelease, display_sorted
from benchmarks.utility import curve_series, reading_for
from catalog.models import MetricDefinition
from collaborations.models import Cohort, Collaboration
from ingest.models import ReportingPeriod


def benchmark_index(request):
    """Landing page: pick a cell and see its published release, if any."""
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

    release = None
    statistics = []
    cohort = metric = period = None
    n_submissions = 0
    utility = None

    if selected_cohort and selected_metric and selected_period:
        cohort = get_object_or_404(Cohort, code=selected_cohort, collaboration=collaboration)
        metric = get_object_or_404(
            MetricDefinition, code=selected_metric, collaboration=collaboration
        )
        period = get_object_or_404(
            ReportingPeriod, label=selected_period, collaboration=collaboration
        )

        # Read only. No mechanism runs here and no budget is charged.
        release = (
            BenchmarkRelease.objects.filter(cohort=cohort, metric=metric, period=period)
            .prefetch_related("statistics")
            .first()
        )
        if release:
            # Reading order, not the model's alphabetical Meta ordering,
            # which puts "median" before "q25".
            statistics = display_sorted(release.statistics.all())
            # S3-3. What the sweep measured at this release's own epsilon and
            # cohort size. Static data read from a committed digest — no
            # mechanism runs, so this costs nothing and cannot fail the page.
            utility = reading_for(
                epsilon=release.epsilon_spent, n=release.n_contributors
            )
        else:
            # Contributor count only, so an unreleased cell can explain itself.
            # Membership is public (DESIGN.md section 2.2), so this leaks
            # nothing -- and no individual value is read.
            from benchmarks.selectors import submissions_for

            n_submissions = submissions_for(cohort, metric, period).count()

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
            "cohort": cohort,
            "metric": metric,
            "period": period,
            "release": release,
            "statistics": statistics,
            "n_submissions": n_submissions,
            "min_contributors": collaboration.effective_min_contributors,
            "utility": utility,
            "curve": curve_series(),
        },
    )
