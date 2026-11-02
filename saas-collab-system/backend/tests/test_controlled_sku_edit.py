from unittest.mock import patch
from django.utils import timezone

import pytest
from rest_framework.test import APIClient

from apps.products.controlled_sku_edit import confirm_controlled_edit, preview_controlled_edit
from apps.products.models import ProductBundleComponent, ProductCategory, ProductColor, ProductSKU, ProductSKUAlias, ProductSPU
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant
from apps.accounts.models import CustomUser
from rest_framework.exceptions import ValidationError


@pytest.mark.django_db
@pytest.mark.parametrize("existing_manual_alias", [False, True])
def test_controlled_edit_preview_confirm_preserves_identity_and_alias_resolves_across_dates(existing_manual_alias):
    from tests.test_sales_management import create_scope, create_order
    tenant, _, store, _ = create_scope("controlled-edit")
    item = create_order(tenant, store, "controlled-edit").items.get()
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Root")
    l2 = ProductCategory.objects.create(tenant=tenant, level=2, code="01", name="Category", parent=l1)
    l3 = ProductCategory.objects.create(tenant=tenant, level=3, code="01", name="Subcategory", parent=l2,
        spec_dimensions=[{"code": "size", "name": "Size", "values": ["S", "M"]}])
    ProductColor.objects.create(tenant=tenant, code="RED", name="Red")
    old_spu = ProductSPU.objects.create(tenant=tenant, spu_code="OLD", product_name="Item", category_node=l3)
    new_spu = ProductSPU.objects.create(tenant=tenant, spu_code="NEW", product_name="Item", category_node=l3)
    sku = ProductSKU.objects.create(tenant=tenant, spu=old_spu, sku_code="OLD-RED-S", color_code="RED",
        specification="S", spec_values={"size": "S"}, legacy_sku_code="SOURCE-OLD")
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="BUNDLE", product_name="Bundle", product_type="bundle")
    bundle_sku = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="BUNDLE-1")
    component = ProductBundleComponent.objects.create(tenant=tenant, bundle_sku=bundle_sku, component_sku=sku, quantity=2)
    item.internal_sku = sku
    item.internal_spu = old_spu
    item.save()
    before_line = type(item).objects.values().get(pk=item.pk)
    from types import SimpleNamespace
    from apps.products.serializers import ProductSKUSerializer
    stale_editor = ProductSKUSerializer(instance=sku, data={"product_name": "Corrected display"}, partial=True, context={"request": SimpleNamespace(user=SimpleNamespace(tenant=tenant))})
    assert stale_editor.is_valid(), stale_editor.errors
    if existing_manual_alias:
        from apps.products.sku_alias_views import create_alias
        with patch("apps.audit.services.write_operation_log"):
            create_alias(sku=sku, actor=None, values={"alias_code": "SOURCE-OLD", "scope_type": "tenant", "reason": "Existing mapping", "effective_from": timezone.now(), "effective_to": None})
    plan = preview_controlled_edit(tenant, sku, {"spu_id": new_spu.pk, "color_code": "RED",
        "spec_values": {"size": "M"}, "legacy_sku_code": "SOURCE-NEW"}, {old_spu.pk, new_spu.pk})
    assert plan["after"]["sku_code"] == "NEW-RED-M"
    if existing_manual_alias:
        assert any("同商品" in message for message in plan["conflicts"])
        sku.refresh_from_db()
        assert sku.sku_code == "OLD-RED-S"
        return
    assert not plan["conflicts"]
    with patch("apps.audit.services.write_operation_log"):
        changed = confirm_controlled_edit(tenant, None, sku.pk, {"spu_id": new_spu.pk, "color_code": "RED",
            "spec_values": {"size": "M"}, "legacy_sku_code": "SOURCE-NEW",
            "updated_at": plan["updated_at"], "before": plan["before"], "preview_token": plan["preview_token"]}, {old_spu.pk, new_spu.pk})
    assert changed.pk == sku.pk
    assert changed.spu_id == new_spu.pk
    item.refresh_from_db()
    assert item.internal_spu_id == new_spu.pk and item.internal_sku_id == sku.pk
    after_line = type(item).objects.values().get(pk=item.pk)
    before_line["internal_spu_id"] = new_spu.pk
    assert before_line == after_line
    item.save()  # ValidatedWriteModel.full_clean must still pass.
    stale_editor.save()
    changed.refresh_from_db()
    assert changed.spu_id == new_spu.pk and changed.sku_code == "NEW-RED-M"
    assert changed.product_name == "Corrected display"
    assert changed.size == changed.specification == "M"
    item.refresh_from_db()
    item.save()
    component.refresh_from_db()
    assert component.component_sku_id == changed.pk and component.quantity == 2
    aliases = set(ProductSKUAlias.objects.filter(sku=changed, source="identity_correction").values_list("alias_code", flat=True))
    assert aliases == {"OLD-RED-S", "SOURCE-OLD"}
    alias = ProductSKUAlias.objects.get(sku=changed, alias_code="OLD-RED-S", source="identity_correction")
    from apps.products.sku_aliases import alias_at
    assert alias_at(ProductSKUAlias.objects.filter(pk=alias.pk), "2000-01-01").exists()
    with pytest.raises(ValidationError):
        confirm_controlled_edit(tenant, None, sku.pk, {"spu_id": new_spu.pk, "color_code": "RED",
            "spec_values": {"size": "M"}, "legacy_sku_code": "SOURCE-NEW", "updated_at": plan["updated_at"],
            "before": plan["before"], "preview_token": plan["preview_token"]}, {old_spu.pk, new_spu.pk})


