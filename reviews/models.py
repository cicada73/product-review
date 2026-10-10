from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Review(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "product"],
                name="unique_review_author_product",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["pending", "approved", "rejected"],
                ),
                name="review_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["product", "status", "created_at"],
                name="review_product_status_idx",
            ),
            models.Index(
                fields=["status", "created_at"],
                name="review_status_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.product} — {self.rating}/5"