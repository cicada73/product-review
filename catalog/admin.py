from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "brand",
        "category",
        "is_active",
        "created_at",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "brand", "description"]
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ["category"]
    readonly_fields = ["created_at", "updated_at"]