@pytest.mark.django_db
def test_controlled_edit_rejects_stale_preview_and_duplicate_code():
    tenant = Tenant.objects.create(name="Tenant", code="controlled-edit-stale")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Root")
    l2 = ProductCategory.objects.create(tenant=tenant, level=2, code="01", name="Category", parent=l1)
    l3 = ProductCategory.objects.create(tenant=tenant, level=3, code="01", name="Subcategory", parent=l2,
        spec_dimensions=[{"code": "size", "name": "Size", "values": ["S"]}])
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="NEW", product_name="Item", category_node=l3)
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW-S")
    ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW-S-OTHER", legacy_sku_code="NEW-S")
    preview = preview_controlled_edit(tenant, sku, {"spu_id": spu.pk, "color_code": "", "spec_values": {"size": "S"}}, {spu.pk})
    assert preview["conflicts"]
    with pytest.raises(ValidationError, match="确认内容与预览不一致"):
        confirm_controlled_edit(tenant, None, sku.pk, {"spu_id": spu.pk, "color_code": "", "spec_values": {"size": "S"},
            "legacy_sku_code": "TAMPERED", "updated_at": preview["updated_at"], "before": preview["before"],
            "preview_token": preview["preview_token"]}, {spu.pk})
    import time
    from unittest.mock import patch as mock_patch
    with mock_patch("django.core.signing.time.time", return_value=time.time() + 3600):
        with pytest.raises(ValidationError, match="预览已失效"):
            confirm_controlled_edit(tenant, None, sku.pk, {"spu_id": spu.pk, "color_code": "", "spec_values": {"size": "S"},
                "updated_at": preview["updated_at"], "before": preview["before"], "preview_token": preview["preview_token"]}, {spu.pk})
    sku.product_name = "Updated after preview"
    sku.save(update_fields=["product_name", "updated_at"])
    with pytest.raises(Exception, match="商品身份已被其他操作修改"):
        confirm_controlled_edit(tenant, None, sku.pk, {"spu_id": spu.pk, "color_code": "", "spec_values": {"size": "S"},
            "updated_at": preview["updated_at"], "before": preview["before"], "preview_token": preview["preview_token"]}, {spu.pk})


