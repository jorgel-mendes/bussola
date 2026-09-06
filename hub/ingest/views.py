"""Ingestion API.

Every query is scoped to the caller's collaboration, derived from the
authenticated contributor. There is no endpoint that accepts a collaboration
identifier from the client.

Status codes are chosen so an agent can act on them without parsing prose:

* 401 — bad, revoked, inactive-contributor or inactive-collaboration token
* 409 — the reporting period is not open (a scheduling problem, retry later)
* 422 — the value is outside the metric's declared bounds (a data problem,
        do not retry; the operator must look at it)
* 400 — malformed payload, or a metric/period not in this collaboration

409 vs 422 is the distinction that matters: one is transient, the other is not.
"""

from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from benchmarks.positions import PositionUnavailable, position_for
from bussola_contracts import CONTRACT_VERSION
from catalog.models import MetricDefinition
from ingest.models import ReportingPeriod, Submission
from ingest.serializers import (
    MetricSpecSerializer,
    SubmissionAckSerializer,
    SubmissionCreateSerializer,
)


class MetricListView(ListAPIView):
    """GET /api/v1/metrics/ — the catalog an agent validates against.

    Scoped to the caller's collaboration. An agent cannot enumerate another
    collaboration's metrics, which would leak what that group measures.
    """

    serializer_class = MetricSpecSerializer

    def get_queryset(self):
        return MetricDefinition.objects.filter(
            is_active=True, collaboration=self.request.user.collaboration
        )


@api_view(["POST"])
def create_submission(request: Request) -> Response:
    """POST /api/v1/submissions/

    Idempotent by (contributor, period, metric): a resubmission updates in
    place. Without that, a contributor could submit twice and double its weight
    in the aggregate, breaking the per-contributor sensitivity bound the privacy
    guarantee depends on.
    """
    contributor = request.user  # set by ContributorTokenAuthentication

    serializer = SubmissionCreateSerializer(
        data=request.data, context={"collaboration": contributor.collaboration}
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    metric: MetricDefinition = data["metric_code"]
    period = data["period_label"]
    value = data["value"]

    if not period.accepts_submissions:
        return Response(
            {
                "detail": f"Reporting period '{period.label}' is {period.status}.",
                "code": "period_not_open",
            },
            status=status.HTTP_409_CONFLICT,
        )

    if not metric.is_within_bounds(value):
        # Rejected rather than silently clamped. Clamping here would hide a
        # sensor or unit-conversion fault behind a plausible number, and the
        # operator would never learn about it.
        return Response(
            {
                "detail": (
                    f"Value {value} is outside the declared bounds "
                    f"[{metric.lower_bound}, {metric.upper_bound}] for '{metric.code}'."
                ),
                "code": "value_out_of_bounds",
                "lower_bound": str(metric.lower_bound),
                "upper_bound": str(metric.upper_bound),
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    with transaction.atomic():
        submission, created = Submission.objects.update_or_create(
            contributor=contributor,
            period=period,
            metric=metric,
            defaults={
                "value": value,
                "n_records": data["n_records"],
                "agent_version": data["agent_version"],
            },
        )

    submission.created = created
    body = SubmissionAckSerializer(submission).data
    return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def contributor_position(request: Request) -> Response:
    """GET /api/v1/position/?metric=<code>&period=<label> — "where am I?" (S3-1)

    THIS ENDPOINT COMPUTES NOTHING. It reads an already-published release and
    places the caller's own submitted value against it. That is post-processing
    of a differentially private output, so it spends no budget — which is what
    makes it safe to expose to an agent that may poll it. An endpoint that
    released statistics on read would let a cron job drain a collaboration's
    budget overnight, and `test_position_api.py` asserts that this one does not.

    The cohort is taken from the authenticated contributor, never from the
    query string: a member cannot ask where it would sit in a cohort it does
    not belong to.

    404, not 200-with-nulls, when there is nothing to report. An empty quartile
    rendered beside a real one reads as an answer.
    """
    contributor = request.user

    metric_code = request.query_params.get("metric")
    period_label = request.query_params.get("period")
    if not metric_code or not period_label:
        return Response(
            {"detail": "Both 'metric' and 'period' are required.", "code": "missing_parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Scoped to the caller's collaboration, so an unknown code and another
    # group's code are indistinguishable from outside.
    metric = MetricDefinition.objects.filter(
        code=metric_code, collaboration=contributor.collaboration, is_active=True
    ).first()
    if metric is None:
        return Response(
            {"detail": f"No active metric '{metric_code}'.", "code": "unknown_metric"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    period = ReportingPeriod.objects.filter(
        label=period_label, collaboration=contributor.collaboration
    ).first()
    if period is None:
        return Response(
            {"detail": f"No period '{period_label}'.", "code": "unknown_period"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        position = position_for(contributor=contributor, metric=metric, period=period)
    except PositionUnavailable as exc:
        # exc.code, not a single generic code: an agent must be able to tell
        # "you never submitted" from "the operator has not released yet"
        # without reading English.
        return Response(
            {"detail": str(exc), "code": exc.code},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        {
            "contract_version": CONTRACT_VERSION,
            "metric_code": metric.code,
            "metric_unit": metric.unit,
            "period_label": period.label,
            "cohort_code": contributor.cohort.code,
            "your_value": str(position.submission_value),
            "n_contributors": position.release.n_contributors,
            "epsilon_spent": str(position.release.epsilon_spent),
            "released_q25": str(position.released["q25"]),
            "released_median": str(position.released["median"]),
            "released_q75": str(position.released["q75"]),
            "quartile": position.quartile,
            "is_usable": position.is_usable,
            "caveat": position.caveat,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def healthz(request: Request) -> Response:
    """Unauthenticated liveness probe.

    Also the URL to warm before recording the demo — Render's free tier sleeps
    after inactivity and a cold start on camera is avoidable.
    """
    return Response({"status": "ok"})
