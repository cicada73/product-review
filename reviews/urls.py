from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path(
        "products/<slug:slug>/new/",
        views.review_create,
        name="review_create",
    ),
    path(
        "<int:pk>/edit/",
        views.review_edit,
        name="review_edit",
    ),
    path("", views.my_reviews, name="my_reviews"),
]