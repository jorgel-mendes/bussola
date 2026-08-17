"""Admin for contributors and credentials.

Django admin *is* the operator's console for Sprint 1. Building it properly here
is why there is no bespoke CRUD UI in the backlog.
"""

from django.contrib import admin, messages
from django.utils import timezone

from contributors.models import ApiToken, Contributor


@admin.register(Contributor)
class ContributorAdmin(admin.ModelAdmin):
    list_display = ["name", "collaboration", "cohort", "is_active", "joined_at", "submission_count"]
    list_filter = ["collaboration", "cohort", "is_active"]
    search_fields = ["name", "external_id"]
    readonly_fields = ["external_id"]
    actions = ["issue_token"]

    @admin.display(description="Submissions")
    def submission_count(self, obj: Contributor) -> int:
        return obj.submissions.count()

    @admin.action(description="Issue a new API token")
    def issue_token(self, request, queryset) -> None:
        """Issue tokens and surface the raw keys once, in a message.

        This is the only moment the raw key exists in readable form -- the model
        stores a SHA-256 hash. If the operator misses it, the token must be
        revoked and reissued.
        """
        for contributor in queryset:
            _token, raw = ApiToken.issue(contributor, label=f"issued by {request.user}")
            self.message_user(
                request,
                f"Token for {contributor.name}: {raw}  — copy it now, it cannot be shown again.",
                level=messages.WARNING,
            )


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ["contributor", "prefix", "label", "created_at", "last_used_at", "state"]
    list_filter = ["contributor__collaboration", "revoked_at"]
    search_fields = ["contributor__name", "prefix", "label"]
    readonly_fields = ["contributor", "prefix", "key_hash", "created_at", "last_used_at"]
    actions = ["revoke_tokens"]

    @admin.display(description="State", boolean=True)
    def state(self, obj: ApiToken) -> bool:
        return obj.is_active

    def has_add_permission(self, request) -> bool:
        """Tokens are issued via the Contributor action, which returns the raw key.

        Adding one here would create a token whose raw value nobody ever saw.
        """
        return False

    @admin.action(description="Revoke selected tokens")
    def revoke_tokens(self, request, queryset) -> None:
        updated = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {updated} token(s).")
