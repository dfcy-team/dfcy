import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.integrations.models import EmployeeReadonlyGrant, InternalAPIClient
from apps.permissions.models import Permission, Role, UserRole, DataScope
from apps.products.models import ProductSPU
from apps.products.models import ProductSKU
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.ui_p2_scopes import filter_master_data
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant

BASE = "/api/employee-readonly/v1/"
POLICIES = {"products": {f: "field.employee_readonly.products."+f+".view" for f in ("id", "product_name", "brand", "updated_at")}}


@override_settings(EMPLOYEE_READONLY_ENABLED=True, EMPLOYEE_READONLY_CLIENT_IDS=["employee-test"], EMPLOYEE_READONLY_FIELD_POLICIES=POLICIES)
class EmployeeReadonlyTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="ER1", name="Employee")
        self.user = get_user_model().objects.create_user(username="employee-A", password="test", tenant=self.tenant, user_type="internal")
        self.b = get_user_model().objects.create_user(username="employee-B", password="test", tenant=self.tenant, user_type="internal")
        self.callback = "https://caller.example/callback"
        self.machine = InternalAPIClient.objects.create(tenant=self.tenant, name="ER", caller_type="knowledge_base", client_id="employee-test", secret_hash=make_password("secret"), resources=["products"], allowed_cidrs=["127.0.0.1/32"], sso_redirect_uris=[self.callback], status="active", approval_status="approved", created_by=self.user, updated_by=self.user)
        self.basic = "Basic "+base64.b64encode(b"employee-test:secret").decode()
        self.p1 = ProductSPU.objects.create(tenant=self.tenant, spu_code="one", product_name="One", brand="Private")
        self.p2 = ProductSPU.objects.create(tenant=self.tenant, spu_code="two", product_name="Two")
        self.roles = []
        for user, product, fields in [(self.user, self.p1, ["id", "product_name", "brand"]), (self.b, self.p2, ["product_name"])]:
            role = Role.objects.create(tenant=self.tenant, name=user.username, code=user.username)
            action, _ = Permission.objects.get_or_create(code="products.master.view", defaults={"name": "View", "module": "products", "action": "master.view"})
            role.permissions.add(action)
            for field in fields:
                p, _ = Permission.objects.get_or_create(code=POLICIES["products"][field], defaults={"name": field, "module": "employee_readonly", "action": "view", "permission_type": "field", "metadata": {"resource": "employee_readonly.products", "field": field}})
                role.permissions.add(p)
            UserRole.objects.create(user=user, tenant=self.tenant, role=role)
            DataScope.objects.create(role=role, tenant=self.tenant, scope_type="custom", config={"spu_ids": [product.pk]})
            self.roles.append(role)
        self.verifier = "a"*43
        self.payload = {"client_id": self.machine.client_id, "redirect_uri": self.callback, "state": "safe_state_123456789", "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode(), "audience": "employee-readonly-v1"}

    def code(self, user=None):
        self.client.force_authenticate(user or self.user)
        response = self.client.post(BASE+"authorize/", self.payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return parse_qs(urlsplit(response.json()["data"]["redirect_url"]).query)["code"][0]

    def exchange(self, code, **kw):
        self.client.force_authenticate(None)
        payload = {"code": code, "state": self.payload["state"], "redirect_uri": self.callback, "code_verifier": self.verifier, "audience": "employee-readonly-v1"}
        payload.update(kw)
        return self.client.post(BASE+"exchange/", payload, format="json", HTTP_AUTHORIZATION=self.basic)

    def token(self, user=None):
        response = self.exchange(self.code(user))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]["access_token"]

    def read(self, token, path="resources/products/", **kw):
        return self.client.get(BASE+path, HTTP_AUTHORIZATION=self.basic, HTTP_X_EMPLOYEE_DELEGATION="Bearer "+token, **kw)

    def test_employee_rows_and_columns_and_tenant(self):
        a, b = self.token(), self.token(self.b)
        self.assertEqual(self.read(a).json()["data"]["items"], [{"id": self.p1.pk, "product_name": "One", "brand": "Private"}])
        self.assertEqual(self.read(b).json()["data"]["items"], [{"product_name": "Two"}])
        self.assertEqual(self.read(a, "resources/products/?id="+str(self.p2.pk)).json()["data"]["returned_count"], 0)
        other = Tenant.objects.create(code="ER2", name="Other")
        self.user.tenant = other
        self.user.save(update_fields=["tenant"])
        self.assertEqual(self.read(a).status_code, 401)

    def test_code_replay_wrong_state_pkce_audience_expiry(self):
        code = self.code()
        for kw in [{"state": "incorrect"}, {"audience": "business"}, {"code_verifier": "b"*43}]:
            self.assertEqual(self.exchange(code, **kw).status_code, 401)
        self.assertEqual(self.exchange(code).status_code, 200)
        self.assertEqual(self.exchange(code).status_code, 401)
        code = self.code()
        EmployeeReadonlyGrant.objects.filter(code_hash=hashlib.sha256(code.encode()).hexdigest()).update(code_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.exchange(code).status_code, 401)

    def test_revocation_m2m_scope_and_disabled_switch(self):
        token = self.token()
        self.roles[0].permissions.remove(Permission.objects.get(code=POLICIES["products"]["brand"]))
        self.assertEqual(self.read(token).status_code, 401)
        token = self.token()
        DataScope.objects.filter(role=self.roles[0]).update(config={"spu_ids": [self.p2.pk]})
        self.assertEqual(self.read(token).status_code, 401)
        token = self.token()
        with override_settings(EMPLOYEE_READONLY_ENABLED=False):
            self.assertEqual(self.read(token).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(BASE+"revoke-all/", {}, format="json").status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(self.read(token).status_code, 401)

    def test_client_cidr_expiry_and_write_rejection(self):
        token = self.token()
        self.assertEqual(self.read(token, REMOTE_ADDR="192.0.2.1").status_code, 401)
        self.assertEqual(self.client.post(BASE+"resources/products/", {}, HTTP_AUTHORIZATION=self.basic, HTTP_X_EMPLOYEE_DELEGATION="Bearer "+token).status_code, 405)
        self.assertEqual(self.client.post("/api/internal/products/spus/", {}, HTTP_AUTHORIZATION="Bearer "+token).status_code, 401)
        EmployeeReadonlyGrant.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.read(token).status_code, 401)

    def test_field_metadata_and_unknown_filter_fail_closed(self):
        token = self.token()
        self.assertEqual(self.read(token, "resources/products/?sql=anything").status_code, 400)
        self.assertEqual(self.read(token, "resources/sales_orders/").status_code, 404)
        with override_settings(EMPLOYEE_READONLY_FIELD_POLICIES={"products": {"brand": POLICIES["products"]["product_name"]}}):
            token = self.token()
            self.assertEqual(self.read(token).status_code, 403)

    def test_cursor_bound_to_employee_resource_filters_and_native_scope(self):
        DataScope.objects.filter(role=self.roles[0]).update(config={"spu_ids": [self.p1.pk, self.p2.pk]})
        a = self.token()
        page = self.read(a, "resources/products/?limit=1").json()["data"]
        self.assertTrue(page["has_more"])
        cursor = page["next_cursor"]
        second = self.read(a, "resources/products/?limit=1&cursor="+cursor)
        self.assertEqual(second.json()["data"]["items"][0]["id"], self.p2.pk)
        b = self.token(self.b)
        self.assertEqual(self.read(b, "resources/products/?cursor="+cursor).status_code, 400)
        self.assertEqual(self.read(a, "resources/products/?id="+str(self.p1.pk)+"&cursor="+cursor).status_code, 400)
        self.assertEqual(self.read(a, "resources/products/?cursor="+cursor+"tamper").status_code, 400)

    def test_no_field_grants_and_logout_client_token_revocation(self):
        self.roles[0].permissions.remove(*Permission.objects.filter(permission_type="field"))
        token = self.token()
        self.assertEqual(self.read(token).status_code, 403)
        self.assertEqual(self.read(token, "capabilities/").json()["data"]["ready_resources"], [])
        response = self.client.post(BASE+"revoke/", {}, HTTP_AUTHORIZATION=self.basic, HTTP_X_EMPLOYEE_DELEGATION="Bearer "+token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read(token).status_code, 401)

    def test_disabled_employee_wrong_client_and_client_config_changes(self):
        token = self.token()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.read(token).status_code, 401)

        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        token = self.token()
        InternalAPIClient.objects.create(tenant=self.tenant, name="Other", caller_type="knowledge_base", client_id="other-client", secret_hash=make_password("secret"), resources=["products"], allowed_cidrs=["127.0.0.1/32"], sso_redirect_uris=[self.callback], status="active", approval_status="approved", created_by=self.user, updated_by=self.user)
        with override_settings(EMPLOYEE_READONLY_CLIENT_IDS=["employee-test", "other-client"]):
            basic = "Basic "+base64.b64encode(b"other-client:secret").decode()
            response = self.client.get(BASE+"capabilities/", HTTP_AUTHORIZATION=basic, HTTP_X_EMPLOYEE_DELEGATION="Bearer "+token)
            self.assertEqual(response.status_code, 401)
        for fields in [{"approval_status": "pending"}, {"status": "disabled"}, {"expires_at": timezone.now()-timedelta(seconds=1)}, {"resources": []}]:
            InternalAPIClient.objects.filter(pk=self.machine.pk).update(**fields)
            self.assertEqual(self.read(token).status_code, 401)
            InternalAPIClient.objects.filter(pk=self.machine.pk).update(status="active", approval_status="approved", expires_at=None, resources=["products"])

    def test_default_off_strict_json_malformed_callback_and_role_changes(self):
        self.client.force_authenticate(self.user)
        with override_settings(EMPLOYEE_READONLY_ENABLED=False):
            self.assertEqual(self.client.post(BASE+"authorize/", self.payload, format="json").status_code, 403)
        self.assertEqual(self.client.post(BASE+"authorize/", dict(self.payload, user_id=self.b.pk), format="json").status_code, 400)
        self.assertEqual(self.client.post(BASE+"authorize/", dict(self.payload, redirect_uri="https://[bad"), format="json").status_code, 400)
        token = self.token()
        self.roles[0].status = "inactive"
        self.roles[0].save(update_fields=["status"])
        self.assertEqual(self.read(token).status_code, 401)
        self.roles[0].status = "active"
        self.roles[0].save(update_fields=["status"])
        token = self.token()
        self.roles[0].permissions.remove(Permission.objects.get(code="products.master.view"))
        self.assertEqual(self.read(token).status_code, 401)

    def test_master_hierarchy_and_sku_tenant_parent_scope(self):
        platform = PlatformMaster.objects.create(tenant=self.tenant, code="p", name="P", platform_type="amazon")
        store = StoreMaster.objects.create(tenant=self.tenant, platform=platform, code="s", name="Store")
        warehouse = WarehouseMaster.objects.create(tenant=self.tenant, code="w", name="Warehouse", service_platform=platform)
        sku = ProductSKU.objects.create(tenant=self.tenant, spu=self.p1, sku_code="sku")
        other = Tenant.objects.create(code="ER-other", name="Other")
        foreign = ProductSPU.objects.create(tenant=other, spu_code="foreign", product_name="Foreign")
        # Simulate inconsistent historical relation using queryset update (bypasses model validation).
        bad = ProductSKU.objects.create(tenant=self.tenant, spu=self.p1, sku_code="bad")
        ProductSKU.objects.filter(pk=bad.pk).update(spu=foreign)
        mapping = dict(POLICIES)
        for resource in ["stores", "warehouses", "product_details"]:
            code = "field.employee_readonly."+resource+".id.view"
            p, _ = Permission.objects.get_or_create(code=code, defaults={"name": "id", "module": "employee_readonly", "action": "view", "permission_type": "field", "metadata": {"resource": "employee_readonly."+resource, "field": "id"}})
            self.roles[0].permissions.add(p)
            mapping[resource] = {"id": code}
        action, _ = Permission.objects.get_or_create(code="masterdata.view", defaults={"name": "Master", "module": "masterdata", "action": "view"})
        self.roles[0].permissions.add(action)
        DataScope.objects.filter(role=self.roles[0]).update(config={"platform_ids": [platform.pk], "spu_ids": [self.p1.pk], "sku_ids": [bad.pk]})
        self.machine.resources = ["products", "product_details", "stores", "warehouses"]
        self.machine.save(update_fields=["resources"])
        with override_settings(EMPLOYEE_READONLY_FIELD_POLICIES=mapping):
            token = self.token()
            for resource, model, expected in [("stores", StoreMaster, store), ("warehouses", WarehouseMaster, warehouse)]:
                native = list(filter_master_data(self.user, model.objects.filter(tenant=self.tenant), "masterdata.view", resource).values_list("id", flat=True))
                items = self.read(token, "resources/"+resource+"/").json()["data"]["items"]
                self.assertEqual([row["id"] for row in items], native)
                self.assertEqual(native, [expected.pk])
            self.assertEqual(self.read(token, "resources/product_details/").json()["data"]["items"], [{"id": sku.pk}])

    def test_admin_bootstrap_does_not_grant_employee_fields(self):
        field = Permission.objects.get(code=POLICIES["products"]["brand"])
        admin = sync_tenant_administrator_role(self.tenant)
        self.assertFalse(admin.permissions.filter(pk=field.pk).exists())
        admin.permissions.add(field)
        admin = sync_tenant_administrator_role(self.tenant)
        self.assertTrue(admin.permissions.filter(pk=field.pk).exists())
