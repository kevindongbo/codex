import os
from pathlib import Path

import dj_database_url
from corsheaders.defaults import default_headers
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if DEBUG and not SECRET_KEY:
    SECRET_KEY = "unsafe-development-key-change-before-deployment"
if not DEBUG and (
    len(SECRET_KEY) < 50
    or SECRET_KEY.startswith("REPLACE_")
    or SECRET_KEY == "unsafe-development-key-change-before-deployment"
):
    raise ImproperlyConfigured(
        "Production requires DJANGO_SECRET_KEY with at least 50 non-placeholder characters."
    )

ALLOWED_HOSTS = [v.strip() for v in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if v.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "apps.erp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}

# Development keeps cache in memory. Production uses a shared on-host file
# cache so all Gunicorn workers reuse the same paid selection response.
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.locmem.LocMemCache"
            if DEBUG else "django.core.cache.backends.filebased.FileBasedCache"
        ),
        "LOCATION": (
            "dongbo-erp-development-cache"
            if DEBUG else os.getenv("DJANGO_CACHE_LOCATION", "/tmp/dongbo-erp-cache")
        ),
        "TIMEOUT": 600,
        "OPTIONS": {"MAX_ENTRIES": 2000},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True
INTERNAL_ORGANIZATION_NAME = os.getenv("INTERNAL_ORGANIZATION_NAME", "东铂跨境")
INTERNAL_ORGANIZATION_SLUG = os.getenv("INTERNAL_ORGANIZATION_SLUG", "dongbo-internal")
OWNER_EMAIL_VERIFICATION_REQUIRED = env_bool("OWNER_EMAIL_VERIFICATION_REQUIRED")
OWNER_EMAIL_CODE_TTL_SECONDS = int(os.getenv("OWNER_EMAIL_CODE_TTL_SECONDS", "600"))
ALPHASHOP_ACCESS_KEY = os.getenv("ALPHASHOP_ACCESS_KEY", os.getenv("ALPHACLAW_ACCESS_KEY", "")).strip()
ALPHASHOP_SECRET_KEY = os.getenv("ALPHASHOP_SECRET_KEY", os.getenv("ALPHACLAW_SECRET_KEY", "")).strip()
ALPHASHOP_API_BASE = os.getenv("ALPHASHOP_API_BASE", "https://api.alphashop.cn").strip().rstrip("/")
ALPHASHOP_KEYWORD_TIMEOUT = int(os.getenv("ALPHASHOP_KEYWORD_TIMEOUT", "30"))
ALPHASHOP_REPORT_TIMEOUT = int(os.getenv("ALPHASHOP_REPORT_TIMEOUT", "120"))
ALPHASHOP_KEYWORD_CACHE_SECONDS = int(os.getenv("ALPHASHOP_KEYWORD_CACHE_SECONDS", "600"))
ALPHASHOP_REPORT_CACHE_SECONDS = int(os.getenv("ALPHASHOP_REPORT_CACHE_SECONDS", "1800"))
EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@localhost")
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", str(25 * 1024 * 1024)))

CORS_ALLOWED_ORIGINS = [v.strip() for v in os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",") if v.strip()]
CORS_ALLOW_HEADERS = (*default_headers, "x-organization-id")
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if v.strip()]

# The API container is only reachable through the trusted Caddy service in the
# supplied Compose network. Caddy sets X-Forwarded-Proto for HTTPS requests.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.erp.authentication.InternalJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "EXCEPTION_HANDLER": "apps.erp.exceptions.erp_exception_handler",
    "PAGE_SIZE": 50,
}
