"""Local development settings."""

from config.settings.base import *  # noqa: F403
from config.settings.base import env  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Readable errors in the console rather than silent 500s.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# ManifestStaticFilesStorage requires collectstatic to have run; unhelpful in dev.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
