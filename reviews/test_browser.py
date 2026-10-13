import re
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings, tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from catalog.models import Category, Product
from moderation.models import ModerationAction

from .models import Review


@tag("browser")
@override_settings(
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ReviewLifecycleBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()

        self.password = "River!Cabin73Mountain9"

        self.author = User.objects.create_user(
            username="browser-review-author",
            email="browser-review-author@example.com",
            password=self.password,
        )
        self.moderator = User.objects.create_user(
            username="browser-review-moderator",
            email="browser-review-moderator@example.com",
            password=self.password,
        )
        self.moderator.groups.add(
            Group.objects.get(name="Review Moderators"),
        )

        self.category = Category.objects.create(
            name="Browser Review Products",
            slug="browser-review-products",
        )
        self.product = Product.objects.create(
            category=self.category,
            name="Browser Lifecycle Product",
            slug="browser-lifecycle-product",
            description="A product for testing the complete review lifecycle.",
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
        page.locator("form").get_by_role("button").click()

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

    def test_submit_approve_and_edit_back_to_pending(self):
        original_title = "Browser lifecycle review"
        edited_title = "Edited browser lifecycle review"
        edited_body = (
            "My experience changed after using this product for longer."
        )
        detail_url = (
            self.live_server_url
            + reverse(
                "catalog:product_detail",
                kwargs={"slug": self.product.slug},
            )
        )
        queue_url = (
            self.live_server_url
            + reverse("moderation:review_queue")
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                author_page = browser.new_context().new_page()
                moderator_page = browser.new_context().new_page()
                visitor_page = browser.new_context().new_page()

                # The author submits a new review.
                self.login(author_page, self.author.username)
                author_page.goto(detail_url)
                author_page.get_by_role(
                    "link",
                    name="Write a review",
                    exact=True,
                ).click()

                self.field(author_page, "Rating").select_option("4")
                self.field(author_page, "Review title").fill(
                    original_title,
                )
                self.field(author_page, "Your review").fill(
                    "This product worked well throughout everyday use.",
                )
                author_page.get_by_role(
                    "button",
                    name="Submit review",
                    exact=True,
                ).click()

                expect(author_page).to_have_url(detail_url)
                expect(
                    author_page.get_by_role(
                        "link",
                        name="Edit my review",
                        exact=True,
                    )
                ).to_be_visible()

                # A visitor cannot see the pending review.
                visitor_page.goto(detail_url)
                expect(
                    visitor_page.get_by_role(
                        "heading",
                        name=original_title,
                        exact=True,
                    )
                ).to_have_count(0)
                expect(
                    visitor_page.get_by_text(
                        "No approved reviews yet.",
                        exact=True,
                    )
                ).to_be_visible()

                # A separate moderator session approves it.
                self.login(moderator_page, self.moderator.username)
                moderator_page.goto(queue_url)
                moderator_page.get_by_role(
                    "link",
                    name="Review and decide",
                    exact=True,
                ).click()

                expect(
                    moderator_page.get_by_role(
                        "heading",
                        name=original_title,
                        level=1,
                        exact=True,
                    )
                ).to_be_visible()

                self.field(
                    moderator_page,
                    "Decision",
                ).select_option("approved")
                self.field(
                    moderator_page,
                    "Reason for this decision",
                ).fill(
                    "Reviewed the complete content and approved this review."
                )
                moderator_page.get_by_role(
                    "button",
                    name="Save decision",
                    exact=True,
                ).click()

                expect(moderator_page).to_have_url(queue_url)

                # The visitor now sees the approved review and rating.
                visitor_page.reload()
                expect(
                    visitor_page.get_by_role(
                        "heading",
                        name=original_title,
                        level=3,
                        exact=True,
                    )
                ).to_be_visible()
                expect(
                    visitor_page.locator(".product-rating")
                ).to_contain_text("4.0 out of 5")
                expect(
                    visitor_page.locator(".product-rating")
                ).to_contain_text("1 approved review")

                # Editing requires approval again.
                author_page.goto(detail_url)
                author_page.get_by_role(
                    "link",
                    name="Edit my review",
                    exact=True,
                ).click()

                expect(
                    self.field(author_page, "Review title")
                ).to_have_value(original_title)

                self.field(author_page, "Rating").select_option("2")
                self.field(author_page, "Review title").fill(edited_title)
                self.field(author_page, "Your review").fill(edited_body)
                author_page.get_by_role(
                    "button",
                    name="Save changes",
                    exact=True,
                ).click()

                expect(author_page).to_have_url(detail_url)

                visitor_page.reload()
                for title in [original_title, edited_title]:
                    expect(
                        visitor_page.get_by_role(
                            "heading",
                            name=title,
                            exact=True,
                        )
                    ).to_have_count(0)

                expect(
                    visitor_page.get_by_text(
                        "No approved reviews yet.",
                        exact=True,
                    )
                ).to_be_visible()

                # The author can still see it privately.
                author_page.goto(
                    self.live_server_url + reverse("reviews:my_reviews"),
                )
                expect(
                    author_page.get_by_role(
                        "heading",
                        name=edited_title,
                        exact=True,
                    )
                ).to_be_visible()
                expect(
                    author_page.get_by_text(
                        "Status: Pending",
                        exact=True,
                    )
                ).to_be_visible()
            finally:
                self.close_browser(browser)

        # Database assertions run after Playwright has stopped.
        review = Review.objects.get(
            author=self.author,
            product=self.product,
        )
        self.assertEqual(review.rating, 2)
        self.assertEqual(review.title, edited_title)
        self.assertEqual(review.body, edited_body)
        self.assertEqual(review.status, Review.Status.PENDING)

        action = ModerationAction.objects.get()
        self.assertEqual(action.actor_id, self.moderator.pk)
        self.assertEqual(action.review_id, review.pk)
        self.assertEqual(
            action.action,
            ModerationAction.Action.APPROVE_REVIEW,
        )
        self.assertEqual(action.previous_state, "pending")
        self.assertEqual(action.new_state, "approved")