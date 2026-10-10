from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "author",
        "product",
        "rating",
        "status",
        "created_at",
    ]
    list_filter = ["status", "rating"]
    search_fields = [
        "title",
        "body",
        "author__username",
        "product__name",
    ]
    list_select_related = ["author", "product"]
    readonly_fields = ["created_at", "updated_at"]