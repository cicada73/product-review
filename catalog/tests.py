from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from io import StringIO

from .models import Category, Product

from django.core.management import call_command

from django.contrib.auth import get_user_model
from django.urls import reverse

from reviews.models import Review


class CatalogModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name="Electronics",
            slug="electronics",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Wireless Headphones",
            slug="wireless-headphones",
            description="Sample headphones.",
        )

    def test_category_name_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(
                    name="Electronics",
                    slug="another-category",
                )

    def test_category_slug_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(
                    name="Another Category",
                    slug="electronics",
                )

    def test_product_slug_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(
                    category=self.category,
                    name="Another Product",
                    slug="wireless-headphones",
                    description="Another sample product.",
                )

    def test_category_with_products_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.category.delete()

        self.assertTrue(
            Category.objects.filter(pk=self.category.pk).exists()
        )
        self.assertTrue(
            Product.objects.filter(pk=self.product.pk).exists()
        )
class SeedDemoCommandTests(TestCase):
    def test_command_can_run_twice_without_duplicates(self):
        output = StringIO()

        call_command("seed_demo", stdout=output)
        call_command("seed_demo", stdout=output)

        self.assertEqual(Category.objects.count(), 3)
        self.assertEqual(Product.objects.count(), 6)

    def test_command_preserves_existing_product_data(self):
        category = Category.objects.create(
            name="Electronics",
            slug="electronics",
            description="My category description.",
        )
        product = Product.objects.create(
            category=category,
            name="My Headphones",
            slug="wireless-headphones",
            brand="My Brand",
            description="My product description.",
            is_active=False,
        )

        call_command("seed_demo", stdout=StringIO())

        category.refresh_from_db()
        product.refresh_from_db()

        self.assertEqual(
            category.description,
            "My category description.",
        )
        self.assertEqual(product.name, "My Headphones")
        self.assertEqual(product.brand, "My Brand")
        self.assertEqual(
            product.description,
            "My product description.",
        )
        self.assertFalse(product.is_active)

class ProductListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.electronics = Category.objects.create(
            name="Electronics",
            slug="electronics",
        )
        cls.books = Category.objects.create(
            name="Books",
            slug="books",
        )

        cls.laptop = Product.objects.create(
            category=cls.electronics,
            name="Trail Laptop",
            slug="trail-laptop",
            brand="Northstar",
            description="A portable computer for travelling.",
        )
        cls.monitor = Product.objects.create(
            category=cls.electronics,
            name="Desk Monitor",
            slug="desk-monitor",
            brand="Pixelcraft",
            description="An office display.",
        )
        cls.book = Product.objects.create(
            category=cls.books,
            name="Gardening Guide",
            slug="gardening-guide",
            brand="LeafPress",
            description="Learn how to grow vegetables.",
        )
        cls.hidden = Product.objects.create(
            category=cls.electronics,
            name="Hidden Product",
            slug="hidden-product",
            is_active=False,
        )

        cls.url = reverse("catalog:product_list")

    def create_paging_products(self):
        for number in range(13):
            Product.objects.create(
                category=self.electronics,
                name=f"Paging Product {number:02d}",
                slug=f"paging-product-{number}",
            )

    def test_public_listing_shows_only_active_products(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "catalog/product_list.html")
        self.assertEqual(response.context["page_obj"].paginator.count, 3)

        for product in [self.laptop, self.monitor, self.book]:
            self.assertContains(response, product.name)
            self.assertContains(
                response,
                reverse(
                    "catalog:product_detail",
                    kwargs={"slug": product.slug},
                ),
            )

        self.assertNotContains(response, self.hidden.name)

    def test_search_matches_name_brand_and_description(self):
        searches = [
            ("Trail", self.laptop.pk),
            ("Pixelcraft", self.monitor.pk),
            ("vegetables", self.book.pk),
        ]

        for query, expected_id in searches:
            with self.subTest(query=query):
                response = self.client.get(self.url, {"q": query})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [product.pk for product in response.context["page_obj"]],
                    [expected_id],
                )

    def test_search_ignores_case_and_surrounding_whitespace(self):
        response = self.client.get(self.url, {"q": "  tRaIl  "})

        self.assertEqual(response.context["query"], "tRaIl")
        self.assertEqual(
            [product.pk for product in response.context["page_obj"]],
            [self.laptop.pk],
        )

    def test_category_filter(self):
        response = self.client.get(
            self.url,
            {"category": self.electronics.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {product.pk for product in response.context["page_obj"]},
            {self.laptop.pk, self.monitor.pk},
        )
        self.assertEqual(
            response.context["selected_category"],
            self.electronics.slug,
        )

    def test_search_and_category_filter_work_together(self):
        response = self.client.get(
            self.url,
            {"q": "Trail", "category": self.electronics.slug},
        )
        self.assertEqual(
            [product.pk for product in response.context["page_obj"]],
            [self.laptop.pk],
        )

        response = self.client.get(
            self.url,
            {"q": "Trail", "category": self.books.slug},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_unknown_category_returns_404(self):
        response = self.client.get(
            self.url,
            {"category": "nonexistent-category"},
        )

        self.assertEqual(response.status_code, 404)

    def test_no_matches_shows_empty_message(self):
        response = self.client.get(self.url, {"q": "zzzz-no-match"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertContains(
            response,
            "No products match your search or category selection.",
        )

    def test_pagination_has_no_duplicates_or_missing_products(self):
        self.create_paging_products()

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})

        first_ids = [
            product.pk for product in first.context["page_obj"]
        ]
        second_ids = [
            product.pk for product in second.context["page_obj"]
        ]

        self.assertEqual(len(first_ids), 12)
        self.assertEqual(len(second_ids), 4)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        expected_ids = list(
            Product.objects.filter(is_active=True)
            .order_by("name", "id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)

    def test_pagination_preserves_search_and_category(self):
        self.create_paging_products()

        response = self.client.get(
            self.url,
            {"q": "Paging", "category": self.electronics.slug},
        )

        self.assertEqual(response.context["page_obj"].paginator.count, 13)
        self.assertContains(
            response,
            "?q=Paging&amp;category=electronics&amp;page=2",
        )

        second = self.client.get(
            self.url,
            {
                "q": "Paging",
                "category": self.electronics.slug,
                "page": 2,
            },
        )

        self.assertEqual(len(second.context["page_obj"]), 1)
        self.assertEqual(
            second.context["page_obj"][0].category_id,
            self.electronics.pk,
        )

    def test_invalid_page_values_are_handled(self):
        for page in ["banana", "999", "-1"]:
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, 1)

    def test_ratings_include_only_approved_reviews(self):
        User = get_user_model()

        review_data = [
            (4, Review.Status.APPROVED),
            (2, Review.Status.APPROVED),
            (5, Review.Status.PENDING),
            (1, Review.Status.REJECTED),
        ]

        for number, (rating, status) in enumerate(review_data):
            author = User.objects.create_user(
                username=f"listing-reviewer-{number}",
                email=f"listing-reviewer-{number}@example.com",
            )
            Review.objects.create(
                author=author,
                product=self.laptop,
                rating=rating,
                title=f"Review {number}",
                body="Test review content.",
                status=status,
            )

        response = self.client.get(self.url)
        products = {
            product.pk: product
            for product in response.context["page_obj"]
        }

        laptop = products[self.laptop.pk]
        self.assertEqual(laptop.review_count, 2)
        self.assertAlmostEqual(laptop.average_rating, 3.0)

        book = products[self.book.pk]
        self.assertEqual(book.review_count, 0)
        self.assertIsNone(book.average_rating)
        self.assertContains(response, "No approved reviews yet.")

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

class ProductDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name="Detail Electronics",
            slug="detail-electronics",
        )

        cls.product = Product.objects.create(
            category=cls.category,
            name="Detail Laptop",
            slug="detail-laptop",
            brand="Northstar",
            description="Full product description for detail testing.",
        )
        cls.empty_product = Product.objects.create(
            category=cls.category,
            name="Unreviewed Product",
            slug="unreviewed-product",
        )
        cls.other_product = Product.objects.create(
            category=cls.category,
            name="Other Product",
            slug="other-product",
        )
        cls.hidden_product = Product.objects.create(
            category=cls.category,
            name="Inactive Product",
            slug="inactive-product",
            is_active=False,
        )

        User = get_user_model()
        cls.authors = [
            User.objects.create_user(
                username=f"detail-reviewer-{number}",
                email=f"detail-reviewer-{number}@example.com",
            )
            for number in range(5)
        ]

        cls.approved_one = Review.objects.create(
            author=cls.authors[0],
            product=cls.product,
            rating=4,
            title="Approved first review",
            body="Public first review content.",
            status=Review.Status.APPROVED,
        )
        cls.approved_two = Review.objects.create(
            author=cls.authors[1],
            product=cls.product,
            rating=2,
            title="Approved second review",
            body="Public second review content.",
            status=Review.Status.APPROVED,
        )
        cls.pending = Review.objects.create(
            author=cls.authors[2],
            product=cls.product,
            rating=5,
            title="Pending private review",
            body="Pending private content.",
            status=Review.Status.PENDING,
        )
        cls.rejected = Review.objects.create(
            author=cls.authors[3],
            product=cls.product,
            rating=1,
            title="Rejected private review",
            body="Rejected private content.",
            status=Review.Status.REJECTED,
        )
        cls.other_review = Review.objects.create(
            author=cls.authors[4],
            product=cls.other_product,
            rating=5,
            title="Review for another product",
            body="Other product review content.",
            status=Review.Status.APPROVED,
        )

        cls.url = reverse(
            "catalog:product_detail",
            kwargs={"slug": cls.product.slug},
        )

    def test_detail_page_is_public_and_shows_product_information(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "catalog/product_detail.html")
        self.assertEqual(response.context["product"].pk, self.product.pk)

        self.assertContains(response, self.product.name)
        self.assertContains(response, self.product.brand)
        self.assertContains(response, self.product.description)
        self.assertContains(response, self.category.name)

    def test_only_this_products_approved_reviews_are_public(self):
        response = self.client.get(self.url)

        for review in [self.approved_one, self.approved_two]:
            self.assertContains(response, review.title)
            self.assertContains(response, review.body)

        for review in [self.pending, self.rejected, self.other_review]:
            self.assertNotContains(response, review.title)
            self.assertNotContains(response, review.body)

        summary = response.context["rating_summary"]
        self.assertEqual(summary["review_count"], 2)
        self.assertAlmostEqual(summary["average_rating"], 3.0)

    def test_product_without_reviews_shows_empty_messages(self):
        url = reverse(
            "catalog:product_detail",
            kwargs={"slug": self.empty_product.slug},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        summary = response.context["rating_summary"]
        self.assertEqual(summary["review_count"], 0)
        self.assertIsNone(summary["average_rating"])

        self.assertContains(response, "No approved reviews yet.")
        self.assertContains(
            response,
            "There are no approved reviews to display.",
        )

    def test_inactive_product_returns_404(self):
        url = reverse(
            "catalog:product_detail",
            kwargs={"slug": self.hidden_product.slug},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(
            response,
            self.hidden_product.name,
            status_code=404,
        )

    def test_unknown_product_returns_404(self):
        url = reverse(
            "catalog:product_detail",
            kwargs={"slug": "nonexistent-product"},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

    def test_review_pagination_keeps_summary_for_all_approved_reviews(self):
        User = get_user_model()

        for number in range(11):
            author = User.objects.create_user(
                username=f"paging-reviewer-{number}",
                email=f"paging-reviewer-{number}@example.com",
            )
            Review.objects.create(
                author=author,
                product=self.product,
                rating=5,
                title=f"Additional approved review {number}",
                body="Additional public review content.",
                status=Review.Status.APPROVED,
            )

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        first_ids = [
            review.pk for review in first.context["review_page"]
        ]
        second_ids = [
            review.pk for review in second.context["review_page"]
        ]

        self.assertEqual(len(first_ids), 10)
        self.assertEqual(len(second_ids), 3)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        expected_ids = list(
            Review.objects.filter(
                product=self.product,
                status=Review.Status.APPROVED,
            )
            .order_by("-created_at", "-id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)

        # Two original ratings (4 and 2), plus eleven ratings of 5.
        expected_average = (4 + 2 + 11 * 5) / 13

        for response in [first, second]:
            summary = response.context["rating_summary"]
            self.assertEqual(summary["review_count"], 13)
            self.assertAlmostEqual(
                summary["average_rating"],
                expected_average,
                places=4,
            )

        self.assertContains(first, "?page=2")
        self.assertContains(second, "?page=1")

    def test_invalid_review_page_values_are_handled(self):
        for page in ["banana", "999", "-1"]:
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["review_page"].number,
                    1,
                )

    def test_product_and_review_content_is_html_escaped(self):
        unsafe_content = '<script>alert("bad")</script>'

        self.product.description = unsafe_content
        self.product.save(update_fields=["description"])

        self.approved_one.title = "<b>Unsafe title</b>"
        self.approved_one.body = unsafe_content
        self.approved_one.save(update_fields=["title", "body"])

        response = self.client.get(self.url)

        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(
            response,
            "&lt;b&gt;Unsafe title&lt;/b&gt;",
        )
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, "<b>Unsafe title</b>")