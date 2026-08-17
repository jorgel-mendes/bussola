"""Admin for collaborations and cohorts."""

from django.contrib import admin

from collaborations.models import Cohort, Collaboration


class CohortInline(admin.TabularInline):
    model = Cohort
    extra = 0


@admin.register(Collaboration)
class CollaborationAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "operator_name",
        "operator_kind",
        "min_contributors",
        "contributor_count",
        "is_active",
    ]
    list_filter = ["operator_kind", "is_active"]
    search_fields = ["name", "slug", "operator_name"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CohortInline]
    fieldsets = [
        (None, {"fields": ["slug", "name", "description", "is_active"]}),
        (
            "Trusted curator",
            {
                "fields": ["operator_name", "operator_kind"],
                "description": (
                    "The hub operator sees raw submissions before noise is applied. "
                    "The guarantee offered to contributors is therefore only as strong "
                    "as their existing reason to trust this operator — so it is "
                    "recorded explicitly and shown to contributors."
                ),
            },
        ),
        (
            "Disclosure control",
            {
                "fields": ["min_contributors"],
                "description": (
                    "Minimum contributing parties before a cell may be published. "
                    "A cell drawn from two contributors is a disclosure, not a benchmark."
                ),
            },
        ),
    ]

    @admin.display(description="Contributors")
    def contributor_count(self, obj: Collaboration) -> int:
        return obj.contributors.count()


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "collaboration", "contributor_count"]
    list_filter = ["collaboration"]
    search_fields = ["code", "name"]

    @admin.display(description="Contributors")
    def contributor_count(self, obj: Cohort) -> int:
        return obj.contributors.count()
