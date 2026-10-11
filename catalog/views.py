from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .models import Category, Product
from reviews.models import Review


@require_GET
def product_list(request):
    query = request.GET.get("q", "").strip()[:200]
    category_slug = request.GET.get("category", "").strip()

    products = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .annotate(
            average_rating=Avg(
                "reviews__rating",
                filter=Q(reviews__status=Review.Status.APPROVED),
            ),
            review_count=Count(
                 "reviews",
                filter=Q(reviews__status=Review.Status.APPROVED),
            ),
        )
        .order_by("name", "id")
    )

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(brand__icontains=query)
            | Q(description__icontains=query)
        )

    selected_category = ""

    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)
        selected_category = category.slug

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "catalog/product_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "categories": Category.objects.order_by("name"),
            "selected_category": selected_category,
        },
    )

@require_GET
def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category"),
        slug=slug,
        is_active=True,
    )

    approved_reviews = (
        Review.objects.filter(
            product=product,
            status=Review.Status.APPROVED,
        )
        .select_related("author")
        .order_by("-created_at", "-id")
    )

    rating_summary = approved_reviews.aggregate(
        average_rating=Avg("rating"),
        review_count=Count("id"),
    )

    paginator = Paginator(approved_reviews, 10)
    review_page = paginator.get_page(request.GET.get("page"))

    user_review = None

    if request.user.is_authenticated:
        user_review = Review.objects.filter(
            product=product,
            author=request.user,
        ).first()

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "rating_summary": rating_summary,
            "review_page": review_page,
            "user_review": user_review,
        },
    )