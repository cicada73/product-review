from django.conf import settings
from django.db import models
from django.db.models import Q


class ReviewReport(models.Model):
    class Reason(models.TextChoices):
        SPAM = "spam", "Spam"
        ABUSE = "abuse", "Abusive content"
        MISLEADING = "misleading", "Misleading content"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    review = models.ForeignKey(
        "reviews.Review",
        on_delete=models.PROTECT,
        related_name="reports",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_reports",
    )
    reason = models.CharField(
        max_length=20,
        choices=Reason.choices,
    )
    details = models.TextField(max_length=2000, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_review_reports",
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(max_length=2000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ("view",)
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="report_status_created_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "review"],
                name="unique_reporter_review",
            ),
            models.CheckConstraint(
                condition=Q(reason__in=[
                    "spam",
                    "abuse",
                    "misleading",
                    "other",
                ]),
                name="report_valid_reason",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="open",
                        resolved_by__isnull=True,
                        resolved_at__isnull=True,
                    )
                    | Q(
                        status__in=["resolved", "dismissed"],
                        resolved_by__isnull=False,
                        resolved_at__isnull=False,
                    )
                ),
                name="report_valid_resolution",
            ),
        ]

    def __str__(self):
        return f"Report {self.pk} on review {self.review_id}"


class ModerationAction(models.Model):
    class Action(models.TextChoices):
        APPROVE_REVIEW = "approve_review", "Approve review"
        REJECT_REVIEW = "reject_review", "Reject review"
        RESOLVE_REPORT = "resolve_report", "Resolve report"
        DISMISS_REPORT = "dismiss_report", "Dismiss report"
        SUSPEND_USER = "suspend_user", "Suspend user"
        RESTORE_USER = "restore_user", "Restore user"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="moderation_actions",
    )
    action = models.CharField(
        max_length=32,
        choices=Action.choices,
    )

    review = models.ForeignKey(
        "reviews.Review",
        on_delete=models.PROTECT,
        related_name="moderation_actions",
        null=True,
        blank=True,
    )
    report = models.ForeignKey(
        ReviewReport,
        on_delete=models.PROTECT,
        related_name="moderation_actions",
        null=True,
        blank=True,
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="moderation_history",
        null=True,
        blank=True,
    )

    reason = models.TextField(max_length=2000)
    previous_state = models.CharField(max_length=32)
    new_state = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ("view",)
        permissions = [
            ("moderate_reviews", "Can approve and reject reviews"),
            ("manage_reports", "Can resolve and dismiss review reports"),
            ("suspend_users", "Can suspend and restore user accounts"),
        ]
        indexes = [
            models.Index(
                fields=["action", "created_at"],
                name="mod_action_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        action__in=["approve_review", "reject_review"],
                        review__isnull=False,
                        report__isnull=True,
                        target_user__isnull=True,
                    )
                    | Q(
                        action__in=["resolve_report", "dismiss_report"],
                        review__isnull=True,
                        report__isnull=False,
                        target_user__isnull=True,
                    )
                    | Q(
                        action__in=["suspend_user", "restore_user"],
                        review__isnull=True,
                        report__isnull=True,
                        target_user__isnull=False,
                    )
                ),
                name="moderation_action_valid_target",
            ),
            models.CheckConstraint(
                condition=~Q(reason=""),
                name="moderation_action_reason_required",
            ),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by user {self.actor_id}"