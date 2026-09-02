from django.db import migrations, models
import django.db.models.deletion


def backfill_category_nodes(apps, schema_editor):
    """Carry structured categories through existing development records.

    Older projects only stored a free-text category.  Where a project points
    at a research requirement with a structured category, preserve that
    relation on the project and any already-created archive.  Rows that
    cannot be traced remain nullable for backwards compatibility and are
    required to choose a category before a new archive is created.
    """

    DevelopmentProject = apps.get_model("development", "DevelopmentProject")
    DevelopmentProductArchive = apps.get_model("development", "DevelopmentProductArchive")

    for project in DevelopmentProject.objects.select_related("requirement").all().iterator():
        category = getattr(project.requirement, "category_node_id", None) if project.requirement_id else None
        if not category:
            continue
        project.category_node_id = category
        if not project.category:
            category_model = apps.get_model("products", "ProductCategory")
            category_obj = category_model.objects.filter(pk=category, tenant_id=project.tenant_id).first()
            if category_obj:
                project.category = category_obj.name
        project.save(update_fields=["category_node", "category"])

    for archive in DevelopmentProductArchive.objects.select_related("project__requirement").all().iterator():
        category = getattr(archive.project, "category_node_id", None) if archive.project_id else None
        if not category and archive.project_id and archive.project.requirement_id:
            category = getattr(archive.project.requirement, "category_node_id", None)
        if not category:
            continue
        archive.category_node_id = category
        if not archive.category:
            category_model = apps.get_model("products", "ProductCategory")
            category_obj = category_model.objects.filter(pk=category, tenant_id=archive.tenant_id).first()
            if category_obj:
                archive.category = category_obj.name
        archive.save(update_fields=["category_node", "category"])


class Migration(migrations.Migration):

    dependencies = [
        ("development", "0004_developmentproductarchive_and_more"),
        ("products", "0015_productresearch_category_sites"),
    ]

    operations = [
        migrations.AddField(
            model_name="developmentproject",
            name="category_node",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_projects",
                to="products.productcategory",
            ),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="category_node",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_product_archives",
                to="products.productcategory",
            ),
        ),
        migrations.RunPython(backfill_category_nodes, migrations.RunPython.noop),
    ]
