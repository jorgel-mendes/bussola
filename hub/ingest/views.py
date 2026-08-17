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

from catalog.models import MetricDefinition
from ingest.models import Submission
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
@permission_classes([AllowAny])
def healthz(request: Request) -> Response:
    """Unauthenticated liveness probe.

    Also the URL to warm before recording the demo — Render's free tier sleeps
    after inactivity and a cold start on camera is avoidable.
    """
    return Response({"status": "ok"})