@pytest.mark.django_db
def test_identity_action_denies_user_without_manage_permission_and_rejects_out_of_scope_target():
    tenant = Tenant.objects.create(name="Tenant", code="controlled-edit-scope")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Root")
    l2 = ProductCategory.objects.create(tenant=tenant, level=2, code="01", name="Category", parent=l1)
    l3 = ProductCategory.objects.create(tenant=tenant, level=3, code="01", name="Subcategory", parent=l2,
        spec_dimensions=[{"code": "size", "name": "Size", "values": ["S"]}])
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SCOPE", product_name="Item", category_node=l3)
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SCOPE-S")
    user = CustomUser.objects.create_user(username="no-product-permission", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    client = APIClient(); client.force_authenticate(user=user)
    response = client.get(f"/api/internal/products/skus/{sku.pk}/identity/options/")
    assert response.status_code == 403
    with pytest.raises(ValidationError, match="数据范围"):
        preview_controlled_edit(tenant, sku, {"spu_id": spu.pk, "color_code": "", "spec_values": {"size": "S"}}, set())


@pytest.mark.django_db
def test_bundle_identity_accepts_master_scope_union_but_bundle_permission_does_not_edit_normal_sku():
    tenant = Tenant.objects.create(name="Tenant", code="bundle-identity-permission-union")
    root = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Root")
    middle = ProductCategory.objects.create(tenant=tenant, level=2, code="01", name="Category", parent=root)
    category = ProductCategory.objects.create(tenant=tenant, level=3, code="01", name="Subcategory", parent=middle,
        spec_dimensions=[{"code": "size", "name": "Size", "values": ["S"]}])
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="BUNDLE", product_name="Bundle", product_type="bundle", category_node=category)
    bundle_target = ProductSPU.objects.create(tenant=tenant, spu_code="BUNDLE-TARGET", product_name="Bundle target", product_type="bundle", category_node=category)
    bundle_sku = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="BUNDLE-1")
    normal_spu = ProductSPU.objects.create(tenant=tenant, spu_code="NORMAL", product_name="Normal")
    normal_sku = ProductSKU.objects.create(tenant=tenant, spu=normal_spu, sku_code="NORMAL-1")

    master_user = CustomUser.objects.create_user(username="bundle-master-manager", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    master_role = Role.objects.create(tenant=tenant, code="bundle-master-role", name="Bundle master manager")
    master_permission, _ = Permission.objects.get_or_create(code="products.master.manage", defaults={"name": "Master manage", "module": "products", "action": "master.manage"})
    bundle_permission, _ = Permission.objects.get_or_create(code="products.bundle.manage", defaults={"name": "Bundle manage", "module": "products", "action": "bundle.manage"})
    master_role.permissions.add(master_permission)
    UserRole.objects.create(tenant=tenant, user=master_user, role=master_role)
    DataScope.objects.create(tenant=tenant, role=master_role, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    master_client = APIClient(); master_client.force_authenticate(user=master_user)

    options = master_client.get(f"/api/internal/products/skus/{bundle_sku.pk}/identity/options/")
    assert options.status_code == 200
    assert {row["id"] for row in options.json()["data"]} == {bundle_spu.pk, bundle_target.pk}
    preview = master_client.post(
        f"/api/internal/products/skus/{bundle_sku.pk}/identity/preview/",
            {"spu_id": bundle_target.pk, "color_code": "", "spec_values": {"size": "S"}, "legacy_sku_code": ""},
        format="json",
    )
    assert preview.status_code == 200, preview.json()

    bundle_only = CustomUser.objects.create_user(username="bundle-only-manager", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    bundle_role = Role.objects.create(tenant=tenant, code="bundle-only-role", name="Bundle only manager")
    bundle_role.permissions.add(bundle_permission)
    UserRole.objects.create(tenant=tenant, user=bundle_only, role=bundle_role)
    DataScope.objects.create(tenant=tenant, role=bundle_role, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    bundle_client = APIClient(); bundle_client.force_authenticate(user=bundle_only)
    assert bundle_client.get(f"/api/internal/products/skus/{normal_sku.pk}/identity/options/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["create", "update"])
def test_identity_alias_cannot_be_reoccupied_after_validation(operation):
    from types import SimpleNamespace
    from apps.products.serializers import ProductSKUSerializer
    from apps.products.sku_alias_views import create_alias
    tenant = Tenant.objects.create(name="Reserved", code="reserved-" + operation)
    user = CustomUser.objects.create_user(username="reserved-" + operation, tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU", product_name="Item")
    source = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW")
    other = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="OTHER")
    context = {"request": SimpleNamespace(user=user)}
    kwargs = {"data": {"spu": spu.pk, "sku_code": "OLD"}, "context": context}
    if operation == "update": kwargs.update(instance=other, partial=True, data={"sku_code": "OLD"})
    serializer = ProductSKUSerializer(**kwargs)
    assert serializer.is_valid(), serializer.errors
    with patch("apps.audit.services.write_operation_log"):
        create_alias(sku=source, actor=user, source="identity_correction", values={
            "alias_code": "OLD", "scope_type": "tenant", "reason": "identity correction", "effective_from": timezone.now(), "effective_to": None})
    with pytest.raises(ValidationError, match="历史别名"):
        serializer.save(**({"tenant": tenant} if operation == "create" else {}))
    assert not ProductSKU.objects.filter(tenant=tenant, sku_code="OLD").exists()
    other.refresh_from_db()
    assert other.sku_code == "OTHER"
    fresh = ProductSKUSerializer(**kwargs)
    assert not fresh.is_valid() and "sku_code" in fresh.errors
