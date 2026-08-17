"""Token authentication for contributor agents.

Agents are not Django users. The request principal is a ``Contributor``,
resolved from the bearer token. This is deliberate: it means an agent cannot
submit on another contributor's behalf, because the identity is never taken
from the request body -- only from the credential.

The collaboration is derived from the contributor, so an agent also cannot
reach another collaboration's metrics or periods.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, exceptions

from contributors.models import ApiToken, Contributor, hash_token

KEYWORD = "Bearer"


class ContributorTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate ``Authorization: Bearer <token>`` against ApiToken.key_hash."""

    keyword = KEYWORD

    def authenticate(self, request) -> tuple[Contributor, ApiToken] | None:
        header = authentication.get_authorization_header(request).split()

        if not header or header[0].lower() != self.keyword.lower().encode():
            return None  # No credential offered; let permissions reject it.

        if len(header) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header: no credentials provided.")
        if len(header) > 2:
            raise exceptions.AuthenticationFailed(
                "Invalid token header: token may not contain spaces."
            )

        try:
            raw = header[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid token header: not valid UTF-8.") from None

        return self._authenticate_key(raw)

    def _authenticate_key(self, raw: str) -> tuple[Contributor, ApiToken]:
        try:
            token = ApiToken.objects.select_related("contributor__collaboration").get(
                key_hash=hash_token(raw)
            )
        except ApiToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid token.") from None

        # Deliberately the same message for revoked, unknown, inactive-contributor
        # and inactive-collaboration tokens: distinguishing them would confirm to
        # an attacker that a particular token once existed.
        if token.revoked_at is not None:
            raise exceptions.AuthenticationFailed("Invalid token.")
        if not token.contributor.is_active:
            raise exceptions.AuthenticationFailed("Invalid token.")
        if not token.contributor.collaboration.is_active:
            raise exceptions.AuthenticationFailed("Invalid token.")

        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.contributor, token

    def authenticate_header(self, request) -> str:
        """Returning this makes DRF answer 401 rather than 403 on failure."""
        return self.keyword
