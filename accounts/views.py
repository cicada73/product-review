from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required

from .forms import ProfileForm, SignUpForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = SignUpForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error(
                None,
                "This username or email is unavailable. "
                "Please choose another.",
            )
        else:
            login(request,user,backend="django.contrib.auth.backends.ModelBackend",)
            messages.success(request, "Your account has been created.")
            return redirect("home")

    return render(
        request,
        "accounts/signup.html",
        {"form": form},
    )

@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(
        request.POST if request.method == "POST" else None,
        instance=request.user,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/profile.html",
        {"form": form},
    )