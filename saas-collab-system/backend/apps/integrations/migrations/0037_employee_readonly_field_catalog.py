from django.db import migrations


FIELDS = {
    "products": "id spu_code legacy_spu_code product_name brand category lifecycle_status sales_status updated_at",
    "product_details": "id spu_id sku_code legacy_sku_code product_name color_code specification size material image_url is_active updated_at",
    "stores": "id platform_id platform_site_id code name country_code currency status updated_at",
    "warehouses": "id code name country_code warehouse_type status updated_at",
}


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for resource, fields in FIELDS.items():
        for field in fields.split():
            Permission.objects.get_or_create(code=f"field.employee_readonly.{resource}.{field}.view", defaults={"name": f"Employee {resource} {field}", "module": "employee_readonly", "action": "view", "permission_type": "field", "metadata": {"resource": "employee_readonly."+resource, "field": field}})


class Migration(migrations.Migration):
    dependencies = [("integrations", "0036_employee_readonly_grant"), ("permissions", "0048_register_internal_api_client_approval")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
