from django.test import TestCase, override_settings
from . import test_api


class LocalAuthorizeTests(TestCase):
    base = test_api.DemoSyncAPITests.base
    setUp = test_api.DemoSyncAPITests.setUp
    def test_local_authorize_disabled_by_default(self):
        self.assertEqual(self.client.get(self.base + 'local-authorize/').status_code, 404)

    def test_local_actor_and_tenant_are_bound(self):
        with override_settings(DEMO_LOCAL_UPDATE_ENABLED=True, DEMO_LOCAL_ACTOR_ID=self.user.pk,
                               DEMO_LOCAL_TENANT_ID=self.tenant.pk):
            self.assertEqual(self.client.get(self.base + 'local-authorize/').status_code, 200)
        with override_settings(DEMO_LOCAL_UPDATE_ENABLED=True, DEMO_LOCAL_ACTOR_ID=self.peer.pk,
                               DEMO_LOCAL_TENANT_ID=self.tenant.pk):
            self.assertEqual(self.client.get(self.base + 'local-authorize/').status_code, 403)

    def test_local_update_still_requires_download_permission(self):
        self.role.permissions.remove(*self.role.permissions.filter(code='system.demo_sync.download'))
        with override_settings(DEMO_LOCAL_UPDATE_ENABLED=True, DEMO_LOCAL_ACTOR_ID=self.user.pk,
                               DEMO_LOCAL_TENANT_ID=self.tenant.pk):
            self.assertEqual(self.client.get(self.base + 'local-authorize/').status_code, 403)
