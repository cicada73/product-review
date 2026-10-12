from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "author",
        "rating",
        "status",
        "created_at",
    )
    list_filter = ("status", "rating")
    search_fields = ("title", "product__name", "author__username")
    list_select_related = ("product", "author")
    readonly_fields = [
        field.name for field in Review._meta.fields
    ]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False