"""Contributors and their credentials.

A *contributor* is a party that submits data to a collaboration: a plant, a
hospital site, a reporting unit, a firm. The platform is domain-neutral, so the
noun is too.

Note on the privacy model: contributor *membership* is public -- parties join a
collaboration openly and the roster is not secret. What is protected is each
contributor's reported *values*. So nothing in this module needs privacy
treatment; it is ordinary tenant management.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from django.db import models
from django.utils import timezone

TOKEN_BYTES = 32
TOKEN_PREFIX_LEN = 8


def hash_token(raw: str) -> str:
    """Hash a raw API token for storage.

    SHA-256 rather than a password hasher on purpose: tokens are high-entropy
    random strings, not user-chosen secrets, so they are not brute-forceable and
    a slow KDF would only add latency to every API call.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Contributor(models.Model):
    collaboration = models.ForeignKey(
        "collaborations.Collaboration", on_delete=models.CASCADE, related_name="contributors"
    )
    external_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    name = models.CharField(max_length=160)
    cohort = models.ForeignKey(
        "collaborations.Cohort", on_delete=models.PROTECT, related_name="contributors"
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["collaboration", "name"], name="uniq_contributor_name_per_collaboration"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_authenticated(self) -> bool:
        """DRF's ``IsAuthenticated`` permission checks this attribute.

        A Contributor resolved from a valid API token *is* the request
        principal -- there is no Django ``User`` behind an agent.
        """
        return True


class ApiTokenQuerySet(models.QuerySet):
    def active(self) -> ApiTokenQuerySet:
        return self.filter(revoked_at__isnull=True, contributor__is_active=True)


class ApiToken(models.Model):
    """Bearer credential for one contributor's agent.

    Only the hash is stored. The raw token is returned exactly once, at
    creation. Storing raw API keys in a system whose entire premise is data
    protection would be indefensible in the demo.
    """

    contributor = models.ForeignKey(Contributor, on_delete=models.CASCADE, related_name="tokens")
    label = models.CharField(max_length=60, blank=True, help_text="e.g. 'kiln-line-1 agent'")
    prefix = models.CharField(
        max_length=TOKEN_PREFIX_LEN,
        editable=False,
        help_text="Leading characters, for identifying a token without revealing it.",
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = ApiTokenQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"{self.contributor.name} · {self.prefix}… ({state})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.contributor.is_active

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    @classmethod
    def issue(cls, contributor: Contributor, label: str = "") -> tuple[ApiToken, str]:
        """Create a token. Returns ``(token, raw_key)``; the raw key is
        unrecoverable after this."""
        raw = secrets.token_urlsafe(TOKEN_BYTES)
        token = cls.objects.create(
            contributor=contributor,
            label=label,
            prefix=raw[:TOKEN_PREFIX_LEN],
            key_hash=hash_token(raw),
        )
        return token, raw
