from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from catalog.models import Category, Product

from .models import Review

from django.test import Client
from django.urls import reverse

from .forms import ReviewForm


User = get_user_model()


class ReviewModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(
            username="reviewer",
            email="review-author@example.com",
            password="TestOnlyPassword123!",
        )
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

    def create_review(self, **overrides):
        values = {
            "author": self.author,
            "product": self.product,
            "rating": 4,
            "title": "Comfortable headphones",
            "body": "Comfortable to wear with clear sound.",
        }
        values.update(overrides)
        return Review.objects.create(**values)

    def test_new_review_defaults_to_pending(self):
        review = self.create_review()

        review.refresh_from_db()
        self.assertEqual(review.status, Review.Status.PENDING)

    def test_duplicate_author_and_product_is_rejected(self):
        self.create_review()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_review(title="Duplicate review")

    def test_database_rejects_ratings_outside_allowed_range(self):
        for rating in [0, 6]:
            with self.subTest(rating=rating):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_review(rating=rating)

    def test_database_rejects_invalid_status(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_review(status="invalid")

    def test_different_users_can_review_same_product(self):
        self.create_review()

        another_author = User.objects.create_user(
            username="another-reviewer",
            email="another-review-author@example.com",
            password="TestOnlyPassword123!",
        )
        self.create_review(author=another_author)

        self.assertEqual(
            Review.objects.filter(product=self.product).count(),
            2,
        )

    def test_same_user_can_review_different_products(self):
        self.create_review()

        another_product = Product.objects.create(
            category=self.category,
            name="Portable Speaker",
            slug="portable-speaker",
            description="Sample speaker.",
        )
        self.create_review(product=another_product)

        self.assertEqual(
            Review.objects.filter(author=self.author).count(),
            2,
        )

    def test_product_with_reviews_cannot_be_deleted(self):
        self.create_review()

        with self.assertRaises(ProtectedError):
            self.product.delete()

        self.assertTrue(
            Product.objects.filter(pk=self.product.pk).exists()
        )
        self.assertEqual(Review.objects.count(), 1)

    def test_author_with_reviews_cannot_be_deleted(self):
        self.create_review()

        with self.assertRaises(ProtectedError):
            self.author.delete()

        self.assertTrue(
            User.objects.filter(pk=self.author.pk).exists()
        )
        self.assertEqual(Review.objects.count(), 1)

class ReviewFormTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            "rating": "4",
            "title": "A useful product",
            "body": "This product worked well during everyday use.",
        }
        data.update(overrides)
        return data

    def test_valid_form(self):
        form = ReviewForm(data=self.valid_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["rating"], 4)

    def test_all_five_ratings_are_accepted(self):
        for rating in range(1, 6):
            with self.subTest(rating=rating):
                form = ReviewForm(
                    data=self.valid_data(rating=str(rating)),
                )

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["rating"], rating)

    def test_invalid_ratings_are_rejected(self):
        for rating in ["", "0", "6", "1.5", "invalid"]:
            with self.subTest(rating=rating):
                form = ReviewForm(
                    data=self.valid_data(rating=rating),
                )

                self.assertFalse(form.is_valid())
                self.assertIn("rating", form.errors)

    def test_title_length_is_validated(self):
        for title in ["", "abcd", "a" * 201, " " * 10]:
            with self.subTest(title_length=len(title)):
                form = ReviewForm(
                    data=self.valid_data(title=title),
                )

                self.assertFalse(form.is_valid())
                self.assertIn("title", form.errors)

    def test_body_length_is_validated(self):
        for body in ["", "Too short", "a" * 5001, " " * 25]:
            with self.subTest(body_length=len(body)):
                form = ReviewForm(
                    data=self.valid_data(body=body),
                )

                self.assertFalse(form.is_valid())
                self.assertIn("body", form.errors)

    def test_text_is_trimmed(self):
        form = ReviewForm(
            data=self.valid_data(
                title="  A useful product  ",
                body="  This product worked well during everyday use.  ",
            ),
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["title"], "A useful product")
        self.assertEqual(
            form.cleaned_data["body"],
            "This product worked well during everyday use.",
        )

    def test_only_review_content_fields_are_editable(self):
        self.assertEqual(
            set(ReviewForm().fields),
            {"rating", "title", "body"},
        )

class ReviewCreateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="submission-author",
            email="submission-author@example.com",
        )
        cls.other_author = User.objects.create_user(
            username="other-submission-author",
            email="other-submission-author@example.com",
        )

        cls.category = Category.objects.create(
            name="Submission Electronics",
            slug="submission-electronics",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Submission Product",
            slug="submission-product",
        )
        cls.other_product = Product.objects.create(
            category=cls.category,
            name="Other Submission Product",
            slug="other-submission-product",
        )
        cls.hidden_product = Product.objects.create(
            category=cls.category,
            name="Hidden Submission Product",
            slug="hidden-submission-product",
            is_active=False,
        )

        cls.url = reverse(
            "reviews:review_create",
            kwargs={"slug": cls.product.slug},
        )
        cls.detail_url = reverse(
            "catalog:product_detail",
            kwargs={"slug": cls.product.slug},
        )

    def setUp(self):
        self.client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "rating": "4",
            "title": "A useful product",
            "body": "This product worked well during everyday use.",
        }
        data.update(overrides)
        return data

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={self.url}",
                )

        self.assertEqual(Review.objects.count(), 0)

    def test_get_shows_form_without_creating_review(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/review_form.html")
        self.assertIsInstance(response.context["form"], ReviewForm)
        self.assertEqual(response.context["product"].pk, self.product.pk)
        self.assertEqual(Review.objects.count(), 0)

    def test_valid_submission_creates_pending_review(self):
        response = self.client.post(self.url, self.valid_data())

        self.assertRedirects(response, self.detail_url)

        review = Review.objects.get()
        self.assertEqual(review.author_id, self.author.pk)
        self.assertEqual(review.product_id, self.product.pk)
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.status, Review.Status.PENDING)

        public_page = self.client.get(self.detail_url)
        self.assertNotContains(public_page, review.title)
        self.assertEqual(
            public_page.context["rating_summary"]["review_count"],
            0,
        )

    def test_submitted_author_product_and_status_are_ignored(self):
        response = self.client.post(
            self.url,
            self.valid_data(
                author=str(self.other_author.pk),
                product=str(self.other_product.pk),
                status=Review.Status.APPROVED,
            ),
        )

        self.assertRedirects(response, self.detail_url)

        review = Review.objects.get()
        self.assertEqual(review.author_id, self.author.pk)
        self.assertEqual(review.product_id, self.product.pk)
        self.assertEqual(review.status, Review.Status.PENDING)

    def test_invalid_submission_does_not_create_review(self):
        invalid_cases = [
            ("rating", "0"),
            ("title", "abcd"),
            ("body", "Too short"),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                response = self.client.post(
                    self.url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(Review.objects.count(), 0)

    def test_duplicate_submission_does_not_overwrite_review(self):
        original = Review.objects.create(
            author=self.author,
            product=self.product,
            rating=3,
            title="Original review title",
            body="Original review content that must remain unchanged.",
            status=Review.Status.APPROVED,
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    self.valid_data(),
                )

                self.assertRedirects(response, self.detail_url)

        self.assertEqual(Review.objects.count(), 1)

        original.refresh_from_db()
        self.assertEqual(original.rating, 3)
        self.assertEqual(original.title, "Original review title")
        self.assertEqual(original.status, Review.Status.APPROVED)

    def test_inactive_product_returns_404(self):
        url = reverse(
            "reviews:review_create",
            kwargs={"slug": self.hidden_product.slug},
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    self.valid_data(),
                )
                self.assertEqual(response.status_code, 404)

        self.assertEqual(Review.objects.count(), 0)

    def test_unknown_product_returns_404(self):
        url = reverse(
            "reviews:review_create",
            kwargs={"slug": "nonexistent-product"},
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    self.valid_data(),
                )
                self.assertEqual(response.status_code, 404)

    def test_unsupported_methods_are_rejected(self):
        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)
                self.assertEqual(response.status_code, 405)

        self.assertEqual(Review.objects.count(), 0)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.url, self.valid_data())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Review.objects.count(), 0)

        client.get(self.url)
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            self.url,
            self.valid_data(csrfmiddlewaretoken=csrf_token),
        )

        self.assertRedirects(response, self.detail_url)
        self.assertEqual(Review.objects.count(), 1)

class ReviewEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="edit-author",
            email="edit-author@example.com",
        )
        cls.other_author = User.objects.create_user(
            username="other-edit-author",
            email="other-edit-author@example.com",
        )

        cls.category = Category.objects.create(
            name="Edit Electronics",
            slug="edit-electronics",
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Edit Product",
            slug="edit-product",
        )
        cls.other_product = Product.objects.create(
            category=cls.category,
            name="Other Edit Product",
            slug="other-edit-product",
        )

        cls.review = Review.objects.create(
            author=cls.author,
            product=cls.product,
            rating=5,
            title="Original review title",
            body="Original review content that must remain unchanged.",
            status=Review.Status.APPROVED,
        )

        cls.url = reverse(
            "reviews:review_edit",
            kwargs={"pk": cls.review.pk},
        )
        cls.detail_url = reverse(
            "catalog:product_detail",
            kwargs={"slug": cls.product.slug},
        )

    def setUp(self):
        self.client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def valid_data(self, **overrides):
        data = {
            "rating": "2",
            "title": "Updated review title",
            "body": "Updated experience after using this product longer.",
        }
        data.update(overrides)
        return data

    def assert_original_unchanged(self):
        self.review.refresh_from_db()

        self.assertEqual(self.review.author_id, self.author.pk)
        self.assertEqual(self.review.product_id, self.product.pk)
        self.assertEqual(self.review.rating, 5)
        self.assertEqual(self.review.title, "Original review title")
        self.assertEqual(
            self.review.body,
            "Original review content that must remain unchanged.",
        )
        self.assertEqual(self.review.status, Review.Status.APPROVED)

    def test_anonymous_requests_redirect_to_login(self):
        self.client.logout()

        for method in ["get", "post"]:
            with self.subTest(method=method):
                if method == "get":
                    response = self.client.get(self.url)
                else:
                    response = self.client.post(
                        self.url,
                        self.valid_data(),
                    )

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={self.url}",
                )

        self.assert_original_unchanged()

    def test_get_prefills_existing_review(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/review_form.html")
        self.assertTrue(response.context["is_edit"])

        form = response.context["form"]
        self.assertEqual(form.instance.pk, self.review.pk)
        self.assertEqual(form.initial["rating"], 5)
        self.assertEqual(form.initial["title"], self.review.title)
        self.assertEqual(form.initial["body"], self.review.body)

        self.assert_original_unchanged()

    def test_editing_any_status_returns_review_to_pending(self):
        for status in [
            Review.Status.APPROVED,
            Review.Status.REJECTED,
            Review.Status.PENDING,
        ]:
            with self.subTest(original_status=status):
                Review.objects.filter(pk=self.review.pk).update(
                    status=status,
                )

                response = self.client.post(
                    self.url,
                    self.valid_data(),
                )

                self.assertRedirects(response, self.detail_url)

                self.review.refresh_from_db()
                self.assertEqual(self.review.rating, 2)
                self.assertEqual(
                    self.review.title,
                    "Updated review title",
                )
                self.assertEqual(
                    self.review.body,
                    "Updated experience after using this product longer.",
                )
                self.assertEqual(
                    self.review.status,
                    Review.Status.PENDING,
                )
                self.assertEqual(Review.objects.count(), 1)

                public_page = self.client.get(self.detail_url)
                self.assertNotContains(public_page, self.review.title)
                self.assertEqual(
                    public_page.context["rating_summary"]["review_count"],
                    0,
                )

    def test_other_user_cannot_view_or_edit_review(self):
        self.client.force_login(
            self.other_author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    self.valid_data(),
                )

                self.assertEqual(response.status_code, 404)

        self.assert_original_unchanged()

    def test_author_product_and_approval_cannot_be_changed_by_post(self):
        response = self.client.post(
            self.url,
            self.valid_data(
                author=str(self.other_author.pk),
                product=str(self.other_product.pk),
                status=Review.Status.APPROVED,
            ),
        )

        self.assertRedirects(response, self.detail_url)

        self.review.refresh_from_db()
        self.assertEqual(self.review.author_id, self.author.pk)
        self.assertEqual(self.review.product_id, self.product.pk)
        self.assertEqual(self.review.status, Review.Status.PENDING)
        self.assertEqual(self.review.rating, 2)

    def test_invalid_edit_keeps_published_review_unchanged(self):
        invalid_cases = [
            ("rating", "6"),
            ("title", "abcd"),
            ("body", "Too short"),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                response = self.client.post(
                    self.url,
                    self.valid_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assert_original_unchanged()

    def test_inactive_product_cannot_be_edited(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    self.valid_data(),
                )

                self.assertEqual(response.status_code, 404)

        self.assert_original_unchanged()

    def test_unknown_review_returns_404(self):
        missing_pk = self.review.pk + 1000
        url = reverse(
            "reviews:review_edit",
            kwargs={"pk": missing_pk},
        )

        for method in ["get", "post"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    self.valid_data(),
                )

                self.assertEqual(response.status_code, 404)

    def test_csrf_token_is_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = client.post(self.url, self.valid_data())

        self.assertEqual(response.status_code, 403)
        self.assert_original_unchanged()

        client.get(self.url)
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            self.url,
            self.valid_data(csrfmiddlewaretoken=csrf_token),
        )

        self.assertRedirects(response, self.detail_url)

        self.review.refresh_from_db()
        self.assertEqual(self.review.rating, 2)
        self.assertEqual(self.review.status, Review.Status.PENDING)

    def test_unsupported_methods_are_rejected(self):
        for method in ["put", "delete"]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)

                self.assertEqual(response.status_code, 405)

        self.assert_original_unchanged()

class MyReviewsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.author = User.objects.create_user(
            username="dashboard-author",
            email="dashboard-author@example.com",
        )
        cls.other_author = User.objects.create_user(
            username="other-dashboard-author",
            email="other-dashboard-author@example.com",
        )
        cls.empty_author = User.objects.create_user(
            username="empty-dashboard-author",
            email="empty-dashboard-author@example.com",
        )

        cls.category = Category.objects.create(
            name="Dashboard Electronics",
            slug="dashboard-electronics",
        )

        cls.products = [
            Product.objects.create(
                category=cls.category,
                name=f"Dashboard Product {number}",
                slug=f"dashboard-product-{number}",
            )
            for number in range(4)
        ]

        cls.own_reviews = []

        for number, status in enumerate([
            Review.Status.PENDING,
            Review.Status.APPROVED,
            Review.Status.REJECTED,
        ]):
            review = Review.objects.create(
                author=cls.author,
                product=cls.products[number],
                rating=4,
                title=f"Dashboard own review {number}",
                body="My private dashboard review content.",
                status=status,
            )
            cls.own_reviews.append(review)

        cls.other_review = Review.objects.create(
            author=cls.other_author,
            product=cls.products[3],
            rating=2,
            title="Other author's private review",
            body="Private content belonging to another account.",
            status=Review.Status.PENDING,
        )

        cls.url = reverse("reviews:my_reviews")

    def setUp(self):
        self.client.force_login(
            self.author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

    def test_anonymous_dashboard_redirects_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={self.url}",
        )

    def test_dashboard_shows_only_own_reviews_in_all_statuses(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/my_reviews.html")
        self.assertEqual(response.context["page_obj"].paginator.count, 3)

        actual_ids = {
            review.pk for review in response.context["page_obj"]
        }
        self.assertEqual(
            actual_ids,
            {review.pk for review in self.own_reviews},
        )

        for review in self.own_reviews:
            self.assertContains(response, review.title)
            self.assertContains(
                response,
                f"Status: {review.get_status_display()}",
            )

        self.assertNotContains(response, self.other_review.title)
        self.assertNotContains(response, self.other_review.body)

    def test_empty_dashboard_shows_product_link(self):
        self.client.force_login(
            self.empty_author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertContains(
            response,
            "You haven’t submitted any reviews yet.",
        )
        self.assertContains(
            response,
            reverse("catalog:product_list"),
        )

    def test_inactive_product_review_remains_visible_without_links(self):
        product = self.products[0]
        product.is_active = False
        product.save(update_fields=["is_active"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.name)
        self.assertContains(response, self.own_reviews[0].title)
        self.assertContains(
            response,
            "This product is currently unavailable.",
        )

        self.assertNotContains(
            response,
            reverse(
                "reviews:review_edit",
                kwargs={"pk": self.own_reviews[0].pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "catalog:product_detail",
                kwargs={"slug": product.slug},
            ),
        )

    def test_pagination_includes_all_own_reviews_without_duplicates(self):
        for number in range(11):
            product = Product.objects.create(
                category=self.category,
                name=f"Dashboard Paging Product {number}",
                slug=f"dashboard-paging-product-{number}",
            )
            Review.objects.create(
                author=self.author,
                product=product,
                rating=3,
                title=f"Dashboard paging review {number}",
                body="Additional content for dashboard pagination.",
            )

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})

        first_ids = [
            review.pk for review in first.context["page_obj"]
        ]
        second_ids = [
            review.pk for review in second.context["page_obj"]
        ]

        self.assertEqual(len(first_ids), 10)
        self.assertEqual(len(second_ids), 4)
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        expected_ids = list(
            Review.objects.filter(author=self.author)
            .order_by("-updated_at", "-id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(first_ids + second_ids, expected_ids)
        self.assertNotIn(self.other_review.pk, first_ids + second_ids)

        self.assertContains(first, "?page=2")
        self.assertContains(second, "?page=1")

    def test_invalid_page_values_are_handled(self):
        for page in ["banana", "999", "-1"]:
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, 1)

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

    def test_dashboard_escapes_review_content(self):
        review = self.own_reviews[0]
        review.title = '<script>alert("title")</script>'
        review.body = '<script>alert("body")</script>'
        review.save(update_fields=["title", "body"])

        response = self.client.get(self.url)

        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")

    def test_homepage_dashboard_link_is_only_shown_when_logged_in(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, self.url)

        self.client.logout()

        response = self.client.get(reverse("home"))
        self.assertNotContains(response, self.url)

    def test_product_page_only_links_to_current_users_review(self):
        product = self.products[0]
        detail_url = reverse(
            "catalog:product_detail",
            kwargs={"slug": product.slug},
        )
        own_edit_url = reverse(
            "reviews:review_edit",
            kwargs={"pk": self.own_reviews[0].pk},
        )
        create_url = reverse(
            "reviews:review_create",
            kwargs={"slug": product.slug},
        )

        response = self.client.get(detail_url)
        self.assertContains(response, own_edit_url)
        self.assertNotContains(response, create_url)

        self.client.force_login(
            self.other_author,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        response = self.client.get(detail_url)
        self.assertContains(response, create_url)
        self.assertNotContains(response, own_edit_url)