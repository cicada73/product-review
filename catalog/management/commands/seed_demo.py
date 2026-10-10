from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, Product


DEMO_CATALOG = [
    {
        "name": "Electronics",
        "slug": "electronics",
        "description": "Electronic devices and accessories.",
        "products": [
            {
                "name": "Wireless Headphones",
                "slug": "wireless-headphones",
                "brand": "Demo Brand",
                "description": "Comfortable wireless headphones for everyday listening.",
            },
            {
                "name": "Portable Speaker",
                "slug": "portable-speaker",
                "brand": "Demo Brand",
                "description": "A compact speaker for listening at home or on the go.",
            },
        ],
    },
    {
        "name": "Books",
        "slug": "books",
        "description": "Books for learning and leisure.",
        "products": [
            {
                "name": "Python for Beginners",
                "slug": "python-for-beginners",
                "brand": "Demo Publisher",
                "description": "An introductory guide to Python programming.",
            },
            {
                "name": "Everyday Cooking",
                "slug": "everyday-cooking",
                "brand": "Demo Publisher",
                "description": "Simple recipes for everyday meals.",
            },
        ],
    },
    {
        "name": "Home and Lifestyle",
        "slug": "home-and-lifestyle",
        "description": "Useful products for everyday living.",
        "products": [
            {
                "name": "Insulated Water Bottle",
                "slug": "insulated-water-bottle",
                "brand": "Demo Home",
                "description": "A reusable insulated bottle for hot and cold drinks.",
            },
            {
                "name": "Desk Lamp",
                "slug": "desk-lamp",
                "brand": "Demo Home",
                "description": "An adjustable lamp for reading and desk work.",
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Add sample categories and products without changing existing records."

    @transaction.atomic
    def handle(self, *args, **options):
        categories_created = 0
        products_created = 0

        for category_data in DEMO_CATALOG:
            category, created = Category.objects.get_or_create(
                slug=category_data["slug"],
                defaults={
                    "name": category_data["name"],
                    "description": category_data["description"],
                },
            )
            categories_created += int(created)

            for product_data in category_data["products"]:
                _, created = Product.objects.get_or_create(
                    slug=product_data["slug"],
                    defaults={
                        "category": category,
                        "name": product_data["name"],
                        "brand": product_data["brand"],
                        "description": product_data["description"],
                    },
                )
                products_created += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {categories_created} categories "
                f"and {products_created} products created."
            )
        )