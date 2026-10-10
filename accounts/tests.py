from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.conf import settings
from django.shortcuts import resolve_url
from django.urls import reverse
import re
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import (Client as DjangoClient,RequestFactory,TestCase,override_settings,)
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from axes.models import AccessAttempt
from django.utils import timezone


User = get_user_model()

class Client(DjangoClient):
    """Test client compatible with our authentication backends."""

    def login(self, **credentials):
        credentials.setdefault(
            "request",
            RequestFactory().post("/accounts/login/"),
        )
        return super().login(**credentials)

    def force_login(self, user, backend=None):
        return super().force_login(
            user,
            backend=backend or "django.contrib.auth.backends.ModelBackend",
        )


class AccountTestCase(TestCase):
    client_class = Client


class UserModelTests(AccountTestCase):
    def test_duplicate_email_is_rejected_by_database(self):
        User.objects.create_user(
            username="first-user",
            email="shared@example.com",
            password="TestOnlyPassword123!",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="second-user",
                    email="shared@example.com",
                    password="TestOnlyPassword123!",
                )

    def test_email_is_required_during_validation(self):
        user = User(
            username="missing-email",
            email="",
        )
        user.set_password("TestOnlyPassword123!")

        with self.assertRaises(ValidationError) as error:
            user.full_clean()

        self.assertIn("email", error.exception.message_dict)

class SignUpTests(AccountTestCase):
    def setUp(self):
        self.url = reverse("accounts:signup")
        self.data = {
            "username": "new-reviewer",
            "email": "NewReviewer@Example.com",
            "password1": "River!Cabin42Forest9",
            "password2": "River!Cabin42Forest9",
        }

    def test_signup_page_is_accessible(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/signup.html")

    def test_signup_creates_normal_user_and_signs_them_in(self):
        data = {
            **self.data,
            "is_staff": "true",
            "is_superuser": "true",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, reverse("home"))

        user = User.objects.get(username="new-reviewer")

        self.assertEqual(user.email, "newreviewer@example.com")
        self.assertTrue(user.check_password(self.data["password1"]))
        self.assertNotEqual(user.password, self.data["password1"])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(user.pk),
        )

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user(
            username="new-reviewer",
            email="existing@example.com",
            password="River!Cabin42Forest9",
        )

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(
            username="existing-reviewer",
            email="newreviewer@example.com",
            password="River!Cabin42Forest9",
        )

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_mismatched_passwords_are_rejected(self):
        data = {
            **self.data,
            "password2": "Another!StrongPassword42",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_is_rejected(self):
        data = {
            **self.data,
            "password1": "123",
            "password2": "123",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_signup_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(self.url, self.data)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), 0)

class AuthenticationFlowTests(AccountTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "River!Cabin42Forest9"
        cls.user = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password=cls.password,
        )

    def login_data(self, **overrides):
        data = {
            "username": self.user.username,
            "password": self.password,
        }
        data.update(overrides)
        return data

    def test_login_creates_session_that_persists(self):
        response = self.client.post(
            reverse("accounts:login"),
            self.login_data(),
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.user.pk),
        )

        home_response = self.client.get(reverse("home"))

        self.assertTrue(
            home_response.wsgi_request.user.is_authenticated
        )
        self.assertContains(home_response, self.user.username)

    def test_incorrect_password_does_not_sign_user_in(self):
        response = self.client.post(
            reverse("accounts:login"),
            self.login_data(password="WrongPassword!42"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:login"),
            self.login_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_rejects_external_redirect_destination(self):
        response = self.client.post(
            reverse("accounts:login"),
            self.login_data(next="https://example.com/"),
        )

        self.assertRedirects(response, reverse("home"))

    def test_signed_in_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:login"))

        self.assertRedirects(response, reverse("home"))

    def test_logout_ends_session(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(
            response,
            resolve_url(settings.LOGOUT_REDIRECT_URL),
        )
        self.assertNotIn("_auth_user_id", self.client.session)

        home_response = self.client.get(reverse("home"))

        self.assertFalse(
            home_response.wsgi_request.user.is_authenticated
        )

    def test_get_request_cannot_logout_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_requires_valid_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("_auth_user_id", client.session)

        client.get(reverse("home"))
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            reverse("accounts:logout"),
            {"csrfmiddlewaretoken": csrf_token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", client.session)

    def test_regular_user_cannot_access_admin(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            response,
            reverse("admin:login") + "?next=/admin/",
        )

class ProfileTests(AccountTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="River!Cabin42Forest9",
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))

        self.assertRedirects(
            response,
            reverse("accounts:login")
            + "?next="
            + reverse("accounts:profile"),
        )

    def test_user_can_update_their_names(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Alex",
                "last_name": "Taylor",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alex")
        self.assertEqual(self.user.last_name, "Taylor")

    def test_profile_ignores_account_and_privilege_fields(self):
        other_user = User.objects.create_user(
            username="other-profile-user",
            email="other-profile@example.com",
            first_name="Original",
            password="River!Cabin42Forest9",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Updated",
                "last_name": "Name",
                "user_id": other_user.pk,
                "username": "changed-username",
                "email": "changed@example.com",
                "is_staff": "true",
                "is_superuser": "true",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))

        self.user.refresh_from_db()
        other_user.refresh_from_db()

        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.username, "profile-user")
        self.assertEqual(self.user.email, "profile@example.com")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(other_user.first_name, "Original")

    def test_profile_update_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Unauthorized",
                "last_name": "Update",
            },
        )

        self.assertEqual(response.status_code, 403)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")

