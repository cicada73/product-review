from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings, tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright
from urllib.parse import parse_qs, urlsplit

from .models import Category, Product

import sys


@tag("browser")
@override_settings(
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class CatalogBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Browser Electronics",
            slug="browser-electronics",
        )
        self.product = Product.objects.create(
            category=self.category,
            name="Browser Test Laptop",
            slug="browser-test-laptop",
            brand="Northstar",
            description="A laptop created for browser testing.",
        )
        self.hidden_product = Product.objects.create(
            category=self.category,
            name="Hidden Browser Product",
            slug="hidden-browser-product",
            is_active=False,
        )
        self.books_category = Category.objects.create(
            name="Browser Books",
            slug="browser-books",
        )
        self.other_product = Product.objects.create(
            category=self.books_category,
            name="Browser Gardening Guide",
            slug="browser-gardening-guide",
            brand="LeafPress",
            description="A guide to growing vegetables.",
        )
    def close_browser(self, browser):
        original_error_exists = sys.exc_info()[0] is not None

        try:
            browser.close()
        except Exception:
            if not original_error_exists:
                raise
    def test_public_catalog_to_product_detail(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()

                page.goto(
                    self.live_server_url + reverse("home"),
                )
                page.get_by_role(
                    "link",
                    name="Browse products",
                    exact=True,
                ).click()

                expect(page).to_have_url(
                    self.live_server_url
                    + reverse("catalog:product_list"),
                )
                expect(
                    page.get_by_role(
                        "heading",
                        name="Browse products",
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    page.get_by_role(
                        "heading",
                        name=self.product.name,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    page.get_by_text(
                        self.hidden_product.name,
                        exact=True,
                    )
                ).to_have_count(0)

                page.get_by_role(
                    "link",
                    name=self.product.name,
                    exact=True,
                ).click()

                expect(page).to_have_url(
                    self.live_server_url
                    + reverse(
                        "catalog:product_detail",
                        kwargs={"slug": self.product.slug},
                    ),
                )
                expect(
                    page.get_by_role(
                        "heading",
                        name=self.product.name,
                        level=1,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    page.get_by_text(
                        self.product.description,
                        exact=True,
                    )
                ).to_be_visible()

                expect(
                    page.get_by_text(
                        "No approved reviews yet.",
                        exact=True,
                    )
                ).to_be_visible()
            finally:
                self.close_browser(browser)

    def test_search_category_filter_and_clear_filters(self):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)

                try:
                    page = browser.new_page()
                    page.goto(
                        self.live_server_url
                        + reverse("catalog:product_list"),
                    )

                    page.get_by_label("Search products").fill("Northstar")
                    page.get_by_label("Category", exact=True).select_option(
                        self.category.slug,
                    )
                    page.get_by_role(
                        "button",
                        name="Apply filters",
                        exact=True,
                    ).click()

                    expect(
                        page.get_by_role(
                            "heading",
                            name=self.product.name,
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(
                        page.get_by_role(
                            "heading",
                            name=self.other_product.name,
                            exact=True,
                        )
                    ).to_have_count(0)

                    # Keep the search but choose a category without a match.
                    page.get_by_label("Category", exact=True).select_option(
                        self.books_category.slug,
                    )
                    page.get_by_role(
                        "button",
                        name="Apply filters",
                        exact=True,
                    ).click()

                    expect(
                        page.get_by_text(
                            "No products match your search or category selection.",
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(
                        page.get_by_label("Search products")
                    ).to_have_value("Northstar")

                    page.get_by_role(
                        "link",
                        name="Clear filters",
                        exact=True,
                    ).click()

                    expect(
                        page.get_by_label("Search products")
                    ).to_have_value("")
                    expect(
                        page.get_by_label("Category", exact=True)
                    ).to_have_value("")

                    for product in [self.product, self.other_product]:
                        expect(
                            page.get_by_role(
                                "heading",
                                name=product.name,
                                exact=True,
                            )
                        ).to_be_visible()
                finally:
                    self.close_browser(browser)

    def test_pagination_preserves_search_and_category(self):
        # Create database fixtures before starting Playwright.
        for number in range(13):
            Product.objects.create(
                category=self.category,
                name=f"Browser Paging Product {number:02d}",
                slug=f"browser-paging-product-{number}",
            )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()
                page.goto(
                    self.live_server_url
                    + reverse("catalog:product_list"),
                )

                page.get_by_label("Search products").fill("Paging")
                page.get_by_label("Category", exact=True).select_option(
                    self.category.slug,
                )
                page.get_by_role(
                    "button",
                    name="Apply filters",
                    exact=True,
                ).click()

                cards = page.get_by_role(
                    "region",
                    name="Products",
                    exact=True,
                ).get_by_role("article")

                expect(cards).to_have_count(12)

                page.get_by_role(
                    "link",
                    name="Next",
                    exact=True,
                ).click()

                expect(cards).to_have_count(1)
                expect(
                    page.get_by_text("Page 2 of 2", exact=True)
                ).to_be_visible()

                parameters = parse_qs(urlsplit(page.url).query)
                self.assertEqual(parameters["q"], ["Paging"])
                self.assertEqual(
                    parameters["category"],
                    [self.category.slug],
                )
                self.assertEqual(parameters["page"], ["2"])

                expect(
                    page.get_by_label("Search products")
                ).to_have_value("Paging")
                expect(
                    page.get_by_label("Category", exact=True)
                ).to_have_value(self.category.slug)

                page.get_by_role(
                    "link",
                    name="Previous",
                    exact=True,
                ).click()

                expect(cards).to_have_count(12)
                expect(
                    page.get_by_text("Page 1 of 2", exact=True)
                ).to_be_visible()
            finally:
                self.close_browser(browser)

    def test_search_form_can_be_used_with_keyboard(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()
                page.goto(
                    self.live_server_url
                    + reverse("catalog:product_list"),
                )

                search = page.get_by_label("Search products")
                category = page.get_by_label("Category", exact=True)
                apply_button = page.get_by_role(
                    "button",
                    name="Apply filters",
                    exact=True,
                )

                search.focus()
                page.keyboard.type("Northstar")

                page.keyboard.press("Tab")
                expect(category).to_be_focused()

                page.keyboard.press("Tab")
                expect(apply_button).to_be_focused()

                page.keyboard.press("Enter")

                expect(
                    page.get_by_role(
                        "heading",
                        name=self.product.name,
                        exact=True,
                    )
                ).to_be_visible()
                expect(
                    page.get_by_role(
                        "heading",
                        name=self.other_product.name,
                        exact=True,
                    )
                ).to_have_count(0)
                expect(search).to_have_value("Northstar")
            finally:
                self.close_browser(browser)

    def test_public_pages_do_not_overflow_narrow_viewports(self):
        paths = [
            reverse("home"),
            reverse("catalog:product_list"),
            reverse(
                "catalog:product_detail",
                kwargs={"slug": self.product.slug},
            ),
        ]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            try:
                page = browser.new_page()

                for width in [320, 390]:
                    page.set_viewport_size(
                        {"width": width, "height": 900},
                    )

                    for path in paths:
                        with self.subTest(width=width, path=path):
                            page.goto(self.live_server_url + path)

                            expect(
                                page.get_by_role("heading", level=1)
                            ).to_be_visible()

                            dimensions = page.evaluate(
                                """() => ({
                                    scrollWidth:
                                        document.documentElement.scrollWidth,
                                    clientWidth:
                                        document.documentElement.clientWidth
                                })"""
                            )

                            self.assertLessEqual(
                                dimensions["scrollWidth"],
                                dimensions["clientWidth"] + 1,
                                (
                                    f"Horizontal overflow at {width}px "
                                    f"on {path}: {dimensions}"
                                ),
                            )
            finally:
                self.close_browser(browser)