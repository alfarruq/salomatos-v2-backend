import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# Secure by default: production must not depend on someone remembering to
# switch DEBUG off.
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY is not set. See .env.example.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")

AUTH_USER_MODEL = "accounts.User"

ADMIN_URL = os.getenv("ADMIN_URL", "admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "apps.core",
    "apps.accounts",
    "apps.tenancy",
    "apps.audit",
    "apps.patients",
    "apps.catalog",
    "apps.scheduling",
    "apps.clinical",
    "apps.imaging",
    "apps.dental",
    "apps.billing",
    "apps.finance",
    "apps.bot",
    "apps.voice",
    "apps.saas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# The frontend is served from the same origin as /api, so cross-origin access
# is closed unless an origin is listed explicitly.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_HEADERS = ["authorization", "content-type", "x-clinic-id", "x-organization-id"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "salomatos_v2"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files hold PHI. MEDIA_ROOT is a private directory: nothing maps it
# to a URL, files are streamed by authenticated views. The storage backend is
# configurable so the files can move (e.g. to a server inside Uzbekistan)
# without code changes.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "private_media"))
MEDIA_URL = None
STORAGES = {
    "default": {"BACKEND": os.getenv("FILE_STORAGE_BACKEND", "django.core.files.storage.FileSystemStorage")},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MAX_ATTACHMENT_BYTES = int(os.getenv("MAX_ATTACHMENT_MB", "50")) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.drf_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "login": os.getenv("LOGIN_THROTTLE_RATE", "10/min"),
        "login_username": os.getenv("LOGIN_USERNAME_THROTTLE_RATE", "20/hour"),
    },
    # How many proxies sit in front of Django. Without it DRF trusts the whole
    # X-Forwarded-For header, which a client writes itself, so every guess
    # could claim a new address. Behind one nginx set NUM_PROXIES=1.
    "NUM_PROXIES": int(os.getenv("NUM_PROXIES", "0")),
}

# Throttle counters must be shared by every worker process; the default
# in-process cache would give each worker its own count.
if os.getenv("CACHE_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": os.getenv("CACHE_URL")}}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("ACCESS_TOKEN_LIFETIME_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("REFRESH_TOKEN_LIFETIME_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SalomatOS API",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "PlatformPaymentKindEnum": "apps.saas.models.PlatformPayment.Kind",
        "AttachmentKindEnum": "apps.imaging.models.Attachment.Kind",
        "BotAccountKindEnum": "apps.bot.models.BotAccount.Kind",
        "PaymentMethodEnum": "apps.billing.models.Payment.Method",
    },
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Telegram bot. The token comes from @BotFather; without it `run_bot` refuses to start.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Fernet key for bot passwords (see apps/bot/crypto.py). Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
BOT_CREDENTIAL_KEY = os.getenv("BOT_CREDENTIAL_KEY", "")

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # Preload is a hard-to-undo commitment for the whole domain; decide it at deploy time.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    # httpx logs every request URL at INFO, and Telegram puts the bot token in the URL.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

# Voice input: a dictation becomes a form draft. Off while the key is empty.
# The dictated text goes to Anthropic's API; it is never stored or logged here.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VOICE_MODEL = os.getenv("VOICE_MODEL", "claude-haiku-5-5")
# Drafts per clinic per calendar month: the cap behind the paid voice add-on.
VOICE_MONTHLY_LIMIT = int(os.getenv("VOICE_MONTHLY_LIMIT", "1500"))
