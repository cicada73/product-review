import re
import sys
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.shortcuts import resolve_url
from django.test import override_settings, tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright


@tag("browser")
@override_settings(
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class AccountBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.password = "River!Cabin73Mountain9"
        self.existing_user = get_user_model().objects.create_user(
            username="browser-existing-user",
            email="browser-existing@example.com",
            password=self.password,
        )

    def field(self, page, label):
        pattern = re.compile(
            r"^\s*" + re.escape(label) + r"\s*:?\s*$"
        )
        return page.get_by_label(pattern)

    def close_browser(self, browser):
        original_error_exists = sys.exc_info()[0] is not None

        try:
            browser.close()
        except Exception:
            if not original_error_exists:
                raise

    def open_login(self, page):
        page.goto(
            self.live_server_url + reverse("accounts:login"),
        )

    def submit_login(self, page, username, password):
        self.field(page, "Username").fill(username)
        self.field(page, "Password").fill(password)
        page.locator("form").get_by_role("button").click()

    def logout_from_home(self, page):
        page.goto(self.live_server_url + reverse("home"))

        logout_path = reverse("accounts:logout")
        page.locator(
            f'form[action="{logout_path}"]'
        ).get_by_role("button").click()

        expect(page).to_have_url(
            self.live_server_url
            + resolve_url(settings.LOGOUT_REDIRECT_URL),
        )

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

    def test_signup_profile_edit_and_logout(self):
        username = "browser-signup-user"
        email = "Browser.New@Example.COM"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()
                page.goto(
                    self.live_server_url + reverse("accounts:signup"),
                )

                self.field(page, "Username").fill(username)
                self.field(page, "Email").fill(email)
                self.field(page, "Password").fill(self.password)
                self.field(
                    page,
                    "Password confirmation",
                ).fill(self.password)

                page.locator("form").get_by_role("button").click()

                expect(page).to_have_url(
                    self.live_server_url + reverse("home"),
                )
                page.get_by_role(
                    "link",
                    name="Your profile",
                    exact=True,
                ).click()

                expect(page).to_have_url(
                    self.live_server_url + reverse("accounts:profile"),
                )
                expect(
                    page.get_by_text(
                        "browser.new@example.com",
                        exact=True,
                    )
                ).to_be_visible()

                self.field(page, "First name").fill("Browser")
                self.field(page, "Last name").fill("Tester")
                page.locator("form").get_by_role("button").click()

                expect(page).to_have_url(
                    self.live_server_url + reverse("accounts:profile"),
                )

                page.reload()

                expect(
                    self.field(page, "First name")
                ).to_have_value("Browser")
                expect(
                    self.field(page, "Last name")
                ).to_have_value("Tester")

                self.logout_from_home(page)
                self.assert_profile_requires_login(page)
            finally:
                self.close_browser(browser)

        # Run database assertions after Playwright has stopped.
        user = get_user_model().objects.get(username=username)
        self.assertEqual(user.email, "browser.new@example.com")
        self.assertEqual(user.first_name, "Browser")
        self.assertEqual(user.last_name, "Tester")
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_invalid_login_then_valid_login_and_logout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()
                self.open_login(page)

                self.submit_login(
                    page,
                    self.existing_user.username,
                    "IncorrectPassword!123",
                )

                expect(page).to_have_url(
                    self.live_server_url + reverse("accounts:login"),
                )
                expect(page.locator(".errorlist")).to_be_visible()

                self.submit_login(
                    page,
                    self.existing_user.username,
                    self.password,
                )

                expect(page).to_have_url(
                    self.live_server_url + reverse("home"),
                )
                page.get_by_role(
                    "link",
                    name="Your profile",
                    exact=True,
                ).click()

                expect(page).to_have_url(
                    self.live_server_url + reverse("accounts:profile"),
                )
                expect(
                    page.get_by_text(
                        self.existing_user.email,
                        exact=True,
                    )
                ).to_be_visible()

                self.logout_from_home(page)
                self.assert_profile_requires_login(page)
            finally:
                self.close_browser(browser)