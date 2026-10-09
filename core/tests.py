from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse


class FoundationTests(TestCase):
    def test_homepage_is_accessible(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "Product Reviews")

    def test_health_checks_database(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_handles_database_failure(self):
        with patch(
            "core.views.connection.cursor",
            side_effect=OperationalError("Private database details"),
        ):
            response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"status": "unavailable"},
        )
        self.assertNotContains(
            response,
            "Private database details",
            status_code=503,
        )

    def test_admin_requires_login(self):
        response = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            response,
            reverse("admin:login") + "?next=/admin/",
        )