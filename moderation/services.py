from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from reviews.models import Review

from .models import ModerationAction, ReviewReport

from django.contrib.auth import get_user_model


@transaction.atomic
def moderate_review(
    *,
    actor,
    review_id,
    decision,
    reason,
    expected_updated_at,
):
    if not actor.has_perm("moderation.moderate_reviews"):
        raise PermissionDenied

    if decision not in [
        Review.Status.APPROVED,
        Review.Status.REJECTED,
    ]:
        raise ValidationError("Choose approve or reject.")

    reason = reason.strip()

    if not 10 <= len(reason) <= 2000:
        raise ValidationError(
            "The decision reason must contain 10 to 2,000 characters."
        )

    review = get_object_or_404(
        Review.objects.select_for_update(),
        pk=review_id,
    )

    if review.author_id == actor.pk:
        raise PermissionDenied(
            "You cannot moderate your own review."
        )

    if expected_updated_at != review.updated_at:
        raise ValidationError(
            "This review changed after you opened it. "
            "Reload the page and review the latest content."
        )

    if review.status == decision:
        raise ValidationError(
            "This review already has the selected status."
        )

    if decision == Review.Status.APPROVED:
        if not review.product.is_active:
            raise ValidationError(
                "Reviews of inactive products cannot be approved."
            )

        if not review.author.is_active:
            raise ValidationError(
                "Reviews from inactive accounts cannot be approved."
            )

    previous_state = review.status

    review.status = decision
    review.save(update_fields=["status", "updated_at"])

    action = (
        ModerationAction.Action.APPROVE_REVIEW
        if decision == Review.Status.APPROVED
        else ModerationAction.Action.REJECT_REVIEW
    )

    ModerationAction.objects.create(
        actor=actor,
        action=action,
        review=review,
        reason=reason,
        previous_state=previous_state,
        new_state=decision,
    )

    return review

@transaction.atomic
def report_review(*, reporter, review_id, reason, details):
    if not reporter.is_authenticated or not reporter.is_active:
        raise PermissionDenied

    if reason not in ReviewReport.Reason.values:
        raise ValidationError("Choose a valid report reason.")

    details = details.strip()

    if len(details) > 2000:
        raise ValidationError(
            "Report details cannot exceed 2,000 characters."
        )

    review = get_object_or_404(
        Review.objects.select_for_update(),
        pk=review_id,
        status=Review.Status.APPROVED,
        product__is_active=True,
    )

    if review.author_id == reporter.pk:
        raise PermissionDenied("You cannot report your own review.")

    report, created = ReviewReport.objects.get_or_create(
        reporter=reporter,
        review=review,
        defaults={
            "reason": reason,
            "details": details,
        },
    )

    return report, created

@transaction.atomic
def decide_report(
    *,
    actor,
    report_id,
    decision,
    reason,
    expected_updated_at,
    expected_review_updated_at,
):
    if not actor.has_perm("moderation.manage_reports"):
        raise PermissionDenied

    if decision not in [
        ReviewReport.Status.RESOLVED,
        ReviewReport.Status.DISMISSED,
    ]:
        raise ValidationError("Choose resolved or dismissed.")

    reason = reason.strip()

    if not 10 <= len(reason) <= 2000:
        raise ValidationError(
            "The resolution note must contain 10 to 2,000 characters."
        )

    report = get_object_or_404(
        ReviewReport.objects.select_for_update(),
        pk=report_id,
    )

    review = get_object_or_404(
        Review.objects.select_for_update(),
        pk=report.review_id,
    )

    if actor.pk in [report.reporter_id, review.author_id]:
        raise PermissionDenied(
            "You cannot decide a report you submitted "
            "or a report about your own review."
        )

    if report.status != ReviewReport.Status.OPEN:
        raise ValidationError("This report has already been closed.")

    if (
        expected_updated_at != report.updated_at
        or expected_review_updated_at != review.updated_at
    ):
        raise ValidationError(
            "The report or review changed after you opened it. "
            "Reload the page before deciding."
        )

    previous_state = report.status

    report.status = decision
    report.resolved_by = actor
    report.resolved_at = timezone.now()
    report.resolution_note = reason
    report.save(
        update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "updated_at",
        ],
    )

    action = (
        ModerationAction.Action.RESOLVE_REPORT
        if decision == ReviewReport.Status.RESOLVED
        else ModerationAction.Action.DISMISS_REPORT
    )

    ModerationAction.objects.create(
        actor=actor,
        action=action,
        report=report,
        reason=reason,
        previous_state=previous_state,
        new_state=decision,
    )

    return report

@transaction.atomic
def change_account_state(
    *,
    actor,
    user_id,
    decision,
    reason,
    expected_session_version,
):
    if not actor.has_perm("moderation.suspend_users"):
        raise PermissionDenied

    if decision not in ["suspend", "restore"]:
        raise ValidationError("Choose suspend or restore.")

    reason = reason.strip()

    if not 10 <= len(reason) <= 2000:
        raise ValidationError(
            "The reason must contain 10 to 2,000 characters."
        )

    User = get_user_model()
    target = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
    )

    if target.pk == actor.pk:
        raise PermissionDenied(
            "You cannot suspend or restore your own account."
        )

    if target.is_staff or target.is_superuser:
        raise PermissionDenied(
            "Staff and superuser accounts are protected "
            "from this workflow."
        )

    if target.session_version != expected_session_version:
        raise ValidationError(
            "This account's state changed after you opened it. "
            "Reload the page before deciding."
        )

    desired_active = decision == "restore"

    if target.is_active == desired_active:
        raise ValidationError(
            "This account already has the selected state."
        )

    previous_state = "active" if target.is_active else "suspended"

    target.is_active = desired_active
    target.session_version += 1
    target.save(update_fields=["is_active", "session_version"])

    action = (
        ModerationAction.Action.RESTORE_USER
        if desired_active
        else ModerationAction.Action.SUSPEND_USER
    )

    ModerationAction.objects.create(
        actor=actor,
        action=action,
        target_user=target,
        reason=reason,
        previous_state=previous_state,
        new_state="active" if desired_active else "suspended",
    )

    return target