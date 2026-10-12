from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create or update the application's moderation roles."

    @transaction.atomic
    def handle(self, *args, **options):
        roles = {
            "Review Moderators": {
                "moderate_reviews",
                "manage_reports",
                "view_reviewreport",
                "view_moderationaction",
            },
            "Account Managers": {
                "suspend_users",
                "view_moderationaction",
            },
        }

        for name, codenames in roles.items():
            permissions = list(
                Permission.objects.filter(
                    content_type__app_label="moderation",
                    codename__in=codenames,
                )
            )

            found = {permission.codename for permission in permissions}
            missing = codenames - found

            if missing:
                raise CommandError(
                    "Missing permissions: "
                    + ", ".join(sorted(missing))
                    + ". Run migrate first."
                )

            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)

            self.stdout.write(
                self.style.SUCCESS(f"Configured role: {name}")
            )