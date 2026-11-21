"""Contract only after the writer fence and successful row-preserving fill."""
from django.db import migrations, models
from django.db.models import Count, Q


def require_complete_keys(apps, schema_editor):
    Line = apps.get_model("sales_management", "WarehouseOutboundLine")
    rows = Line.objects.using(schema_editor.connection.alias)
    if rows.filter(
        Q(site_code__isnull=True) | Q(document_key__isnull=True) | Q(identity_key__isnull=True)
        | Q(site_code="") | Q(document_key="") | Q(identity_key="")
    ).exists():
        raise RuntimeError("V518_OUTBOUND_INCOMPLETE_BEFORE_CONTRACT")
    if rows.values("lookup_id", "identity_key").annotate(n=Count("pk")).filter(n__gt=1).exists():
        raise RuntimeError("V518_OUTBOUND_COLLISION_BEFORE_CONTRACT")


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0014_fill_outbound_identity_preserving_rows")]
    operations = [
        migrations.RunPython(require_complete_keys, migrations.RunPython.noop),
        # Validate the new key first and keep a lookup-leading unique index
        # throughout the nontransactional MySQL DDL sequence (also covers FK).
        migrations.AddConstraint("warehouseoutboundline", models.UniqueConstraint(fields=["lookup", "identity_key"], name="v518_outbound_identity_guard")),
        migrations.RemoveConstraint("warehouseoutboundline", "uniq_wh_outbound_lookup_line"),
        migrations.RemoveIndex("warehouseoutboundline", "wh_outbound_scope_doc_idx"),
        migrations.AlterField("warehouseoutboundline", "site_code", models.CharField(max_length=8)),
        migrations.AlterField("warehouseoutboundline", "document_key", models.CharField(max_length=64)),
        migrations.AlterField("warehouseoutboundline", "identity_key", models.CharField(max_length=64)),
        migrations.AddIndex("warehouseoutboundline", models.Index(fields=["tenant", "warehouse", "document_key"], name="wh_outbound_scope_doc_idx")),
        migrations.AddIndex("warehouseoutboundline", models.Index(fields=["tenant", "site_code", "shipped_at"], name="wh_outbound_site_time_idx")),
        migrations.AddConstraint("warehouseoutboundline", models.UniqueConstraint(fields=["lookup", "identity_key"], name="uniq_wh_outbound_lookup_line")),
        migrations.RemoveConstraint("warehouseoutboundline", "v518_outbound_identity_guard"),
    ]
