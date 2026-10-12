from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.db.models import Q

from django.contrib.auth import get_user_model

from reviews.models import Review

from .forms import (
    AccountDecisionForm,
    ReportDecisionForm,
    ReviewDecisionForm,
    ReviewReportForm,
)
from .services import (
    change_account_state,
    decide_report,
    moderate_review,
    report_review,
)
from .models import ReviewReport



@login_required
@permission_required("moderation.moderate_reviews", raise_exception=True)
@require_GET
def review_queue(request):
    selected_status = request.GET.get("status", "pending")

    if selected_status not in [*Review.Status.values, "all"]:
        raise Http404("Unknown review status.")

    reviews = (
        Review.objects.select_related("product", "author")
        .exclude(author=request.user)
        .order_by("created_at", "id")
    )

    if selected_status != "all":
        reviews = reviews.filter(status=selected_status)

    paginator = Paginator(reviews, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "moderation/review_queue.html",
        {
            "page_obj": page_obj,
            "statuses": Review.Status.choices,
            "selected_status": selected_status,
        },
    )


@login_required
@permission_required("moderation.moderate_reviews", raise_exception=True)
@require_http_methods(["GET", "POST"])
def review_decision(request, pk):
    review = get_object_or_404(
        Review.objects.select_related("product", "author"),
        pk=pk,
    )

    if review.author_id == request.user.pk:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("You cannot moderate your own review.")

    form = ReviewDecisionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_updated_at": review.updated_at.isoformat(),
        },
    )

    if request.method == "POST" and form.is_valid():
        try:
            moderate_review(
                actor=request.user,
                review_id=review.pk,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data["reason"],
                expected_updated_at=form.cleaned_data[
                    "expected_updated_at"
                ],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "The review decision was saved and recorded.",
            )
            return redirect("moderation:review_queue")

    return render(
        request,
        "moderation/review_decision.html",
        {
            "review": review,
            "form": form,
        },
    )

@login_required
@require_http_methods(["GET", "POST"])
def report_create(request, pk):
    review = get_object_or_404(
        Review.objects.select_related("product", "author"),
        pk=pk,
        status=Review.Status.APPROVED,
        product__is_active=True,
    )

    if review.author_id == request.user.pk:
        raise PermissionDenied("You cannot report your own review.")

    if ReviewReport.objects.filter(
        reporter=request.user,
        review=review,
    ).exists():
        messages.info(
            request,
            "You have already reported this review.",
        )
        return redirect(
            "catalog:product_detail",
            slug=review.product.slug,
        )

    form = ReviewReportForm(
        request.POST if request.method == "POST" else None,
    )

    if request.method == "POST" and form.is_valid():
        try:
            _, created = report_review(
                reporter=request.user,
                review_id=review.pk,
                reason=form.cleaned_data["reason"],
                details=form.cleaned_data["details"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if created:
                messages.success(
                    request,
                    "Your report was submitted for moderator review.",
                )
            else:
                messages.info(
                    request,
                    "You have already reported this review.",
                )

            return redirect(
                "catalog:product_detail",
                slug=review.product.slug,
            )

    return render(
        request,
        "moderation/report_form.html",
        {
            "review": review,
            "form": form,
        },
    )

@login_required
@permission_required("moderation.manage_reports", raise_exception=True)
@require_GET
def report_queue(request):
    selected_status = request.GET.get("status", "open")

    if selected_status not in [*ReviewReport.Status.values, "all"]:
        raise Http404("Unknown report status.")

    reports = (
        ReviewReport.objects.select_related(
            "review__product",
            "review__author",
            "reporter",
            "resolved_by",
        )
        .exclude(
            Q(reporter=request.user)
            | Q(review__author=request.user)
        )
        .order_by("created_at", "id")
    )

    if selected_status != "all":
        reports = reports.filter(status=selected_status)

    paginator = Paginator(reports, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "moderation/report_queue.html",
        {
            "page_obj": page_obj,
            "statuses": ReviewReport.Status.choices,
            "selected_status": selected_status,
        },
    )


@login_required
@permission_required("moderation.manage_reports", raise_exception=True)
@require_http_methods(["GET", "POST"])
def report_decision(request, pk):
    report = get_object_or_404(
        ReviewReport.objects.select_related(
            "review__product",
            "review__author",
            "reporter",
            "resolved_by",
        ),
        pk=pk,
    )

    if request.user.pk in [
        report.reporter_id,
        report.review.author_id,
    ]:
        raise PermissionDenied(
            "You cannot decide your own report "
            "or a report about your own review."
        )

    form = ReportDecisionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_updated_at": report.updated_at.isoformat(),
            "expected_review_updated_at": (
                report.review.updated_at.isoformat()
            ),
        },
    )

    if request.method == "POST" and form.is_valid():
        try:
            decide_report(
                actor=request.user,
                report_id=report.pk,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data["reason"],
                expected_updated_at=form.cleaned_data[
                    "expected_updated_at"
                ],
                expected_review_updated_at=form.cleaned_data[
                    "expected_review_updated_at"
                ],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "The report outcome was saved and recorded.",
            )
            return redirect("moderation:report_queue")

    return render(
        request,
        "moderation/report_decision.html",
        {
            "report": report,
            "form": form,
        },
    )

@login_required
@permission_required("moderation.suspend_users", raise_exception=True)
@require_GET
def account_list(request):
    User = get_user_model()

    selected_state = request.GET.get("state", "active")
    query = request.GET.get("q", "").strip()[:200]

    if selected_state not in ["active", "suspended", "all"]:
        raise Http404("Unknown account state.")

    accounts = (
        User.objects.filter(is_staff=False, is_superuser=False)
        .exclude(pk=request.user.pk)
        .order_by("username", "id")
    )

    if selected_state != "all":
        accounts = accounts.filter(
            is_active=selected_state == "active",
        )

    if query:
        accounts = accounts.filter(username__icontains=query)

    paginator = Paginator(accounts, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "moderation/account_list.html",
        {
            "page_obj": page_obj,
            "selected_state": selected_state,
            "query": query,
        },
    )


@login_required
@permission_required("moderation.suspend_users", raise_exception=True)
@require_http_methods(["GET", "POST"])
def account_decision(request, pk):
    User = get_user_model()
    account = get_object_or_404(User, pk=pk)

    if (
        account.pk == request.user.pk
        or account.is_staff
        or account.is_superuser
    ):
        raise PermissionDenied(
            "This account is protected from this workflow."
        )

    form = AccountDecisionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_session_version": account.session_version,
        },
    )

    if request.method == "POST" and form.is_valid():
        try:
            change_account_state(
                actor=request.user,
                user_id=account.pk,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data["reason"],
                expected_session_version=form.cleaned_data[
                    "expected_session_version"
                ],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "The account action was saved and recorded.",
            )
            return redirect("moderation:account_list")

    return render(
        request,
        "moderation/account_decision.html",
        {
            "account": account,
            "form": form,
        },
    )