from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from catalog.models import Product

from .forms import ReviewForm
from .models import Review

from django.core.paginator import Paginator


@login_required
@require_http_methods(["GET", "POST"])
def review_create(request, slug):
    product = get_object_or_404(
        Product,
        slug=slug,
        is_active=True,
    )

    existing_reviews = Review.objects.filter(
        author=request.user,
        product=product,
    )

    if existing_reviews.exists():
        messages.info(
            request,
            "You have already reviewed this product.",
        )
        return redirect("catalog:product_detail", slug=product.slug)

    form = ReviewForm(
        request.POST if request.method == "POST" else None,
    )

    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.author = request.user
        review.product = product
        review.status = Review.Status.PENDING

        try:
            with transaction.atomic():
                review.save()
        except IntegrityError:
            # Handle another submission arriving at the same time.
            if not existing_reviews.exists():
                raise

            messages.info(
                request,
                "You have already reviewed this product.",
            )
        else:
            messages.success(
                request,
                "Your review was submitted and is awaiting approval.",
            )

        return redirect("catalog:product_detail", slug=product.slug)

    return render(
        request,
        "reviews/review_form.html",
        {
            "form": form,
            "product": product,
        },
    )

@login_required
@require_http_methods(["GET", "POST"])
def review_edit(request, pk):
    review = get_object_or_404(
        Review.objects.select_related("product"),
        pk=pk,
        author=request.user,
        product__is_active=True,
    )

    form = ReviewForm(
        request.POST if request.method == "POST" else None,
        instance=review,
    )

    if request.method == "POST" and form.is_valid():
        updated_review = form.save(commit=False)
        updated_review.status = Review.Status.PENDING
        updated_review.save(
            update_fields=[
                "rating",
                "title",
                "body",
                "status",
                "updated_at",
            ],
        )

        messages.success(
            request,
            "Your review was updated and is awaiting approval.",
        )
        return redirect(
            "catalog:product_detail",
            slug=review.product.slug,
        )

    return render(
        request,
        "reviews/review_form.html",
        {
            "form": form,
            "product": review.product,
            "is_edit": True,
        },
    )

@login_required
@require_GET
def my_reviews(request):
    reviews = (
        Review.objects.filter(author=request.user)
        .select_related("product")
        .order_by("-updated_at", "-id")
    )

    paginator = Paginator(reviews, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "reviews/my_reviews.html",
        {"page_obj": page_obj},
    )