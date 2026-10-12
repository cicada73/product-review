from django.contrib import admin

from .models import ModerationAction, ReviewReport


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReviewReport)
class ReviewReportAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "review",
        "reporter",
        "reason",
        "status",
        "created_at",
        "resolved_by",
    )
    list_filter = ("status", "reason")
    search_fields = (
        "review__title",
        "review__product__name",
        "reporter__username",
    )
    list_select_related = (
        "review__product",
        "review__author",
        "reporter",
        "resolved_by",
    )
    readonly_fields = [
        field.name for field in ReviewReport._meta.fields
    ]


@admin.register(ModerationAction)
class ModerationActionAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "action",
        "actor",
        "review",
        "report",
        "target_user",
        "created_at",
    )
    list_filter = ("action",)
    search_fields = (
        "actor__username",
        "target_user__username",
        "review__title",
        "reason",
    )
    list_select_related = (
        "actor",
        "review__product",
        "review__author",
        "report",
        "target_user",
    )
    readonly_fields = [
        field.name for field in ModerationAction._meta.fields
    ]