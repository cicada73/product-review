from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    readonly_fields = ("is_active", "session_version")

    fieldsets = UserAdmin.fieldsets + (
        (
            "Session security",
            {"fields": ("session_version",)},
        ),
    )