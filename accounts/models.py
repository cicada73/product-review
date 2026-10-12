from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.crypto import salted_hmac


class User(AbstractUser):
    email = models.EmailField(unique=True)
    session_version = models.PositiveIntegerField(
        default=0,
        editable=False,
    )

    def __str__(self):
        return self.username

    def _build_session_auth_hash(self, secret):
        return salted_hmac(
            "accounts.User.session_auth",
            f"{self.password}:{self.session_version}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    def get_session_auth_hash(self):
        return self._build_session_auth_hash(settings.SECRET_KEY)

    def get_session_auth_fallback_hash(self):
        for secret in settings.SECRET_KEY_FALLBACKS:
            yield self._build_session_auth_hash(secret)