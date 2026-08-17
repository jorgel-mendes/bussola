"""Admin for the metric catalog."""

from django import forms
from django.contrib import admin

from catalog.models import MetricDefinition, Statistic


class MetricDefinitionForm(forms.ModelForm):
    """Renders `statistics` as checkboxes rather than raw JSON.

    A free-text JSON field invites typos that would only surface at release
    time, when they are expensive.
    """

    statistics = forms.MultipleChoiceField(
        choices=Statistic.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=(
            "Quantiles are the cheapest statistics under DP (rank-based sensitivity, "
            "independent of value scale). Standard deviation is the most expensive — "
            "drop it first if budget is tight."
        ),
    )

    class Meta:
        model = MetricDefinition
        # Listed explicitly rather than "__all__" so that adding a field to the
        # model is a deliberate decision about whether it belongs in the admin
        # form -- important for a model whose fields carry privacy meaning.
        fields = [
            "collaboration",
            "code",
            "name",
            "unit",
            "value_type",
            "is_active",
            "lower_bound",
            "upper_bound",
            "bounds_rationale",
            "contributions_per_period",
            "statistics",
        ]


@admin.register(MetricDefinition)
class MetricDefinitionAdmin(admin.ModelAdmin):
    form = MetricDefinitionForm
    list_display = ["code", "name", "collaboration", "unit", "bounds", "contributions_per_period", "is_active"]
    list_filter = ["collaboration", "value_type", "is_active"]
    search_fields = ["code", "name"]
    fieldsets = [
        (None, {"fields": ["collaboration", "code", "name", "unit", "value_type", "is_active"]}),
        (
            "Differential privacy parameters",
            {
                "fields": [
                    "lower_bound",
                    "upper_bound",
                    "bounds_rationale",
                    "contributions_per_period",
                    "statistics",
                ],
                "description": (
                    "<strong>Bounds must come from public or domain knowledge — never "
                    "from the submitted data.</strong> Deriving clamping bounds from "
                    "private data leaks information. The rationale is shown to members "
                    "next to every published benchmark."
                ),
            },
        ),
    ]

    @admin.display(description="Bounds")
    def bounds(self, obj: MetricDefinition) -> str:
        return f"[{obj.lower_bound:g}, {obj.upper_bound:g}] {obj.unit}"
