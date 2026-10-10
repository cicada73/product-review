from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from catalog.models import Category, Product

from .models import Review


User = get_user_model()


class ReviewModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(
            username="reviewer",
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