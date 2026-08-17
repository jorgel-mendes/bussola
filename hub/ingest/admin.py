"""Admin for reporting periods and submissions."""

from django.contrib import admin

from ingest.models import PeriodStatus, ReportingPeriod, Submission


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ["label", "collaboration", "starts", "ends", "status", "submission_count"]
    list_filter = ["collaboration", "status"]
    search_fields = ["label"]
    actions = ["close_periods", "reopen_periods"]

    @admin.display(description="Submissions")
    def submission_count(self, obj: ReportingPeriod) -> int:
        return obj.submissions.count()

    @admin.action(description="Close selected periods")
    def close_periods(self, request, queryset) -> None:
        updated = queryset.filter(status=PeriodStatus.OPEN).update(status=PeriodStatus.CLOSED)
        self.message_user(request, f"Closed {updated} period(s).")

    @admin.action(description="Reopen selected periods")
    def reopen_periods(self, request, queryset) -> None:
        """Reopening a RELEASED period is refused.

        Accepting new submissions after a release would let inputs change under
        an already-published benchmark, spending privacy budget the accountant
        never charged.
        """
        released = queryset.filter(status=PeriodStatus.RELEASED)
        if released.exists():
            self.message_user(
                request,
                f"Refused: {released.count()} period(s) already released and cannot reopen.",
                level="ERROR",
            )
        updated = queryset.filter(status=PeriodStatus.CLOSED).update(status=PeriodStatus.OPEN)
        self.message_user(request, f"Reopened {updated} period(s).")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["contributor", "metric", "period", "value", "n_records", "submitted_at"]
    list_filter = ["period", "metric", "contributor__cohort"]
    search_fields = ["contributor__name", "metric__code"]
    readonly_fields = ["submitted_at", "updated_at", "agent_version"]
    date_hierarchy = "submitted_at"

    def has_change_permission(self, request, obj=None) -> bool:
        """Submissions in a released period are frozen (SPEC section 5.3, rule 2)."""
        if obj is not None and obj.period.status == PeriodStatus.RELEASED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:
        if obj is not None and obj.period.status == PeriodStatus.RELEASED:
            return False
        return super().has_delete_permission(request, obj)