class PasswordChangeTests(AccountTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_password = "River!Cabin42Forest9"
        cls.new_password = "Mountain!Lake73Trail8"
        cls.user = User.objects.create_user(
            username="password-user",
            email="password@example.com",
            password=cls.old_password,
        )

    def password_data(self, **overrides):
        data = {
            "old_password": self.old_password,
            "new_password1": self.new_password,
            "new_password2": self.new_password,
        }
        data.update(overrides)
        return data

    def test_password_change_requires_login(self):
        response = self.client.get(
            reverse("accounts:password_change")
        )

        self.assertRedirects(
            response,
            reverse("accounts:login")
            + "?next="
            + reverse("accounts:password_change"),
        )

    def test_incorrect_current_password_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:password_change"),
            self.password_data(old_password="WrongPassword!42"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "old_password",
            response.context["form"].errors,
        )

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password(self.old_password)
        )

    def test_invalid_new_passwords_are_rejected(self):
        self.client.force_login(self.user)

        invalid_passwords = [
            (self.new_password, "Different!Password42"),
            ("123", "123"),
        ]

        for first, second in invalid_passwords:
            with self.subTest(first=first, second=second):
                response = self.client.post(
                    reverse("accounts:password_change"),
                    self.password_data(
                        new_password1=first,
                        new_password2=second,
                    ),
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)

                self.user.refresh_from_db()
                self.assertTrue(
                    self.user.check_password(self.old_password)
                )

    def test_password_change_preserves_current_session_only(self):
        self.client.force_login(self.user)

        other_client = Client()
        self.assertTrue(
            other_client.login(
                username=self.user.username,
                password=self.old_password,
            )
        )

        response = self.client.post(
            reverse("accounts:password_change"),
            self.password_data(),
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_change_done"),
        )

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password(self.new_password)
        )
        self.assertFalse(
            self.user.check_password(self.old_password)
        )

        current_response = self.client.get(
            reverse("accounts:profile")
        )
        self.assertTrue(
            current_response.wsgi_request.user.is_authenticated
        )

        other_response = other_client.get(reverse("home"))
        self.assertFalse(
            other_response.wsgi_request.user.is_authenticated
        )

        self.client.logout()

        self.assertFalse(
            self.client.login(
                username=self.user.username,
                password=self.old_password,
            )
        )
        self.assertTrue(
            self.client.login(
                username=self.user.username,
                password=self.new_password,
            )
        )

    def test_password_change_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            reverse("accounts:password_change"),
            self.password_data(),
        )

        self.assertEqual(response.status_code, 403)

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password(self.old_password)
        )

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordResetTests(AccountTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_password = "River!Cabin42Forest9"
        cls.new_password = "Mountain!Lake73Trail8"
        cls.user = User.objects.create_user(
            username="reset-user",
            email="reset@example.com",
            password=cls.old_password,
        )

    def reset_url(self, token=None):
        return reverse(
            "accounts:password_reset_confirm",
            kwargs={
                "uidb64": urlsafe_base64_encode(
                    force_bytes(self.user.pk)
                ),
                "token": (
                    token
                    if token is not None
                    else default_token_generator.make_token(self.user)
                ),
            },
        )

    def password_data(self, **overrides):
        data = {
            "new_password1": self.new_password,
            "new_password2": self.new_password,
        }
        data.update(overrides)
        return data

    def complete_reset(self):
        self.user.refresh_from_db()
        original_url = self.reset_url()

        response = self.client.get(original_url, follow=True)
        self.assertTrue(response.context["validlink"])

        confirmation_path = response.request["PATH_INFO"]
        response = self.client.post(
            confirmation_path,
            self.password_data(),
        )

        return response, original_url

    def test_registered_email_receives_valid_reset_link(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_done"),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

        match = re.search(r"https?://\S+", mail.outbox[0].body)
        self.assertIsNotNone(match)

        reset_path = urlsplit(match.group(0)).path
        confirmation = self.client.get(reset_path, follow=True)

        self.assertTrue(confirmation.context["validlink"])

    def test_unknown_email_gets_confirmation_without_email(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "unknown@example.com"},
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_done"),
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_account_does_not_receive_reset_email(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_done"),
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_changes_password_and_invalidates_old_session(self):
        other_client = Client()
        self.assertTrue(
            other_client.login(
                username=self.user.username,
                password=self.old_password,
            )
        )

        response, _ = self.complete_reset()

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_complete"),
        )

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password(self.new_password)
        )
        self.assertFalse(
            self.user.check_password(self.old_password)
        )

        other_response = other_client.get(reverse("home"))
        self.assertFalse(
            other_response.wsgi_request.user.is_authenticated
        )

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(
            self.client.login(
                username=self.user.username,
                password=self.new_password,
            )
        )

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            self.reset_url(token="invalid-token"),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["validlink"])

    def test_expired_token_is_rejected(self):
        now = datetime.now()

        with patch(
            "django.contrib.auth.tokens."
            "PasswordResetTokenGenerator._now",
            return_value=now,
        ):
            url = self.reset_url()

        expired_time = now + timedelta(
            seconds=settings.PASSWORD_RESET_TIMEOUT + 1
        )

        with patch(
            "django.contrib.auth.tokens."
            "PasswordResetTokenGenerator._now",
            return_value=expired_time,
        ):
            response = self.client.get(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["validlink"])

    def test_used_reset_link_cannot_be_reused(self):
        response, original_url = self.complete_reset()

        self.assertRedirects(
            response,
            reverse("accounts:password_reset_complete"),
        )

        another_client = Client()
        response = another_client.get(original_url, follow=True)

        self.assertFalse(response.context["validlink"])

    def test_invalid_new_passwords_are_rejected(self):
        response = self.client.get(
            self.reset_url(),
            follow=True,
        )
        confirmation_path = response.request["PATH_INFO"]

        invalid_passwords = [
            (self.new_password, "Different!Password42"),
            ("123", "123"),
        ]

        for first, second in invalid_passwords:
            with self.subTest(first=first, second=second):
                response = self.client.post(
                    confirmation_path,
                    self.password_data(
                        new_password1=first,
                        new_password2=second,
                    ),
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)

                self.user.refresh_from_db()
                self.assertTrue(
                    self.user.check_password(self.old_password)
                )

    def test_reset_request_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_confirmation_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)

        response = client.get(self.reset_url(), follow=True)
        self.assertTrue(response.context["validlink"])

        response = client.post(
            response.request["PATH_INFO"],
            self.password_data(),
        )

        self.assertEqual(response.status_code, 403)

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password(self.old_password)
        )

