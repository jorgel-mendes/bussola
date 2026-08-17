"""Settings shared by every environment.

Twelve-factor: everything environment-specific comes from env vars via
django-environ, so the same image runs locally, in CI, and on Render.
"""

from pathlib import Path

import environ

# hub/config/settings/base.py -> hub/
HUB_DIR = Path(__file__).resolve().parent.parent.parent
REPO_DIR = HUB_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    MIN_CONTRIBUTORS=(int, 5),
)

env_file = REPO_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key-do-not-use-in-prod")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # Local
    "collaborations",
    "contributors",
    "catalog",
    "ingest",
    "privacy",
    "budget",
    "benchmarks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [HUB_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Default to Postgres. SQLite is available for a quick local run, but note that
# `select_for_update()` -- which the Sprint 2 budget accountant depends on -- is
# a no-op on SQLite, so the concurrency test suite requires Postgres.
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{REPO_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Bahia"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = HUB_DIR / "staticfiles"
STATICFILES_DIRS = [HUB_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["ingest.authentication.ContributorTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# --- Domain settings -------------------------------------------------------
# Deployment-wide floor for the minimum-contributor threshold. Each
# Collaboration carries its own `min_contributors`; this is the fallback when a
# collaboration leaves it unset. Conventional statistical disclosure control,
# not a DP requirement: it stops us publishing a "benchmark" that is visibly one
# or two contributors. See SPEC section 3.4.
MIN_CONTRIBUTORS = env("MIN_CONTRIBUTORS")
