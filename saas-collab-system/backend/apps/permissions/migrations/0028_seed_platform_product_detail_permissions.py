from django.db import migrations


PERMISSIONS = (
    ("listings.product_detail.view", "查看平台商品明细数据", "product_detail.view"),
    ("listings.product_detail.manage", "维护平台商品明细数据", "product_detail.manage"),
    ("listings.product_detail.import", "导入平台商品明细数据", "product_detail.import"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "listings", "action": action, "description": "平台商品明细数据权限。"},
        )


def unseed(apps, schema_editor):
    apps.get_model("permissions", "Permission").objects.filter(code__in=[item[0] for item in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    # Keep this migration linear against the checked-in 0027 seed.  Some
    # deployment bundles referred to a local 0027_sync... patch that is not
    # present in source, which prevents Django from building the graph.
    dependencies = [("permissions", "0027_seed_platform_product_detail_permissions")]
    operations = [migrations.RunPython(seed, unseed)]
