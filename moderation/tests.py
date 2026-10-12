from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from catalog.models import Category, Product
from reviews.models import Review

from .models import ModerationAction, ReviewReport

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from .services import (
    change_account_state,
    decide_report,
    moderate_review,
    report_review,
)

from django.test import Client

from django.contrib.auth.models import AnonymousUser, Group
from django.http import Http404

from django.db.models import Q


class ModerationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="model-author",
            email="model-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="model-reporter",
            email="model-reporter@example.com",
        )
        cls.other_reporter = User.objects.create_user(
            username="other-model-reporter",
            email="other-model-reporter@example.com",
        )
        cls.actor = User.objects.create_user(
            username="model-moderator",
            email="model-moderator@example.com",
        )
        cls.target = User.objects.create_user(
            username="model-target",
            email="model-target@example.com",
        )

        cls.category = Category.objects.create(
            name="Moderation Models",
            slug="moderation-models",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Moderation Model Product",
            slug="moderation-model-product",
        )
        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Review for moderation tests",
            body="Review content for moderation model testing.",
        )

    def create_report(self, **overrides):
        data = {
            "review": self.review,
            "reporter": self.reporter,
            "reason": ReviewReport.Reason.SPAM,
            "details": "Please investigate this review.",
        }
        data.update(overrides)
        return ReviewReport.objects.create(**data)

    def create_action(self, **overrides):
        data = {
            "actor": self.actor,
            "action": ModerationAction.Action.APPROVE_REVIEW,
            "review": self.review,
            "reason": "Reviewed and accepted this content.",
            "previous_state": "pending",
            "new_state": "approved",
        }
        data.update(overrides)
        return ModerationAction.objects.create(**data)

    def test_same_reporter_cannot_report_review_twice(self):
        self.create_report()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_report()

        self.assertEqual(ReviewReport.objects.count(), 1)

    def test_different_reporters_can_report_same_review(self):
        self.create_report()
        self.create_report(reporter=self.other_reporter)

        self.assertEqual(ReviewReport.objects.count(), 2)

    def test_invalid_report_reason_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_report(reason="invalid")

    def test_invalid_report_resolution_fields_are_rejected(self):
        now = timezone.now()
        invalid_cases = [
            {"status": "invalid"},
            {"status": "resolved"},
            {
                "status": "resolved",
                "resolved_by": self.actor,
            },
            {
                "status": "dismissed",
                "resolved_at": now,
            },
            {
                "status": "open",
                "resolved_by": self.actor,
            },
            {
                "status": "open",
                "resolved_at": now,
            },
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_report(**data)

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_closed_report_accepts_complete_resolution_metadata(self):
        report = self.create_report()

        for status in [
            ReviewReport.Status.RESOLVED,
            ReviewReport.Status.DISMISSED,
        ]:
            with self.subTest(status=status):
                report.status = status
                report.resolved_by = self.actor
                report.resolved_at = timezone.now()
                report.resolution_note = "Moderator reviewed the concern."
                report.save()

                report.refresh_from_db()
                self.assertEqual(report.status, status)
                self.assertEqual(report.resolved_by_id, self.actor.pk)
                self.assertIsNotNone(report.resolved_at)

    def test_all_action_types_accept_the_correct_target(self):
        report = self.create_report()

        cases = [
            {
                "action": ModerationAction.Action.APPROVE_REVIEW,
            },
            {
                "action": ModerationAction.Action.REJECT_REVIEW,
                "new_state": "rejected",
            },
            {
                "action": ModerationAction.Action.RESOLVE_REPORT,
                "review": None,
                "report": report,
                "previous_state": "open",
                "new_state": "resolved",
            },
            {
                "action": ModerationAction.Action.DISMISS_REPORT,
                "review": None,
                "report": report,
                "previous_state": "open",
                "new_state": "dismissed",
            },
            {
                "action": ModerationAction.Action.SUSPEND_USER,
                "review": None,
                "target_user": self.target,
                "previous_state": "active",
                "new_state": "suspended",
            },
            {
                "action": ModerationAction.Action.RESTORE_USER,
                "review": None,
                "target_user": self.target,
                "previous_state": "suspended",
                "new_state": "active",
            },
        ]

        for data in cases:
            with self.subTest(action=data["action"]):
                self.create_action(**data)

        self.assertEqual(ModerationAction.objects.count(), 6)

    def test_invalid_action_targets_are_rejected(self):
        report = self.create_report()

        invalid_cases = [
            {"review": None},
            {"report": report},
            {"target_user": self.target},
            {
                "action": ModerationAction.Action.RESOLVE_REPORT,
                "review": None,
            },
            {
                "action": ModerationAction.Action.DISMISS_REPORT,
            },
            {
                "action": ModerationAction.Action.SUSPEND_USER,
                "review": None,
            },
            {
                "action": ModerationAction.Action.RESTORE_USER,
                "review": None,
                "target_user": self.target,
                "report": report,
            },
            {"action": "invalid"},
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_action(**data)

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_action_requires_nonempty_reason(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_action(reason="")

    def test_report_protects_review_and_reporter_from_deletion(self):
        self.create_report()

        for record in [self.review, self.reporter]:
            with self.subTest(model=record.__class__.__name__):
                with self.assertRaises(ProtectedError):
                    record.delete()

    def test_audit_history_protects_actor_and_targets_from_deletion(self):
        self.create_action()

        report = self.create_report()
        self.create_action(
            action=ModerationAction.Action.RESOLVE_REPORT,
            review=None,
            report=report,
            previous_state="open",
            new_state="resolved",
        )
        self.create_action(
            action=ModerationAction.Action.SUSPEND_USER,
            review=None,
            target_user=self.target,
            previous_state="active",
            new_state="suspended",
        )

        for record in [self.actor, self.review, report, self.target]:
            with self.subTest(model=record.__class__.__name__, pk=record.pk):
                with self.assertRaises(ProtectedError):
                    record.delete()


class ModerationRoleTests(TestCase):
    def test_setup_roles_can_be_repeated_without_duplicates(self):
        call_command("setup_roles", verbosity=0)
        call_command("setup_roles", verbosity=0)

        self.assertEqual(
            Group.objects.filter(
                name__in=["Review Moderators", "Account Managers"],
            ).count(),
            2,
        )

    def test_roles_have_exactly_the_intended_permissions(self):
        call_command("setup_roles", verbosity=0)

        expected = {
            "Review Moderators": {
                "moderation.moderate_reviews",
                "moderation.manage_reports",
                "moderation.view_reviewreport",
                "moderation.view_moderationaction",
            },
            "Account Managers": {
                "moderation.suspend_users",
                "moderation.view_moderationaction",
            },
        }

        for name, permissions in expected.items():
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                actual = {
                    f"{permission.content_type.app_label}.{permission.codename}"
                    for permission in group.permissions.select_related(
                        "content_type",
                    )
                }
                self.assertEqual(actual, permissions)

    def test_role_membership_separates_moderation_and_account_access(self):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cases = [
            ("ordinary", None, False, False, False),
            ("review-moderator", "Review Moderators", True, True, False),
            ("account-manager", "Account Managers", False, False, True),
        ]

        for username, role, reviews, reports, accounts in cases:
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=username,
                    email=f"{username}@example.com",
                )

                if role:
                    user.groups.add(Group.objects.get(name=role))

                self.assertEqual(
                    user.has_perm("moderation.moderate_reviews"),
                    reviews,
                )
                self.assertEqual(
                    user.has_perm("moderation.manage_reports"),
                    reports,
                )
                self.assertEqual(
                    user.has_perm("moderation.suspend_users"),
                    accounts,
                )
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)

class ReviewModerationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.moderator = User.objects.create_user(
            username="service-moderator",
            email="service-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.author = User.objects.create_user(
            username="service-review-author",
            email="service-review-author@example.com",
        )
        cls.ordinary_user = User.objects.create_user(
            username="service-ordinary-user",
            email="service-ordinary-user@example.com",
        )

        cls.category = Category.objects.create(
            name="Service Moderation",
            slug="service-moderation",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Service Moderation Product",
            slug="service-moderation-product",
        )
        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Service moderation review",
            body="Content for testing review moderation services.",
        )

        cls.detail_url = reverse(
            "catalog:product_detail",
            kwargs={"slug": cls.product.slug},
        )

    def decide(self, **overrides):
        data = {
            "actor": self.moderator,
            "review_id": self.review.pk,
            "decision": Review.Status.APPROVED,
            "reason": "Reviewed the complete review content.",
            "expected_updated_at": self.review.updated_at,
        }
        data.update(overrides)
        return moderate_review(**data)

    def assert_no_decision_saved(self):
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.PENDING)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_approval_updates_review_and_records_audit(self):
        self.decide(reason="  Reviewed and approved this content.  ")

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.review_id, self.review.pk)
        self.assertEqual(
            action.action,
            ModerationAction.Action.APPROVE_REVIEW,
        )
        self.assertEqual(action.previous_state, "pending")
        self.assertEqual(action.new_state, "approved")
        self.assertEqual(
            action.reason,
            "Reviewed and approved this content.",
        )
        self.assertIsNone(action.report_id)
        self.assertIsNone(action.target_user_id)

        response = self.client.get(self.detail_url)
        self.assertContains(response, self.review.title)
        self.assertEqual(
            response.context["rating_summary"]["review_count"],
            1,
        )

    def test_rejection_removes_published_review_and_records_audit(self):
        self.review.status = Review.Status.APPROVED
        self.review.save(update_fields=["status", "updated_at"])

        self.decide(decision=Review.Status.REJECTED)

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.REJECTED)

        action = ModerationAction.objects.get()
        self.assertEqual(
            action.action,
            ModerationAction.Action.REJECT_REVIEW,
        )
        self.assertEqual(action.previous_state, "approved")
        self.assertEqual(action.new_state, "rejected")

        response = self.client.get(self.detail_url)
        self.assertNotContains(response, self.review.title)
        self.assertEqual(
            response.context["rating_summary"]["review_count"],
            0,
        )

    def test_user_without_permission_cannot_decide(self):
        with self.assertRaises(PermissionDenied):
            self.decide(actor=self.ordinary_user)

        self.assert_no_decision_saved()

    def test_author_cannot_moderate_own_review_even_as_superuser(self):
        self.author.is_superuser = True
        self.author.save(update_fields=["is_superuser"])

        with self.assertRaises(PermissionDenied):
            self.decide(actor=self.author)

        self.assert_no_decision_saved()

    def test_invalid_decisions_and_reasons_are_rejected(self):
        invalid_cases = [
            {"decision": Review.Status.PENDING},
            {"decision": "invalid"},
            {"reason": "short"},
            {"reason": " " * 20},
            {"reason": "x" * 2001},
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    self.decide(**data)

                self.assert_no_decision_saved()

    def test_outdated_decision_cannot_approve_changed_content(self):
        opened_at = self.review.updated_at

        Review.objects.filter(pk=self.review.pk).update(
            title="Content edited after moderator opened the page",
            updated_at=opened_at + timedelta(seconds=1),
        )

        with self.assertRaises(ValidationError):
            self.decide(expected_updated_at=opened_at)

        self.assert_no_decision_saved()
        self.assertEqual(
            self.review.title,
            "Content edited after moderator opened the page",
        )

    def test_repeated_same_decision_does_not_create_another_audit(self):
        self.decide()
        self.review.refresh_from_db()
        decided_at = self.review.updated_at

        with self.assertRaises(ValidationError):
            self.decide()

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)
        self.assertEqual(self.review.updated_at, decided_at)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_approval_is_blocked_for_inactive_product_or_author(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.decide()

        self.assert_no_decision_saved()

        self.product.is_active = True
        self.product.save(update_fields=["is_active"])
        self.author.is_active = False
        self.author.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.decide()

        self.assert_no_decision_saved()

    def test_rejection_is_allowed_for_inactive_product_and_author(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        self.author.is_active = False
        self.author.save(update_fields=["is_active"])

        self.decide(decision=Review.Status.REJECTED)

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.REJECTED)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_audit_failure_rolls_back_review_change(self):
        original_updated_at = self.review.updated_at

        with patch(
            "moderation.services.ModerationAction.objects.create",
            side_effect=IntegrityError("Simulated audit write failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.decide()

        self.assert_no_decision_saved()
        self.assertEqual(self.review.updated_at, original_updated_at)

class ReviewModerationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.moderator = User.objects.create_user(
            username="view-moderator",
            email="view-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.ordinary_user = User.objects.create_user(
            username="view-ordinary",
            email="view-ordinary@example.com",
        )
        cls.account_manager = User.objects.create_user(
            username="view-account-manager",
            email="view-account-manager@example.com",
        )
        cls.account_manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

        cls.category = Category.objects.create(
            name="Moderation Views",
            slug="moderation-views",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Moderation View Product",
            slug="moderation-view-product",
        )

        cls.reviews = []

        for number, status in enumerate([
            Review.Status.PENDING,
            Review.Status.APPROVED,
            Review.Status.REJECTED,
        ]):
            author = User.objects.create_user(
                username=f"moderation-view-author-{number}",
                email=f"moderation-view-author-{number}@example.com",
            )
            review = Review.objects.create(
                author=author,
                product=cls.product,
                rating=4,
                title=f"Moderation view review {number}",
                body="Complete review content for moderation view tests.",
                status=status,
            )
            cls.reviews.append(review)

        cls.pending = cls.reviews[0]
        cls.own_review = Review.objects.create(
            author=cls.moderator,
            product=cls.product,
            rating=3,
            title="Moderator's own private review",
            body="A moderator must not decide their own review.",
        )

        cls.queue_url = reverse("moderation:review_queue")
        cls.decision_url = reverse(
            "moderation:review_decision",
            kwargs={"pk": cls.pending.pk},
        )

    def setUp(self):
        self.login_as(self.moderator)

    def login_as(self, user):
        self.client.force_login(
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "decision": Review.Status.APPROVED,
            "reason": "Reviewed and accepted the complete content.",
            "expected_updated_at": self.pending.updated_at.isoformat(),
        }
        data.update(overrides)
        return data

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        requests = [
            ("get", self.queue_url),
            ("get", self.decision_url),
            ("post", self.decision_url),
        ]

        for method, url in requests:
            with self.subTest(method=method, url=url):
                if method == "post":
                    response = self.client.post(url, self.valid_data())
                else:
                    response = self.client.get(url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_ordinary_users_and_account_managers_are_denied(self):
        for user in [self.ordinary_user, self.account_manager]:
            with self.subTest(user=user.username):
                self.login_as(user)

                self.assertEqual(
                    self.client.get(self.queue_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.get(self.decision_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        self.decision_url,
                        self.valid_data(),
                    ).status_code,
                    403,
                )

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.Status.PENDING)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_nonstaff_moderator_can_open_pages_without_writing(self):
        self.assertFalse(self.moderator.is_staff)

        queue = self.client.get(self.queue_url)
        decision = self.client.get(self.decision_url)

        self.assertEqual(queue.status_code, 200)
        self.assertEqual(decision.status_code, 200)
        self.assertTemplateUsed(
            decision,
            "moderation/review_decision.html",
        )
        self.assertEqual(
            decision.context["form"].initial["expected_updated_at"],
            self.pending.updated_at.isoformat(),
        )
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_default_queue_contains_pending_reviews_excluding_own(self):
        response = self.client.get(self.queue_url)

        self.assertEqual(
            [review.pk for review in response.context["page_obj"]],
            [self.pending.pk],
        )
        self.assertNotContains(response, self.own_review.title)

    def test_status_filters_and_invalid_status(self):
        expected_counts = {
            "pending": 1,
            "approved": 1,
            "rejected": 1,
            "all": 3,
        }

        for status, count in expected_counts.items():
            with self.subTest(status=status):
                response = self.client.get(
                    self.queue_url,
                    {"status": status},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["page_obj"].paginator.count,
                    count,
                )

        response = self.client.get(
            self.queue_url,
            {"status": "invalid"},
        )
        self.assertEqual(response.status_code, 404)

    def test_queue_pagination_preserves_status_and_has_no_duplicates(self):
        User = get_user_model()

        for number in range(21):
            author = User.objects.create_user(
                username=f"queue-paging-author-{number}",
                email=f"queue-paging-author-{number}@example.com",
            )
            Review.objects.create(
                author=author,
                product=self.product,
                rating=4,
                title=f"Queue paging review {number}",
                body="Additional content for moderation queue pagination.",
            )

        first = self.client.get(
            self.queue_url,
            {"status": "pending"},
        )
        second = self.client.get(
            self.queue_url,
            {"status": "pending", "page": 2},
        )

        first_ids = [
            review.pk for review in first.context["page_obj"]
        ]
        second_ids = [
            review.pk for review in second.context["page_obj"]
        ]

        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 2)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))
        self.assertNotIn(self.own_review.pk, first_ids + second_ids)

        expected_ids = list(
            Review.objects.filter(status=Review.Status.PENDING)
            .exclude(author=self.moderator)
            .order_by("created_at", "id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)
        self.assertContains(
            first,
            "?status=pending&amp;page=2",
        )

    def test_own_review_is_forbidden_and_missing_review_returns_404(self):
        own_url = reverse(
            "moderation:review_decision",
            kwargs={"pk": self.own_review.pk},
        )
        missing_url = reverse(
            "moderation:review_decision",
            kwargs={"pk": self.own_review.pk + 10000},
        )

        for url, expected_status in [
            (own_url, 403),
            (missing_url, 404),
        ]:
            for method in ["get", "post"]:
                with self.subTest(url=url, method=method):
                    if method == "post":
                        response = self.client.post(url, self.valid_data())
                    else:
                        response = self.client.get(url)

                    self.assertEqual(
                        response.status_code,
                        expected_status,
                    )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_valid_post_uses_signed_in_actor_and_url_review(self):
        response = self.client.post(
            self.decision_url,
            self.valid_data(
                actor=str(self.ordinary_user.pk),
                review=str(self.reviews[1].pk),
            ),
        )

        self.assertRedirects(response, self.queue_url)

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.Status.APPROVED)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.review_id, self.pending.pk)

    def test_invalid_form_does_not_save_decision(self):
        invalid_cases = [
            ("decision", "pending"),
            ("reason", "short"),
            ("expected_updated_at", ""),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                response = self.client.post(
                    self.decision_url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.Status.PENDING)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_outdated_post_shows_error_without_approving(self):
        opened_at = self.pending.updated_at

        Review.objects.filter(pk=self.pending.pk).update(
            title="Review edited after opening moderation page",
            updated_at=opened_at + timedelta(seconds=1),
        )

        response = self.client.post(
            self.decision_url,
            self.valid_data(
                expected_updated_at=opened_at.isoformat(),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This review changed after you opened it.",
        )

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.Status.PENDING)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.moderator,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.decision_url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ModerationAction.objects.count(), 0)

        client.get(self.decision_url)
        token = client.cookies["csrftoken"].value

        response = client.post(
            self.decision_url,
            self.valid_data(csrfmiddlewaretoken=token),
        )

        self.assertRedirects(response, self.queue_url)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_unsupported_methods_are_rejected(self):
        self.assertEqual(
            self.client.post(self.queue_url).status_code,
            405,
        )

        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.decision_url,
                )
                self.assertEqual(response.status_code, 405)

        self.assertEqual(ModerationAction.objects.count(), 0)

class ReportCreationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="report-service-author",
            email="report-service-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="report-service-reporter",
            email="report-service-reporter@example.com",
        )
        cls.other_reporter = User.objects.create_user(
            username="other-report-service-reporter",
            email="other-report-service-reporter@example.com",
        )

        cls.category = Category.objects.create(
            name="Report Services",
            slug="report-services",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Report Service Product",
            slug="report-service-product",
        )
        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Public review for report testing",
            body="Public content for report creation service tests.",
            status=Review.Status.APPROVED,
        )

    def submit(self, **overrides):
        data = {
            "reporter": self.reporter,
            "review_id": self.review.pk,
            "reason": ReviewReport.Reason.SPAM,
            "details": "Please investigate this content.",
        }
        data.update(overrides)
        return report_review(**data)

    def test_valid_report_is_open_and_preserves_public_review(self):
        report, created = self.submit(
            details="  Please investigate this content.  ",
        )

        self.assertTrue(created)
        self.assertEqual(report.reporter_id, self.reporter.pk)
        self.assertEqual(report.review_id, self.review.pk)
        self.assertEqual(report.reason, ReviewReport.Reason.SPAM)
        self.assertEqual(report.details, "Please investigate this content.")
        self.assertEqual(report.status, ReviewReport.Status.OPEN)
        self.assertIsNone(report.resolved_by_id)
        self.assertIsNone(report.resolved_at)
        self.assertEqual(ModerationAction.objects.count(), 0)

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)

        url = reverse(
            "catalog:product_detail",
            kwargs={"slug": self.product.slug},
        )
        response = self.client.get(url)

        self.assertContains(response, self.review.title)
        self.assertEqual(
            response.context["rating_summary"]["review_count"],
            1,
        )

    def test_duplicate_report_preserves_original_details(self):
        original, _ = self.submit()

        duplicate, created = self.submit(
            reason=ReviewReport.Reason.ABUSE,
            details="Different details that must not overwrite the original.",
        )

        self.assertFalse(created)
        self.assertEqual(duplicate.pk, original.pk)
        self.assertEqual(ReviewReport.objects.count(), 1)

        original.refresh_from_db()
        self.assertEqual(original.reason, ReviewReport.Reason.SPAM)
        self.assertEqual(
            original.details,
            "Please investigate this content.",
        )

    def test_closed_report_is_not_reopened_by_duplicate_submission(self):
        original, _ = self.submit()

        original.status = ReviewReport.Status.RESOLVED
        original.resolved_by = self.other_reporter
        original.resolved_at = timezone.now()
        original.resolution_note = "Concern previously addressed."
        original.save()

        duplicate, created = self.submit()

        self.assertFalse(created)
        self.assertEqual(duplicate.pk, original.pk)

        original.refresh_from_db()
        self.assertEqual(original.status, ReviewReport.Status.RESOLVED)
        self.assertEqual(
            original.resolution_note,
            "Concern previously addressed.",
        )
        self.assertEqual(ReviewReport.objects.count(), 1)

    def test_different_users_can_report_same_review(self):
        self.submit()
        _, created = self.submit(reporter=self.other_reporter)

        self.assertTrue(created)
        self.assertEqual(ReviewReport.objects.count(), 2)

    def test_author_cannot_report_own_review(self):
        with self.assertRaises(PermissionDenied):
            self.submit(reporter=self.author)

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_anonymous_and_inactive_users_cannot_report(self):
        with self.assertRaises(PermissionDenied):
            self.submit(reporter=AnonymousUser())

        self.reporter.is_active = False
        self.reporter.save(update_fields=["is_active"])

        with self.assertRaises(PermissionDenied):
            self.submit()

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_nonpublic_and_missing_reviews_cannot_be_reported(self):
        for status in [
            Review.Status.PENDING,
            Review.Status.REJECTED,
        ]:
            with self.subTest(status=status):
                self.review.status = status
                self.review.save(update_fields=["status"])

                with self.assertRaises(Http404):
                    self.submit()

        self.review.status = Review.Status.APPROVED
        self.review.save(update_fields=["status"])

        self.product.is_active = False
        self.product.save(update_fields=["is_active"])

        with self.assertRaises(Http404):
            self.submit()

        with self.assertRaises(Http404):
            self.submit(review_id=self.review.pk + 10000)

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_invalid_reason_and_oversized_details_are_rejected(self):
        invalid_cases = [
            {"reason": "invalid"},
            {"details": "x" * 2001},
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    self.submit(**data)

        self.assertEqual(ReviewReport.objects.count(), 0)

class ReportDecisionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.moderator = User.objects.create_user(
            username="resolution-moderator",
            email="resolution-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.author = User.objects.create_user(
            username="resolution-author",
            email="resolution-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="resolution-reporter",
            email="resolution-reporter@example.com",
        )
        cls.ordinary_user = User.objects.create_user(
            username="resolution-ordinary",
            email="resolution-ordinary@example.com",
        )
        cls.account_manager = User.objects.create_user(
            username="resolution-account-manager",
            email="resolution-account-manager@example.com",
        )
        cls.account_manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

        cls.category = Category.objects.create(
            name="Report Decisions",
            slug="report-decisions",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Report Decision Product",
            slug="report-decision-product",
        )
        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Reported public review",
            body="Public review content for report decision tests.",
            status=Review.Status.APPROVED,
        )
        cls.report = ReviewReport.objects.create(
            review=cls.review,
            reporter=cls.reporter,
            reason=ReviewReport.Reason.SPAM,
            details="Please investigate the reported content.",
        )

    def decide(self, **overrides):
        data = {
            "actor": self.moderator,
            "report_id": self.report.pk,
            "decision": ReviewReport.Status.RESOLVED,
            "reason": "Investigated and addressed the reported concern.",
            "expected_updated_at": self.report.updated_at,
            "expected_review_updated_at": self.review.updated_at,
        }
        data.update(overrides)
        return decide_report(**data)

    def assert_report_still_open(self):
        self.report.refresh_from_db()

        self.assertEqual(self.report.status, ReviewReport.Status.OPEN)
        self.assertIsNone(self.report.resolved_by_id)
        self.assertIsNone(self.report.resolved_at)
        self.assertEqual(self.report.resolution_note, "")
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_resolution_records_metadata_and_audit(self):
        self.decide(
            reason="  Investigated and addressed the reported concern.  ",
        )

        self.report.refresh_from_db()
        self.assertEqual(
            self.report.status,
            ReviewReport.Status.RESOLVED,
        )
        self.assertEqual(
            self.report.resolved_by_id,
            self.moderator.pk,
        )
        self.assertIsNotNone(self.report.resolved_at)
        self.assertEqual(
            self.report.resolution_note,
            "Investigated and addressed the reported concern.",
        )

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.report_id, self.report.pk)
        self.assertEqual(
            action.action,
            ModerationAction.Action.RESOLVE_REPORT,
        )
        self.assertEqual(action.previous_state, "open")
        self.assertEqual(action.new_state, "resolved")
        self.assertEqual(action.reason, self.report.resolution_note)
        self.assertIsNone(action.review_id)
        self.assertIsNone(action.target_user_id)

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)

    def test_dismissal_records_metadata_without_changing_review(self):
        self.decide(
            decision=ReviewReport.Status.DISMISSED,
            reason="Investigated and found no action was needed.",
        )

        self.report.refresh_from_db()
        self.assertEqual(
            self.report.status,
            ReviewReport.Status.DISMISSED,
        )
        self.assertEqual(
            self.report.resolved_by_id,
            self.moderator.pk,
        )
        self.assertIsNotNone(self.report.resolved_at)

        action = ModerationAction.objects.get()
        self.assertEqual(
            action.action,
            ModerationAction.Action.DISMISS_REPORT,
        )
        self.assertEqual(action.previous_state, "open")
        self.assertEqual(action.new_state, "dismissed")

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)

    def test_users_without_report_permission_are_denied(self):
        for actor in [self.ordinary_user, self.account_manager]:
            with self.subTest(actor=actor.username):
                with self.assertRaises(PermissionDenied):
                    self.decide(actor=actor)

                self.assert_report_still_open()

    def test_reporter_and_review_author_cannot_decide_even_as_superusers(self):
        for actor in [self.reporter, self.author]:
            with self.subTest(actor=actor.username):
                actor.is_superuser = True
                actor.save(update_fields=["is_superuser"])

                with self.assertRaises(PermissionDenied):
                    self.decide(actor=actor)

                self.assert_report_still_open()

    def test_invalid_decisions_and_notes_are_rejected(self):
        invalid_cases = [
            {"decision": ReviewReport.Status.OPEN},
            {"decision": "invalid"},
            {"reason": "short"},
            {"reason": " " * 20},
            {"reason": "x" * 2001},
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    self.decide(**data)

                self.assert_report_still_open()

    def test_closed_report_cannot_be_decided_again(self):
        self.decide()
        self.report.refresh_from_db()
        original_resolved_at = self.report.resolved_at
        original_note = self.report.resolution_note

        with self.assertRaises(ValidationError):
            self.decide(decision=ReviewReport.Status.DISMISSED)

        self.report.refresh_from_db()
        self.assertEqual(
            self.report.status,
            ReviewReport.Status.RESOLVED,
        )
        self.assertEqual(
            self.report.resolved_at,
            original_resolved_at,
        )
        self.assertEqual(self.report.resolution_note, original_note)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_changed_report_rejects_outdated_decision(self):
        opened_at = self.report.updated_at

        ReviewReport.objects.filter(pk=self.report.pk).update(
            details="Report details changed after opening.",
            updated_at=opened_at + timedelta(seconds=1),
        )

        with self.assertRaises(ValidationError):
            self.decide(expected_updated_at=opened_at)

        self.assert_report_still_open()
        self.assertEqual(
            self.report.details,
            "Report details changed after opening.",
        )

    def test_changed_review_rejects_outdated_report_decision(self):
        opened_at = self.review.updated_at

        Review.objects.filter(pk=self.review.pk).update(
            body="Review content changed after the report was opened.",
            status=Review.Status.PENDING,
            updated_at=opened_at + timedelta(seconds=1),
        )

        with self.assertRaises(ValidationError):
            self.decide(expected_review_updated_at=opened_at)

        self.assert_report_still_open()

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.PENDING)

    def test_audit_failure_rolls_back_report_resolution(self):
        original_updated_at = self.report.updated_at

        with patch(
            "moderation.services.ModerationAction.objects.create",
            side_effect=IntegrityError("Simulated audit write failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.decide()

        self.assert_report_still_open()
        self.assertEqual(
            self.report.updated_at,
            original_updated_at,
        )

    def test_missing_report_returns_404(self):
        with self.assertRaises(Http404):
            self.decide(report_id=self.report.pk + 10000)

        self.assert_report_still_open()

class ReportCreationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="report-page-author",
            email="report-page-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="report-page-reporter",
            email="report-page-reporter@example.com",
        )

        cls.category = Category.objects.create(
            name="Report Pages",
            slug="report-pages",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Report Page Product",
            slug="report-page-product",
        )
        cls.other_product = Product.objects.create(
            category=cls.category,
            name="Other Report Page Product",
            slug="other-report-page-product",
        )

        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Review for report page tests",
            body="Public review content for report submission testing.",
            status=Review.Status.APPROVED,
        )
        cls.other_review = Review.objects.create(
            author=cls.author,
            product=cls.other_product,
            rating=3,
            title="Another public review",
            body="Another public review for testing submitted identifiers.",
            status=Review.Status.APPROVED,
        )

        cls.url = reverse(
            "moderation:report_create",
            kwargs={"pk": cls.review.pk},
        )
        cls.detail_url = reverse(
            "catalog:product_detail",
            kwargs={"slug": cls.product.slug},
        )

    def setUp(self):
        self.client.force_login(
            self.reporter,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "reason": ReviewReport.Reason.SPAM,
            "details": "Please investigate the reported content.",
        }
        data.update(overrides)
        return data

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        for method in ["get", "post"]:
            with self.subTest(method=method):
                if method == "post":
                    response = self.client.post(self.url, self.valid_data())
                else:
                    response = self.client.get(self.url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={self.url}",
                )

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_regular_user_can_open_form_without_creating_report(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "moderation/report_form.html")
        self.assertEqual(response.context["review"].pk, self.review.pk)
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_submission_ignores_reporter_review_and_resolution_tampering(self):
        response = self.client.post(
            self.url,
            self.valid_data(
                reporter=str(self.author.pk),
                review=str(self.other_review.pk),
                status=ReviewReport.Status.RESOLVED,
                resolved_by=str(self.author.pk),
                resolution_note="Attempted forged resolution.",
            ),
        )

        self.assertRedirects(response, self.detail_url)

        report = ReviewReport.objects.get()
        self.assertEqual(report.reporter_id, self.reporter.pk)
        self.assertEqual(report.review_id, self.review.pk)
        self.assertEqual(report.status, ReviewReport.Status.OPEN)
        self.assertIsNone(report.resolved_by_id)
        self.assertIsNone(report.resolved_at)
        self.assertEqual(report.resolution_note, "")

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_duplicate_get_and_post_preserve_original_report(self):
        report = ReviewReport.objects.create(
            reporter=self.reporter,
            review=self.review,
            reason=ReviewReport.Reason.SPAM,
            details="Original report details.",
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                if method == "post":
                    response = self.client.post(
                        self.url,
                        self.valid_data(
                            reason=ReviewReport.Reason.ABUSE,
                            details="Attempted replacement details.",
                        ),
                    )
                else:
                    response = self.client.get(self.url)

                self.assertRedirects(response, self.detail_url)

        report.refresh_from_db()
        self.assertEqual(report.reason, ReviewReport.Reason.SPAM)
        self.assertEqual(report.details, "Original report details.")
        self.assertEqual(ReviewReport.objects.count(), 1)

    def test_author_cannot_open_or_submit_report_for_own_review(self):
        self.client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(self.url, self.valid_data()).status_code,
            403,
        )
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_nonpublic_and_missing_reviews_return_404(self):
        for status in [
            Review.Status.PENDING,
            Review.Status.REJECTED,
        ]:
            self.review.status = status
            self.review.save(update_fields=["status"])

            with self.subTest(status=status):
                self.assertEqual(
                    self.client.get(self.url).status_code,
                    404,
                )
                self.assertEqual(
                    self.client.post(
                        self.url,
                        self.valid_data(),
                    ).status_code,
                    404,
                )

        self.review.status = Review.Status.APPROVED
        self.review.save(update_fields=["status"])
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.post(self.url, self.valid_data()).status_code,
            404,
        )

        missing_url = reverse(
            "moderation:report_create",
            kwargs={"pk": self.other_review.pk + 10000},
        )
        self.assertEqual(self.client.get(missing_url).status_code, 404)
        self.assertEqual(
            self.client.post(missing_url, self.valid_data()).status_code,
            404,
        )
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_invalid_form_does_not_create_report(self):
        invalid_cases = [
            ("reason", "invalid"),
            ("details", "x" * 2001),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                response = self.client.post(
                    self.url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.reporter,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ReviewReport.objects.count(), 0)

        client.get(self.url)
        token = client.cookies["csrftoken"].value

        response = client.post(
            self.url,
            self.valid_data(csrfmiddlewaretoken=token),
        )

        self.assertRedirects(response, self.detail_url)
        self.assertEqual(ReviewReport.objects.count(), 1)

    def test_unsupported_methods_are_rejected(self):
        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)
                self.assertEqual(response.status_code, 405)

        self.assertEqual(ReviewReport.objects.count(), 0)

class ReportModerationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.moderator = User.objects.create_user(
            username="report-view-moderator",
            email="report-view-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.author = User.objects.create_user(
            username="report-view-author",
            email="report-view-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="report-view-reporter",
            email="report-view-reporter@example.com",
        )
        cls.ordinary_user = User.objects.create_user(
            username="report-view-ordinary",
            email="report-view-ordinary@example.com",
        )
        cls.account_manager = User.objects.create_user(
            username="report-view-manager",
            email="report-view-manager@example.com",
        )
        cls.account_manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

        cls.category = Category.objects.create(
            name="Report Moderation Views",
            slug="report-moderation-views",
        )

        cls.report = cls.make_report(0)
        cls.closed_report = cls.make_report(
            1,
            status=ReviewReport.Status.RESOLVED,
        )
        cls.dismissed_report = cls.make_report(
            2,
            status=ReviewReport.Status.DISMISSED,
        )

        cls.own_report = ReviewReport.objects.create(
            review=cls.report.review,
            reporter=cls.moderator,
            reason=ReviewReport.Reason.SPAM,
            details="Report submitted by this moderator.",
        )
        cls.own_review_report = cls.make_report(
            "own-review",
            author=cls.moderator,
        )

        cls.queue_url = reverse("moderation:report_queue")
        cls.decision_url = reverse(
            "moderation:report_decision",
            kwargs={"pk": cls.report.pk},
        )

    @classmethod
    def make_report(cls, number, status="open", author=None):
        product = Product.objects.create(
            category=cls.category,
            name=f"Report Queue Product {number}",
            slug=f"report-queue-product-{number}",
        )
        review = Review.objects.create(
            author=author or cls.author,
            product=product,
            rating=4,
            title=f"Reported queue review {number}",
            body="Review content for report moderation page testing.",
            status=Review.Status.APPROVED,
        )

        data = {
            "review": review,
            "reporter": cls.reporter,
            "reason": ReviewReport.Reason.SPAM,
            "details": f"Private report details for report {number}.",
            "status": status,
        }

        if status != ReviewReport.Status.OPEN:
            data.update(
                resolved_by=cls.moderator,
                resolved_at=timezone.now(),
                resolution_note=f"Recorded outcome for report {number}.",
            )

        return ReviewReport.objects.create(**data)

    def setUp(self):
        self.login_as(self.moderator)

    def login_as(self, user):
        self.client.force_login(
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "decision": ReviewReport.Status.RESOLVED,
            "reason": "Investigated and addressed this concern.",
            "expected_updated_at": self.report.updated_at.isoformat(),
            "expected_review_updated_at": (
                self.report.review.updated_at.isoformat()
            ),
        }
        data.update(overrides)
        return data

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        for method, url in [
            ("get", self.queue_url),
            ("get", self.decision_url),
            ("post", self.decision_url),
        ]:
            with self.subTest(method=method, url=url):
                if method == "post":
                    response = self.client.post(url, self.valid_data())
                else:
                    response = self.client.get(url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                )

    def test_users_without_report_permission_are_denied(self):
        for user in [self.ordinary_user, self.account_manager]:
            with self.subTest(user=user.username):
                self.login_as(user)

                self.assertEqual(
                    self.client.get(self.queue_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.get(self.decision_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        self.decision_url,
                        self.valid_data(),
                    ).status_code,
                    403,
                )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_queue_filters_status_and_excludes_conflicts(self):
        for status, expected_count in [
            ("open", 1),
            ("resolved", 1),
            ("dismissed", 1),
            ("all", 3),
        ]:
            with self.subTest(status=status):
                response = self.client.get(
                    self.queue_url,
                    {"status": status},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["page_obj"].paginator.count,
                    expected_count,
                )

                ids = {
                    report.pk for report in response.context["page_obj"]
                }
                self.assertNotIn(self.own_report.pk, ids)
                self.assertNotIn(self.own_review_report.pk, ids)

        response = self.client.get(
            self.queue_url,
            {"status": "invalid"},
        )
        self.assertEqual(response.status_code, 404)

    def test_queue_pagination_preserves_filter_without_duplicates(self):
        for number in range(21):
            self.make_report(f"page-{number}")

        first = self.client.get(self.queue_url, {"status": "open"})
        second = self.client.get(
            self.queue_url,
            {"status": "open", "page": 2},
        )

        first_ids = [
            report.pk for report in first.context["page_obj"]
        ]
        second_ids = [
            report.pk for report in second.context["page_obj"]
        ]

        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 2)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        expected_ids = list(
            ReviewReport.objects.filter(status=ReviewReport.Status.OPEN)
            .exclude(
                Q(reporter=self.moderator)
                | Q(review__author=self.moderator)
            )
            .order_by("created_at", "id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)
        self.assertContains(first, "?status=open&amp;page=2")

    def test_get_shows_report_without_saving_outcome(self):
        response = self.client.get(self.decision_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "moderation/report_decision.html",
        )
        self.assertContains(response, self.report.details)
        self.assertEqual(
            response.context["form"].initial["expected_updated_at"],
            self.report.updated_at.isoformat(),
        )
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_conflicting_reports_are_forbidden_and_missing_report_is_404(self):
        cases = [
            (self.own_report.pk, 403),
            (self.own_review_report.pk, 403),
            (self.own_review_report.pk + 10000, 404),
        ]

        for pk, expected_status in cases:
            url = reverse(
                "moderation:report_decision",
                kwargs={"pk": pk},
            )

            for method in ["get", "post"]:
                with self.subTest(pk=pk, method=method):
                    if method == "post":
                        response = self.client.post(url, self.valid_data())
                    else:
                        response = self.client.get(url)

                    self.assertEqual(
                        response.status_code,
                        expected_status,
                    )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_post_uses_signed_in_actor_and_url_report(self):
        response = self.client.post(
            self.decision_url,
            self.valid_data(
                actor=str(self.ordinary_user.pk),
                report=str(self.closed_report.pk),
                resolved_by=str(self.ordinary_user.pk),
            ),
        )

        self.assertRedirects(response, self.queue_url)

        self.report.refresh_from_db()
        self.assertEqual(
            self.report.status,
            ReviewReport.Status.RESOLVED,
        )
        self.assertEqual(
            self.report.resolved_by_id,
            self.moderator.pk,
        )

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.report_id, self.report.pk)

        self.report.review.refresh_from_db()
        self.assertEqual(
            self.report.review.status,
            Review.Status.APPROVED,
        )

    def test_invalid_and_outdated_posts_do_not_close_report(self):
        for field, value in [
            ("decision", "open"),
            ("reason", "short"),
            ("expected_updated_at", ""),
            ("expected_review_updated_at", ""),
        ]:
            with self.subTest(field=field):
                response = self.client.post(
                    self.decision_url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

        opened_at = self.report.updated_at
        ReviewReport.objects.filter(pk=self.report.pk).update(
            updated_at=opened_at + timedelta(seconds=1),
        )

        response = self.client.post(
            self.decision_url,
            self.valid_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "The report or review changed after you opened it.",
        )

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReviewReport.Status.OPEN)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.moderator,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.decision_url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ModerationAction.objects.count(), 0)

        client.get(self.decision_url)
        token = client.cookies["csrftoken"].value

        response = client.post(
            self.decision_url,
            self.valid_data(csrfmiddlewaretoken=token),
        )

        self.assertRedirects(response, self.queue_url)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_closed_report_displays_outcome_and_cannot_be_changed(self):
        url = reverse(
            "moderation:report_decision",
            kwargs={"pk": self.closed_report.pk},
        )

        response = self.client.get(url)

        self.assertContains(
            response,
            self.closed_report.resolution_note,
        )
        self.assertNotContains(response, "Save report outcome")

        response = self.client.post(url, self.valid_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This report has already been closed.",
        )
        self.closed_report.refresh_from_db()
        self.assertEqual(
            self.closed_report.status,
            ReviewReport.Status.RESOLVED,
        )
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_unsupported_methods_are_rejected(self):
        self.assertEqual(
            self.client.post(self.queue_url).status_code,
            405,
        )

        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.decision_url,
                )
                self.assertEqual(response.status_code, 405)

class AccountStateServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.manager = User.objects.create_user(
            username="state-manager",
            email="state-manager@example.com",
        )
        cls.manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

        cls.moderator = User.objects.create_user(
            username="state-review-moderator",
            email="state-review-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.ordinary_user = User.objects.create_user(
            username="state-ordinary",
            email="state-ordinary@example.com",
        )
        cls.staff = User.objects.create_user(
            username="state-staff",
            email="state-staff@example.com",
            is_staff=True,
        )
        cls.superuser = User.objects.create_user(
            username="state-superuser",
            email="state-superuser@example.com",
            is_superuser=True,
        )

        cls.password = "Forest!River82Cabin6"
        cls.target = User.objects.create_user(
            username="state-target",
            email="state-target@example.com",
            password=cls.password,
        )

    def change(self, **overrides):
        data = {
            "actor": self.manager,
            "user_id": self.target.pk,
            "decision": "suspend",
            "reason": "Account suspended after investigating the concern.",
            "expected_session_version": self.target.session_version,
        }
        data.update(overrides)
        return change_account_state(**data)

    def assert_target_unchanged(self):
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.target.session_version, 0)
        self.assertTrue(self.target.check_password(self.password))
        self.assertEqual(ModerationAction.objects.count(), 0)

    def sign_in_target(self, client):
        response = client.post(
            reverse("accounts:login"),
            {
                "username": self.target.username,
                "password": self.password,
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            client.session["_auth_user_id"],
            str(self.target.pk),
        )

    def assert_profile_requires_login(self, client):
        url = reverse("accounts:profile")
        response = client.get(url)

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={url}",
        )

    def test_suspension_records_audit_and_preserves_password(self):
        original_password_hash = self.target.password

        self.change(reason="  Investigated and suspended this account.  ")

        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(self.target.session_version, 1)
        self.assertEqual(self.target.password, original_password_hash)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.manager.pk)
        self.assertEqual(action.target_user_id, self.target.pk)
        self.assertEqual(
            action.action,
            ModerationAction.Action.SUSPEND_USER,
        )
        self.assertEqual(action.previous_state, "active")
        self.assertEqual(action.new_state, "suspended")
        self.assertEqual(
            action.reason,
            "Investigated and suspended this account.",
        )
        self.assertIsNone(action.review_id)
        self.assertIsNone(action.report_id)

    def test_restoration_advances_version_and_records_audit(self):
        self.change()
        self.target.refresh_from_db()

        self.change(
            decision="restore",
            reason="Account restored after reviewing the situation.",
        )

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.target.session_version, 2)
        self.assertTrue(self.target.check_password(self.password))

        action = ModerationAction.objects.get(
            action=ModerationAction.Action.RESTORE_USER,
        )
        self.assertEqual(action.target_user_id, self.target.pk)
        self.assertEqual(action.previous_state, "suspended")
        self.assertEqual(action.new_state, "active")
        self.assertEqual(ModerationAction.objects.count(), 2)

    def test_ordinary_users_and_review_moderators_cannot_suspend(self):
        for actor in [self.ordinary_user, self.moderator]:
            with self.subTest(actor=actor.username):
                with self.assertRaises(PermissionDenied):
                    self.change(actor=actor)

                self.assert_target_unchanged()

    def test_self_staff_and_superuser_targets_are_protected(self):
        for target in [self.manager, self.staff, self.superuser]:
            with self.subTest(target=target.username):
                with self.assertRaises(PermissionDenied):
                    self.change(
                        user_id=target.pk,
                        expected_session_version=target.session_version,
                    )

                target.refresh_from_db()
                self.assertTrue(target.is_active)
                self.assertEqual(target.session_version, 0)

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_invalid_actions_and_reasons_are_rejected(self):
        invalid_cases = [
            {"decision": "invalid"},
            {"reason": "short"},
            {"reason": " " * 20},
            {"reason": "x" * 2001},
        ]

        for data in invalid_cases:
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    self.change(**data)

                self.assert_target_unchanged()

    def test_duplicate_state_changes_do_not_create_extra_audits(self):
        with self.assertRaises(ValidationError):
            self.change(decision="restore")

        self.assert_target_unchanged()

        self.change()
        self.target.refresh_from_db()

        with self.assertRaises(ValidationError):
            self.change()

        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(self.target.session_version, 1)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_outdated_version_cannot_change_restored_account(self):
        opened_version = self.target.session_version

        self.change()
        self.target.refresh_from_db()
        self.change(decision="restore")
        self.target.refresh_from_db()

        with self.assertRaises(ValidationError):
            self.change(expected_session_version=opened_version)

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.target.session_version, 2)
        self.assertEqual(ModerationAction.objects.count(), 2)

    def test_audit_failure_rolls_back_account_and_session_version(self):
        with patch(
            "moderation.services.ModerationAction.objects.create",
            side_effect=IntegrityError("Simulated audit write failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.change()

        self.assert_target_unchanged()

    def test_suspended_login_fails_and_restored_login_uses_same_password(self):
        self.change()

        client = Client()
        response = client.post(
            reverse("accounts:login"),
            {
                "username": self.target.username,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertNotIn("_auth_user_id", client.session)

        self.target.refresh_from_db()
        self.change(decision="restore")

        self.sign_in_target(client)

    def test_old_sessions_stay_invalid_even_after_restoration(self):
        visited_client = Client()
        dormant_client = Client()

        self.sign_in_target(visited_client)
        self.sign_in_target(dormant_client)

        self.change()
        self.assert_profile_requires_login(visited_client)

        self.target.refresh_from_db()
        self.change(decision="restore")

        # The dormant browser made no requests during suspension.
        self.assert_profile_requires_login(dormant_client)
        self.assert_profile_requires_login(visited_client)

    def test_key_fallback_support_does_not_revive_invalidated_session(self):
        client = Client()

        with override_settings(
            SECRET_KEY="previous-test-secret",
            SECRET_KEY_FALLBACKS=[],
        ):
            client.force_login(
                self.target,
                backend="django.contrib.auth.backends.ModelBackend",
            )

        with override_settings(
            SECRET_KEY="current-test-secret",
            SECRET_KEY_FALLBACKS=["previous-test-secret"],
        ):
            response = client.get(reverse("accounts:profile"))
            self.assertEqual(response.status_code, 200)

            self.change()
            self.target.refresh_from_db()
            self.change(decision="restore")

            self.assert_profile_requires_login(client)

    def test_missing_account_returns_404(self):
        with self.assertRaises(Http404):
            self.change(user_id=self.superuser.pk + 10000)

        self.assert_target_unchanged()

class AccountManagementViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        cls.manager = User.objects.create_user(
            username="account-view-manager",
            email="account-view-manager@example.com",
        )
        cls.manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

        cls.moderator = User.objects.create_user(
            username="account-view-moderator",
            email="account-view-moderator@example.com",
        )
        cls.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        cls.ordinary_user = User.objects.create_user(
            username="account-view-ordinary",
            email="account-view-ordinary@example.com",
        )
        cls.target = User.objects.create_user(
            username="account-view-target",
            email="account-view-target@example.com",
        )
        cls.suspended = User.objects.create_user(
            username="account-view-suspended",
            email="account-view-suspended@example.com",
            is_active=False,
        )
        cls.staff = User.objects.create_user(
            username="account-view-staff",
            email="account-view-staff@example.com",
            is_staff=True,
        )
        cls.superuser = User.objects.create_user(
            username="account-view-superuser",
            email="account-view-superuser@example.com",
            is_superuser=True,
        )

        cls.list_url = reverse("moderation:account_list")
        cls.decision_url = reverse(
            "moderation:account_decision",
            kwargs={"pk": cls.target.pk},
        )

    def setUp(self):
        self.login_as(self.manager)

    def login_as(self, user):
        self.client.force_login(
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "decision": "suspend",
            "reason": "Investigated and suspended this account.",
            "expected_session_version": self.target.session_version,
        }
        data.update(overrides)
        return data

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        for method, url in [
            ("get", self.list_url),
            ("get", self.decision_url),
            ("post", self.decision_url),
        ]:
            with self.subTest(method=method, url=url):
                if method == "post":
                    response = self.client.post(url, self.valid_data())
                else:
                    response = self.client.get(url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_ordinary_users_and_review_moderators_are_denied(self):
        for user in [self.ordinary_user, self.moderator]:
            with self.subTest(user=user.username):
                self.login_as(user)

                self.assertEqual(
                    self.client.get(self.list_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.get(self.decision_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        self.decision_url,
                        self.valid_data(),
                    ).status_code,
                    403,
                )

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_nonstaff_manager_can_open_pages_without_writing(self):
        self.assertFalse(self.manager.is_staff)

        listing = self.client.get(self.list_url)
        decision = self.client.get(self.decision_url)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(decision.status_code, 200)
        self.assertTemplateUsed(
            decision,
            "moderation/account_decision.html",
        )
        self.assertEqual(
            decision.context["form"].initial["expected_session_version"],
            0,
        )
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_list_filters_search_and_excludes_protected_accounts(self):
        for state, expected_count in [
            ("active", 3),
            ("suspended", 1),
            ("all", 4),
        ]:
            with self.subTest(state=state):
                response = self.client.get(
                    self.list_url,
                    {"state": state},
                )

                self.assertEqual(
                    response.context["page_obj"].paginator.count,
                    expected_count,
                )

                ids = {
                    account.pk for account in response.context["page_obj"]
                }
                for protected in [
                    self.manager,
                    self.staff,
                    self.superuser,
                ]:
                    self.assertNotIn(protected.pk, ids)

        response = self.client.get(
            self.list_url,
            {"q": "  VIEW-TARGET  ", "state": "all"},
        )
        self.assertEqual(
            [account.pk for account in response.context["page_obj"]],
            [self.target.pk],
        )
        self.assertEqual(response.context["query"], "VIEW-TARGET")

        response = self.client.get(
            self.list_url,
            {"state": "invalid"},
        )
        self.assertEqual(response.status_code, 404)

    def test_pagination_preserves_search_and_state(self):
        User = get_user_model()

        for number in range(21):
            User.objects.create_user(
                username=f"account-page-{number:02d}",
                email=f"account-page-{number}@example.com",
            )

        first = self.client.get(
            self.list_url,
            {"q": "account-page", "state": "active"},
        )
        second = self.client.get(
            self.list_url,
            {"q": "account-page", "state": "active", "page": 2},
        )

        first_ids = [
            account.pk for account in first.context["page_obj"]
        ]
        second_ids = [
            account.pk for account in second.context["page_obj"]
        ]

        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 1)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        expected_ids = list(
            User.objects.filter(username__startswith="account-page-")
            .order_by("username", "id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)
        self.assertContains(
            first,
            "?q=account-page&amp;state=active&amp;page=2",
        )

    def test_suspend_and_restore_use_url_target_and_signed_in_actor(self):
        response = self.client.post(
            self.decision_url,
            self.valid_data(
                actor=str(self.ordinary_user.pk),
                user_id=str(self.staff.pk),
                is_superuser="on",
            ),
        )

        self.assertRedirects(response, self.list_url)

        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(self.target.is_superuser)
        self.assertEqual(self.target.session_version, 1)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.manager.pk)
        self.assertEqual(action.target_user_id, self.target.pk)

        response = self.client.post(
            self.decision_url,
            self.valid_data(
                decision="restore",
                reason="Restored after reviewing the account situation.",
            ),
        )

        self.assertRedirects(response, self.list_url)

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.target.session_version, 2)
        self.assertEqual(ModerationAction.objects.count(), 2)

        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_self_staff_superuser_and_missing_targets_are_blocked(self):
        cases = [
            (self.manager.pk, 403),
            (self.staff.pk, 403),
            (self.superuser.pk, 403),
            (self.superuser.pk + 10000, 404),
        ]

        for pk, expected_status in cases:
            url = reverse(
                "moderation:account_decision",
                kwargs={"pk": pk},
            )

            for method in ["get", "post"]:
                with self.subTest(pk=pk, method=method):
                    if method == "post":
                        response = self.client.post(url, self.valid_data())
                    else:
                        response = self.client.get(url)

                    self.assertEqual(
                        response.status_code,
                        expected_status,
                    )

        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_invalid_and_outdated_posts_do_not_suspend_account(self):
        for field, value in [
            ("decision", "invalid"),
            ("reason", "short"),
            ("expected_session_version", ""),
        ]:
            with self.subTest(field=field):
                response = self.client.post(
                    self.decision_url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

        User = get_user_model()
        User.objects.filter(pk=self.target.pk).update(
            session_version=1,
        )

        response = self.client.post(
            self.decision_url,
            self.valid_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "state changed after you opened it.",
        )

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.target.session_version, 1)
        self.assertEqual(ModerationAction.objects.count(), 0)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.manager,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.decision_url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ModerationAction.objects.count(), 0)

        client.get(self.decision_url)
        token = client.cookies["csrftoken"].value

        response = client.post(
            self.decision_url,
            self.valid_data(csrfmiddlewaretoken=token),
        )

        self.assertRedirects(response, self.list_url)

        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(ModerationAction.objects.count(), 1)

    def test_unsupported_methods_are_rejected(self):
        self.assertEqual(
            self.client.post(self.list_url).status_code,
            405,
        )

        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.decision_url,
                )
                self.assertEqual(response.status_code, 405)

class ModerationAdminProtectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.admin_user = User.objects.create_superuser(
            username="readonly-admin",
            email="readonly-admin@example.com",
            password="Forest!River82Cabin6",
        )
        cls.author = User.objects.create_user(
            username="readonly-author",
            email="readonly-author@example.com",
        )
        cls.reporter = User.objects.create_user(
            username="readonly-reporter",
            email="readonly-reporter@example.com",
        )

        cls.category = Category.objects.create(
            name="Readonly Admin",
            slug="readonly-admin",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Readonly Admin Product",
            slug="readonly-admin-product",
        )
        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=4,
            title="Readonly admin review",
            body="Content for testing read-only admin protections.",
            status=Review.Status.APPROVED,
        )
        cls.report = ReviewReport.objects.create(
            review=cls.review,
            reporter=cls.reporter,
            reason=ReviewReport.Reason.SPAM,
            details="Report for admin protection testing.",
        )
        cls.action = ModerationAction.objects.create(
            actor=cls.admin_user,
            action=ModerationAction.Action.APPROVE_REVIEW,
            review=cls.review,
            reason="Reviewed and approved the submitted content.",
            previous_state="pending",
            new_state="approved",
        )

    def setUp(self):
        self.client.force_login(
            self.admin_user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def admin_url(self, record, action):
        prefix = (
            f"{record._meta.app_label}_"
            f"{record._meta.model_name}"
        )
        name = f"admin:{prefix}_{action}"

        if action in ["add", "changelist"]:
            return reverse(name)

        return reverse(name, args=[record.pk])

    def test_superuser_can_view_records_without_save_controls(self):
        for record in [self.review, self.report, self.action]:
            with self.subTest(model=record._meta.label):
                response = self.client.get(
                    self.admin_url(record, "change"),
                )

                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'name="_save"')

    def test_add_edit_and_delete_requests_are_blocked(self):
        for record in [self.review, self.report, self.action]:
            with self.subTest(model=record._meta.label):
                add_url = self.admin_url(record, "add")
                change_url = self.admin_url(record, "change")
                delete_url = self.admin_url(record, "delete")

                self.assertEqual(
                    self.client.get(add_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(add_url, {}).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        change_url,
                        {"status": "rejected", "reason": "Forged change"},
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.get(delete_url).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        delete_url,
                        {"post": "yes"},
                    ).status_code,
                    403,
                )

                self.assertTrue(
                    record.__class__.objects.filter(
                        pk=record.pk,
                    ).exists(),
                )

        self.review.refresh_from_db()
        self.report.refresh_from_db()
        self.action.refresh_from_db()

        self.assertEqual(self.review.status, Review.Status.APPROVED)
        self.assertEqual(self.report.status, ReviewReport.Status.OPEN)
        self.assertEqual(
            self.action.reason,
            "Reviewed and approved the submitted content.",
        )

    def test_forged_bulk_delete_action_does_not_delete_records(self):
        for record in [self.review, self.report, self.action]:
            with self.subTest(model=record._meta.label):
                response = self.client.post(
                    self.admin_url(record, "changelist"),
                    {
                        "action": "delete_selected",
                        "_selected_action": [str(record.pk)],
                        "index": "0",
                        "select_across": "0",
                        "post": "yes",
                    },
                )

                self.assertIn(response.status_code, [200, 302])
                self.assertTrue(
                    record.__class__.objects.filter(
                        pk=record.pk,
                    ).exists(),
                )

    def test_user_admin_ignores_activation_and_session_version_tampering(self):
        self.author.is_active = False
        self.author.session_version = 3
        self.author.save(
            update_fields=["is_active", "session_version"],
        )

        joined = timezone.localtime(self.author.date_joined)

        response = self.client.post(
            reverse("admin:accounts_user_change", args=[self.author.pk]),
            {
                "username": self.author.username,
                "email": self.author.email,
                "first_name": "",
                "last_name": "",
                "date_joined_0": joined.strftime("%Y-%m-%d"),
                "date_joined_1": joined.strftime("%H:%M:%S"),
                "last_login_0": "",
                "last_login_1": "",
                "groups": [],
                "user_permissions": [],
                "is_active": "on",
                "session_version": "0",
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)
        self.assertEqual(self.author.session_version, 3)

