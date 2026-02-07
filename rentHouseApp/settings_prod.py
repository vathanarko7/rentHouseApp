from .settings import *  # noqa: F403
import os

DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PGDATABASE", ""),
        "USER": os.getenv("PGUSER", ""),
        "PASSWORD": os.getenv("PGPASSWORD", ""),
        "HOST": os.getenv("PGHOST", ""),
        "PORT": os.getenv("PGPORT", "5432"),
    }
}

GS_BUCKET_NAME = os.getenv("GS_BUCKET_NAME", "")
USE_GCS = os.getenv("USE_GCS", "false").lower() == "true"

if USE_GCS and GS_BUCKET_NAME:
    INSTALLED_APPS = [*INSTALLED_APPS, "storages"]  # noqa: F405
    GS_QUERYSTRING_AUTH = False
    GS_DEFAULT_ACL = None
    STATIC_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/"
    MEDIA_URL = STATIC_URL
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
            "OPTIONS": {"bucket_name": GS_BUCKET_NAME},
        },
        "staticfiles": {
            "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
            "OPTIONS": {"bucket_name": GS_BUCKET_NAME},
        },
    }
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(MEDIA_ROOT), "base_url": MEDIA_URL},
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
