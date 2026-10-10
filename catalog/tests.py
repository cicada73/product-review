from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from io import StringIO

from .models import Category, Product

from django.core.management import call_command


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