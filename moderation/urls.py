from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("", views.review_queue, name="review_queue"),
    path(
        "reviews/<int:pk>/",
        views.review_decision,
        name="review_decision",
    ),
        path(
        "reviews/<int:pk>/report/",
        views.report_create,
        name="report_create",
    ),
        path(
        "reports/",
        views.report_queue,
        name="report_queue",
    ),
    path(
        "reports/<int:pk>/",
        views.report_decision,
        name="report_decision",
    ),
        path(
        "accounts/",
        views.account_list,
        name="account_list",
    ),
    path(
        "accounts/<int:pk>/",
        views.account_decision,
        name="account_decision",
    ),
]