class LoginThrottleTests(AccountTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Forest!River82Cabin6"

        cls.user = User.objects.create_user(
            username="throttle-user",
            email="throttle@example.com",
            password=cls.password,
        )

        cls.other_user = User.objects.create_user(
            username="other-throttle-user",
            email="other-throttle@example.com",
            password=cls.password,
        )

    def login_attempt(
        self,
        username=None,
        password="incorrect-password",
        ip="127.0.0.1",
        **extra,
    ):
        return self.client.post(
            reverse("accounts:login"),
            {
                "username": username or self.user.username,
                "password": password,
            },
            REMOTE_ADDR=ip,
            **extra,
        )

    def trigger_lockout(self):
        for _ in range(5):
            response = self.login_attempt()

        self.assertEqual(response.status_code, 429)
        return response

    def test_fifth_failure_locks_out_even_correct_password(self):
        for _ in range(4):
            response = self.login_attempt()
            self.assertEqual(response.status_code, 200)

        response = self.login_attempt()

        self.assertContains(
            response,
            "Login temporarily blocked",
            status_code=429,
        )

        response = self.login_attempt(password=self.password)

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_user_on_same_ip_can_still_log_in(self):
        self.trigger_lockout()

        response = self.login_attempt(
            username=self.other_user.username,
            password=self.password,
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.other_user.pk),
        )

    def test_same_user_on_different_ip_can_still_log_in(self):
        self.trigger_lockout()

        response = self.login_attempt(
            password=self.password,
            ip="192.0.2.10",
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.user.pk),
        )

    def test_successful_login_resets_failure_counter(self):
        for _ in range(4):
            response = self.login_attempt()
            self.assertEqual(response.status_code, 200)

        response = self.login_attempt(password=self.password)
        self.assertRedirects(response, reverse("home"))

        self.client.logout()

        # Previous failures should no longer count.
        for _ in range(4):
            response = self.login_attempt()
            self.assertEqual(response.status_code, 200)

        response = self.login_attempt()
        self.assertEqual(response.status_code, 429)

    def test_login_allowed_after_cooloff_expires(self):
        self.trigger_lockout()

        attempts = AccessAttempt.objects.filter(
            username=self.user.username,
            ip_address="127.0.0.1",
        )
        self.assertTrue(attempts.exists())

        # Simulate the waiting period passing without sleeping.
        attempts.update(
            attempt_time=timezone.now() - timedelta(minutes=20),
        )

        response = self.login_attempt(password=self.password)

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.user.pk),
        )

    def test_forwarded_ip_header_cannot_bypass_local_lockout(self):
        # Changing a client-supplied header must not change the
        # tracked IP when we use REMOTE_ADDR.
        for number in range(1, 6):
            response = self.login_attempt(
                HTTP_X_FORWARDED_FOR=f"192.0.2.{number}",
            )

        self.assertEqual(response.status_code, 429)

        response = self.login_attempt(
            password=self.password,
            HTTP_X_FORWARDED_FOR="192.0.2.99",
        )

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)