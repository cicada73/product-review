from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """User model for the product review application."""

    def __str__(self):
        return self.username