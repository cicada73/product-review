import re
import sys
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings, tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from catalog.models import Category, Product
from reviews.models import Review

from .models import ModerationAction, ReviewReport


@tag("browser")
@override_settings(
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ModerationBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        self.password = "River!Cabin73Mountain9"

        self.author = User.objects.create_user(
            username="browser-report-author",
            email="browser-report-author@example.com",
            password=self.password,
        )
        self.reporter = User.objects.create_user(
            username="browser-report-user",
            email="browser-report-user@example.com",
            password=self.password,
        )
        self.moderator = User.objects.create_user(
            username="browser-report-moderator",
            email="browser-report-moderator@example.com",
            password=self.password,
        )
        self.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        self.category = Category.objects.create(
            name="Browser Report Products",
            slug="browser-report-products",
        )
        self.product = Product.objects.create(
            category=self.category,
            name="Browser Report Product",
            slug="browser-report-product",
        )
        self.review = Review.objects.create(
            author=self.author,
            product=self.product,
            rating=4,
            title="Browser reported review",
            body="Public review content for the browser reporting workflow.",
            status=Review.Status.APPROVED,
        )

        self.manager = User.objects.create_user(
            username="browser-account-manager",
            email="browser-account-manager@example.com",
            password=self.password,
        )
        self.manager.groups.add(
            Group.objects.get(name="Account Managers"),
        )

    def field(self, page, label):
        return page.get_by_label(
            re.compile(
                r"^\s*" + re.escape(label) + r"\s*:?\s*$"
            )
        )

    def login(self, page, username):
        page.goto(
            self.live_server_url + reverse("accounts:login"),
        )
        self.field(page, "Username").fill(username)
        self.field(page, "Password").fill(self.password)

        page.get_by_role(
            "button",
            name="Log in",
            exact=True,
        ).click()

        expect(page).to_have_url(
            self.live_server_url + reverse("home"),
        )

    def close_browser(self, browser):
        original_error_exists = sys.exc_info()[0] is not None

        try:
            browser.close()
        except Exception:
            if not original_error_exists:
                raise

    def test_report_and_resolve_without_changing_public_review(self):
        details = "This review appears to contain promotional spam."
        resolution_note = (
            "Investigated the concern and recorded the resolution."
        )

        detail_url = (
            self.live_server_url
            + reverse(
                "catalog:product_detail",
                kwargs={"slug": self.product.slug},
            )
        )
        report_queue_url = (
            self.live_server_url
            + reverse("moderation:report_queue")
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                reporter_page = browser.new_context().new_page()
                moderator_page = browser.new_context().new_page()
                visitor_page = browser.new_context().new_page()

                # A regular user reports another author's review.
                self.login(reporter_page, self.reporter.username)
                reporter_page.goto(detail_url)

                reporter_page.get_by_role(
                    "link",
                    name="Report review",
                    exact=True,
                ).click()

                self.field(reporter_page, "Reason").select_option("spam")
                self.field(
                    reporter_page,
                    "Additional details",
                ).fill(details)

                reporter_page.get_by_role(
                    "button",
                    name="Submit report",
                    exact=True,
                ).click()

                expect(reporter_page).to_have_url(detail_url)
                expect(
                    reporter_page.get_by_text(
                        "Your report was submitted for moderator review.",
                        exact=True,
                    )
                ).to_be_visible()

                # Reporting does not automatically hide the review.
                visitor_page.goto(detail_url)

                expect(
                    visitor_page.get_by_role(
                        "heading",
                        name=self.review.title,
                        level=3,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    visitor_page.locator(".product-rating")
                ).to_contain_text("1 approved review")

                # A different moderator resolves the report.
                self.login(moderator_page, self.moderator.username)
                moderator_page.goto(report_queue_url)

                moderator_page.get_by_role(
                    "link",
                    name="View report",
                    exact=True,
                ).click()

                expect(
                    moderator_page.get_by_text(details, exact=True)
                ).to_be_visible()

                self.field(
                    moderator_page,
                    "Report outcome",
                ).select_option("resolved")
                self.field(
                    moderator_page,
                    "Resolution note",
                ).fill(resolution_note)

                moderator_page.get_by_role(
                    "button",
                    name="Save report outcome",
                    exact=True,
                ).click()

                expect(moderator_page).to_have_url(report_queue_url)
                expect(
                    moderator_page.get_by_text(
                        "No reports match this status.",
                        exact=True,
                    )
                ).to_be_visible()

                # Find the closed report and inspect its outcome.
                self.field(
                    moderator_page,
                    "Report status",
                ).select_option("resolved")

                moderator_page.get_by_role(
                    "button",
                    name="Apply filter",
                    exact=True,
                ).click()

                moderator_page.get_by_role(
                    "link",
                    name="View report",
                    exact=True,
                ).click()

                expect(
                    moderator_page.get_by_role(
                        "heading",
                        name="Report closed",
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    moderator_page.get_by_text(
                        resolution_note,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    moderator_page.get_by_text(
                        f"Closed by {self.moderator.username}",
                        exact=True,
                    )
                ).to_be_visible()

                visitor_page.reload()

                expect(
                    visitor_page.get_by_role(
                        "heading",
                        name=self.review.title,
                        level=3,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    visitor_page.locator(".product-rating")
                ).to_contain_text("4.0 out of 5")
            finally:
                self.close_browser(browser)

        # Inspect database state after Playwright has stopped.
        report = ReviewReport.objects.get()
        self.assertEqual(report.reporter_id, self.reporter.pk)
        self.assertEqual(report.review_id, self.review.pk)
        self.assertEqual(report.details, details)
        self.assertEqual(report.status, ReviewReport.Status.RESOLVED)
        self.assertEqual(report.resolved_by_id, self.moderator.pk)
        self.assertEqual(report.resolution_note, resolution_note)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.report_id, report.pk)
        self.assertEqual(
            action.action,
            ModerationAction.Action.RESOLVE_REPORT,
        )

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, Review.Status.APPROVED)

    def assert_profile_requires_login(self, page):
        profile_path = reverse("accounts:profile")
        page.goto(self.live_server_url + profile_path)

        expect(self.field(page, "Username")).to_be_visible()

        self.assertEqual(
            urlsplit(page.url).path,
            reverse("accounts:login"),
        )
        self.assertEqual(
            parse_qs(urlsplit(page.url).query)["next"],
            [profile_path],
        )

    def test_suspend_restore_and_invalidate_old_browser_sessions(self):
        account_list_url = (
            self.live_server_url
            + reverse("moderation:account_list")
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                manager_page = browser.new_context().new_page()
                visited_page = browser.new_context().new_page()
                dormant_page = browser.new_context().new_page()

                # Two independent sessions belong to the target account.
                self.login(visited_page, self.reporter.username)
                self.login(dormant_page, self.reporter.username)
                self.login(manager_page, self.manager.username)

                # Find and suspend the target.
                manager_page.goto(account_list_url)

                self.field(
                    manager_page,
                    "Search usernames",
                ).fill(self.reporter.username)

                manager_page.get_by_role(
                    "button",
                    name="Apply filters",
                    exact=True,
                ).click()

                manager_page.get_by_role(
                    "link",
                    name="Manage account",
                    exact=True,
                ).click()

                self.field(
                    manager_page,
                    "Account action",
                ).select_option("suspend")
                self.field(manager_page, "Reason").fill(
                    "Suspended after investigating the browser test concern."
                )

                manager_page.get_by_role(
                    "button",
                    name="Save account action",
                    exact=True,
                ).click()

                expect(manager_page).to_have_url(account_list_url)

                # An existing session loses access during suspension.
                self.assert_profile_requires_login(visited_page)

                # Correct credentials cannot log in while suspended.
                self.field(
                    visited_page,
                    "Username",
                ).fill(self.reporter.username)
                self.field(
                    visited_page,
                    "Password",
                ).fill(self.password)

                visited_page.get_by_role(
                    "button",
                    name="Log in",
                    exact=True,
                ).click()

                expect(
                    visited_page.locator(".errorlist")
                ).to_be_visible()

                # Find the account under Suspended and restore it.
                manager_page.goto(account_list_url)

                self.field(
                    manager_page,
                    "Search usernames",
                ).fill(self.reporter.username)
                self.field(
                    manager_page,
                    "Account state",
                ).select_option("suspended")

                manager_page.get_by_role(
                    "button",
                    name="Apply filters",
                    exact=True,
                ).click()

                manager_page.get_by_role(
                    "link",
                    name="Manage account",
                    exact=True,
                ).click()

                self.field(
                    manager_page,
                    "Account action",
                ).select_option("restore")
                self.field(manager_page, "Reason").fill(
                    "Restored after reviewing the browser test situation."
                )

                manager_page.get_by_role(
                    "button",
                    name="Save account action",
                    exact=True,
                ).click()

                expect(manager_page).to_have_url(account_list_url)

                # This browser made no requests during suspension.
                # Restoration must not revive its old session.
                self.assert_profile_requires_login(dormant_page)

                # Fresh login with the original password now succeeds.
                self.login(dormant_page, self.reporter.username)
                dormant_page.goto(
                    self.live_server_url + reverse("accounts:profile"),
                )

                expect(
                    dormant_page.get_by_text(
                        self.reporter.email,
                        exact=True,
                    )
                ).to_be_visible()
            finally:
                self.close_browser(browser)

        self.reporter.refresh_from_db()
        self.assertTrue(self.reporter.is_active)
        self.assertEqual(self.reporter.session_version, 2)
        self.assertTrue(self.reporter.check_password(self.password))

        actions = ModerationAction.objects.filter(
            target_user=self.reporter,
        ).order_by("created_at", "id")

        self.assertEqual(
            list(actions.values_list("action", flat=True)),
            [
                ModerationAction.Action.SUSPEND_USER,
                ModerationAction.Action.RESTORE_USER,
            ],
        )
        self.assertFalse(
            actions.exclude(actor=self.manager).exists(),
        )