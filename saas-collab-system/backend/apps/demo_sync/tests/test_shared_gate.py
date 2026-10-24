import tempfile
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed

from apps.demo_sync.shared_middleware import SharedDemoGateMiddleware


class SharedDemoGateTests(SimpleTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.marker = Path(self.tempdir.name) / "maintenance.flag"
        self.factory = RequestFactory()
        self.middleware = SharedDemoGateMiddleware(lambda request: JsonResponse({"ok": True}))
        self.settings = override_settings(
            DEMO_SHARED_MAINTENANCE_FILE=str(self.marker),
            DEMO_SHARED_ADMIN_IDS=frozenset({41}),
        )
        self.settings.enable()
        self.addCleanup(self.settings.disable)

    def request(self, path, authorization=None):
        headers = {"HTTP_AUTHORIZATION": authorization} if authorization else {}
        return self.middleware(self.factory.get(path, **headers))

    def test_unauthenticated_business_and_public_routes_are_blocked(self):
        for path in (
            "/api/internal/auth/me/",
            "/api/supply-notifications/files/7/token/",
            "/api/external/callback/",
        ):
            with self.subTest(path=path):
                response = self.request(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(json.loads(response.content)["code"], "AUTH_REQUIRED")

    def test_only_exact_auth_exemptions_and_health_bypass_auth(self):
        for path in ("/api/internal/auth/login/", "/api/internal/auth/refresh/", "/api/internal/health/"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path).status_code, 200)
        self.assertEqual(self.request("/api/internal/auth/login").status_code, 401)
        self.assertEqual(self.request("/api/internal/health").status_code, 401)

    def test_admin_requires_active_internal_allowlisted_superuser(self):
        users = [
            SimpleNamespace(pk=41, is_active=True, user_type="internal", is_superuser=True),
            SimpleNamespace(pk=42, is_active=True, user_type="internal", is_superuser=True),
            SimpleNamespace(pk=41, is_active=True, user_type="external", is_superuser=True),
            SimpleNamespace(pk=41, is_active=False, user_type="internal", is_superuser=True),
            SimpleNamespace(pk=41, is_active=True, user_type="internal", is_superuser=False),
        ]
        with patch("apps.accounts.authentication.UATAwareJWTAuthentication.authenticate") as authenticate:
            authenticate.return_value = (users[0], object())
            self.assertEqual(self.request("/api/internal/analytics/", "Bearer valid").status_code, 200)
            for user in users[1:]:
                with self.subTest(user=user):
                    authenticate.return_value = (user, object())
                    response = self.request("/api/internal/analytics/", "Bearer valid")
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(json.loads(response.content)["code"], "PERMISSION_DENIED")

    def test_authentication_failure_is_401(self):
        with patch(
            "apps.accounts.authentication.UATAwareJWTAuthentication.authenticate",
            side_effect=AuthenticationFailed("secret detail must not leak"),
        ):
            response = self.request("/api/internal/analytics/", "Bearer expired")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("secret detail", response.content.decode())

    def test_maintenance_blocks_every_api_except_health_and_admin_site(self):
        self.marker.touch()
        for path in ("/api/internal/auth/login/", "/api/internal/auth/refresh/", "/api/internal/analytics/"):
            with self.subTest(path=path):
                response = self.request(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(json.loads(response.content)["code"], "MAINTENANCE")
        self.assertEqual(self.request("/api/internal/health/").status_code, 200)
        self.assertEqual(self.request("/admin/").status_code, 403)

    def test_django_admin_is_blocked_without_database_authentication(self):
        self.assertEqual(self.request("/admin/").status_code, 403)
