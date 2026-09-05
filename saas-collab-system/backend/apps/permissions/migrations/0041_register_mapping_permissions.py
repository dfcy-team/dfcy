"""Register the consolidated store and product mapping permission surface.

The mapping pages are moving under the store archive and platform product
detail pages.  Their authorization must move with them while marketplace
OAuth authorization remains governed by the existing ``store.authorize`` and
``store.revoke`` permissions.
"""

from django.db import migrations


PERMISSION_DEFINITIONS = (
    {
        "code": "integrations.store_mapping.view",
        "name": "查看店铺平台关联",
        "module": "integrations",
        "action": "store_mapping.view",
        "description": "查看当前租户店铺与平台店铺身份的映射关系、状态和验证信息。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.store_mapping.manage",
        "name": "维护店铺平台关联",
        "module": "integrations",
        "action": "store_mapping.manage",
        "description": "创建、更新或停用当前租户店铺与平台店铺身份的映射关系。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.product_mapping.view",
        "name": "查看商品 SKU 映射",
        "module": "integrations",
        "action": "product_mapping.view",
        "description": "查看当前租户平台商品变体与内部 SKU 的映射决策及状态。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.product_mapping.manage",
        "name": "维护商品 SKU 映射建议",
        "module": "integrations",
        "action": "product_mapping.manage",
        "description": "创建商品映射建议、更新建议或停用平台商品映射。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.product_mapping.confirm",
        "name": "确认商品 SKU 映射",
        "module": "integrations",
        "action": "product_mapping.confirm",
        "description": "人工确认平台商品变体与内部 SKU 的映射，并记录确认审计。",
        "permission_type": "action",
        "metadata": {},
    },
)
PERMISSION_CODES = tuple(item["code"] for item in PERMISSION_DEFINITIONS)

# Existing store authorization roles retain their OAuth meaning.  Only the
# mapping capabilities are copied to the new surface; role data scopes are
# intentionally untouched so a CUSTOM scope cannot become tenant-wide.
LEGACY_PERMISSION_MAP = {
    "integrations.store.view": (
        "integrations.store_mapping.view",
        "integrations.product_mapping.view",
    ),
    "integrations.store.authorize": (
        "integrations.store_mapping.manage",
        "integrations.product_mapping.manage",
        "integrations.product_mapping.confirm",
    ),
}
LEGACY_PERMISSION_CODES = tuple(LEGACY_PERMISSION_MAP)


def register_mapping_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")

    permissions_by_code = {}
    for definition in PERMISSION_DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=definition["code"],
            defaults={key: value for key, value in definition.items() if key != "code"},
        )
        permissions_by_code[permission.code] = permission

    # Migrate only effective role assignments.  The old permissions remain in
    # place because store.authorize/revoke still govern OAuth authorization;
    # the mapping endpoints themselves use only the new codes at runtime.
    roles = Role.objects.filter(status="active").filter(
        permissions__code__in=LEGACY_PERMISSION_CODES,
    ).distinct()
    for role in roles:
        legacy_codes = set(role.permissions.filter(code__in=LEGACY_PERMISSION_CODES).values_list("code", flat=True))
        grants = {
            new_code
            for legacy_code in legacy_codes
            for new_code in LEGACY_PERMISSION_MAP[legacy_code]
        }
        if grants:
            role.permissions.add(*(permissions_by_code[code] for code in grants))

    # The built-in administrator remains complete even if an older database
    # never carried either legacy store permission.  Existing role data scopes
    # are preserved; this migration does not create an ALL scope.
    all_mapping_permissions = tuple(permissions_by_code.values())
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*all_mapping_permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0040_register_warehouse_api_authorization_permissions")]

    operations = [
        migrations.RunPython(register_mapping_permissions, migrations.RunPython.noop),
    ]
