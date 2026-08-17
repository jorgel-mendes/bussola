"""Serializers for the ingestion API.

The authoritative wire format lives in ``bussola_contracts.SubmissionPayload``.
This module must stay in step with it; ``test_contract.py`` fails if it drifts.

Every lookup here is scoped to the caller's collaboration, which is taken from
the authenticated contributor and never from the request body.
"""

from __future__ import annotations

from rest_framework import serializers

from catalog.models import MetricDefinition
from ingest.models import ReportingPeriod, Submission


class MetricSpecSerializer(serializers.ModelSerializer):
    """Published so agents can validate locally before submitting."""

    class Meta:
        model = MetricDefinition
        fields = [
            "code",
            "name",
            "unit",
            "value_type",
            "lower_bound",
            "upper_bound",
            "bounds_rationale",
            "contributions_per_period",
            "statistics",
        ]


class SubmissionCreateSerializer(serializers.Serializer):
    """Validates an agent payload.

    Note the absence of a contributor field: the contributor comes from the
    token, never the body. Metric and period are resolved *within the caller's
    collaboration*, so a code that exists in another collaboration resolves to
    "unknown" here rather than leaking its existence.

    Requires ``collaboration`` in the serializer context.
    """

    contract_version = serializers.CharField(max_length=8, required=False)
    metric_code = serializers.SlugField(max_length=50)
    period_label = serializers.CharField(max_length=16)
    value = serializers.DecimalField(max_digits=18, decimal_places=6)
    n_records = serializers.IntegerField(min_value=1)
    agent_version = serializers.CharField(max_length=32)

    @property
    def _collaboration(self):
        try:
            return self.context["collaboration"]
        except KeyError:  # pragma: no cover - programming error, not user input
            raise AssertionError(
                "SubmissionCreateSerializer requires 'collaboration' in its context."
            ) from None

    def validate_metric_code(self, value: str) -> MetricDefinition:
        try:
            return MetricDefinition.objects.get(
                code=value, is_active=True, collaboration=self._collaboration
            )
        except MetricDefinition.DoesNotExist:
            raise serializers.ValidationError(f"Unknown or inactive metric '{value}'.") from None

    def validate_period_label(self, value: str) -> ReportingPeriod:
        try:
            return ReportingPeriod.objects.get(label=value, collaboration=self._collaboration)
        except ReportingPeriod.DoesNotExist:
            raise serializers.ValidationError(f"Unknown reporting period '{value}'.") from None


class SubmissionAckSerializer(serializers.ModelSerializer):
    """Mirrors ``bussola_contracts.SubmissionAck``."""

    created = serializers.BooleanField(read_only=True)
    contributor = serializers.CharField(source="contributor.name", read_only=True)
    metric_code = serializers.CharField(source="metric.code", read_only=True)
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = Submission
        fields = ["id", "created", "contributor", "metric_code", "period_label", "value"]
