"""Test settings.

Defaults to SQLite so `pytest` runs with no services. CI overrides DATABASE_URL
to point at a Postgres service, because the Sprint 2 concurrency tests
(SPEC section 7.3) need real row-level locking -- `select_for_update()` is a
no-op on SQLite and those tests would pass vacuously.
"""

from config.settings.base import *  # noqa: F403
from config.settings.base import REPO_DIR, env  # noqa: F401

DEBUG = False
SECRET_KEY = "test-key-not-secret"  # noqa: S105

DATABASES = {"default": env.db_url("DATABASE_URL", default="sqlite:///:memory:")}

# Fast, deterministic hashing in tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LOGGING = {"version": 1, "disable_existing_loggers": True, "root": {"handlers": []}}


def using_postgres() -> bool:
    """Used by tests that must skip when no real transactional DB is present."""
    return "postgresql" in DATABASES["default"]["ENGINE"]
