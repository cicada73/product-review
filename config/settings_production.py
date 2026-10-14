"""Settings for the deployed application."""

import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *


# Always disable debug output in production.
DEBUG = False

if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Production requires explicit DJANGO_ALLOWED_HOSTS values."
    )

# Additional trusted origins, if required by the hosting setup.
# Values must include the scheme, for example https://reviews.example.com.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# Require HTTPS.
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Browser security headers.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Enable HSTS after verifying HTTPS on the deployed domain.
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False