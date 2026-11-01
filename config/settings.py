from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = bool(int(os.getenv("DEBUG", 1)))

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1").split(",")


AUTH_USER_MODEL = "authentication.User"


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.authentication",
    "apps.calendars",
    "apps.clinic",
    "apps.core",

    # packages
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_yasg',
    'django_filters',
    'corsheaders'



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

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ["x-api-key", "content-type", "Authorization"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, 'templates')],
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
        "NAME": os.getenv("DB_NAME", "default"),
        "USER": os.getenv("DB_USER", "default"),
        "PASSWORD": os.getenv("DB_PASSWORD", "default"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", 5432),
    }
}





AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]




LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Tashkent"

USE_I18N = True

USE_TZ = True



STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.authentication.custom_jwt.CustomJwtAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "EXCEPTION_HANDLER": "apps.core.exceptions.drf_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.utils.BackendPageNumberPagination",
    "PAGE_SIZE": 10,
}

JWT_USE = True
ACCESS_TOKEN_LIFETIME = timedelta(days=int(os.getenv("ACCESS_TOKEN_LIFETIME_DAYS", 1)))
REFRESH_TOKEN_LIFETIME = timedelta(
    days=int(os.getenv("REFRESH_TOKEN_LIFETIME_DAYS", 2))
)
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": ACCESS_TOKEN_LIFETIME,
    "REFRESH_TOKEN_LIFETIME": REFRESH_TOKEN_LIFETIME,
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}


SWAGGER_SETTINGS = {
    # "DEFAULT_API_URL": os.getenv("SWAGGER_API_URL", "http://127.0.0.1:8000"),
    "SECURITY_DEFINITIONS": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT Authentication. Format: **Bearer &lt;access_token&gt;**",
        }
    },
    "SWAGGER_UI_REQUEST_HEADERS": [
        {
            "name": "Authorization",
            "description": "JWT Token",
            "value": "Bearer ",
        },
    ],
}


CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE