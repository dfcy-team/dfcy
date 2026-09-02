import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_line_fulfillment(apps, schema_editor):
    """Idempotent local backfill for the legacy order-level production count.

    A partial order cannot be safely split across lines, so those rows are
    explicitly marked for manual allocation and receive zero production
    quantity.  Re-running this function never overwrites an existing row.
    """

    Order = apps.get_model("purchasing", "SupplyPurchaseOrder")
    Projection = apps.get_model("purchasing", "SupplyOrderLineFulfillment")
    for order in Order.objects.all().iterator():
        lines = list(order.lines.all().order_by("pk"))
        if not lines:
            continue
        total = sum(int(line.quantity) for line in lines)
        completed = int(order.completed_quantity or 0)
        if completed <= 0:
            classification = "legacy_zero"
            manual = False
            line_completed = {line.pk: 0 for line in lines}
        elif completed >= total:
            classification = "legacy_full_order"
            manual = False
            line_completed = {line.pk: int(line.quantity) for line in lines}
        else:
            classification = "legacy_partial_manual"
            manual = True
            line_completed = {line.pk: 0 for line in lines}
        for line in lines:
            Projection.objects.get_or_create(
                order_line_id=line.pk,
                defaults={
                    "tenant_id": order.tenant_id,
                    "order_id": order.pk,
                    "ordered_quantity": line.quantity,
                    "production_completed_quantity": line_completed[line.pk],
                    "packing_reserved_quantity": 0,
                    "packed_quantity": 0,
                    "shipped_quantity": 0,
                    "warehouse_received_quantity": 0,
                    "warehouse_cleared_quantity": 0,
                    "version": 1,
                    "migration_classification": classification,
                    "needs_manual_allocation": manual,
                },
            )


def reverse_backfill(apps, schema_editor):
    # Projection rows are additive and must remain available for a safe
    # rollback/read-only phase.  Dropping them is handled by an explicit,
    # separately approved migration rather than an implicit reverse.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0005_shipping_route"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplyOrderLineFulfillment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "ordered_quantity",
                    models.PositiveBigIntegerField(),
                ),
                (
                    "production_completed_quantity",
                    models.PositiveBigIntegerField(default=0),
                ),
                ("packing_reserved_quantity", models.PositiveBigIntegerField(default=0)),
                ("packed_quantity", models.PositiveBigIntegerField(default=0)),
                ("shipped_quantity", models.PositiveBigIntegerField(default=0)),
                (
                    "warehouse_received_quantity",
                    models.PositiveBigIntegerField(default=0),
                ),
                ("warehouse_cleared_quantity", models.PositiveBigIntegerField(default=0)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "migration_classification",
                    models.CharField(
                        choices=[
                            ("native", "Native"),
                            ("legacy_zero", "Legacy zero production"),
                            ("legacy_full_order", "Legacy full order"),
                            (
                                "legacy_partial_manual",
                                "Legacy partial requires manual allocation",
                            ),
                        ],
                        default="native",
                        max_length=32,
                    ),
                ),
                ("needs_manual_allocation", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fulfillment_projections",
                        to="purchasing.supplypurchaseorder",
                    ),
                ),
                (
                    "order_line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fulfillment",
                        to="purchasing.supplypurchaseorderline",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="supply_order_line_fulfillments",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"ordering": ["order_id", "order_line_id"]},
        ),
        migrations.CreateModel(
            name="SupplyFulfillmentEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("production", "Production"),
                            ("packing", "Packing"),
                            ("shipping", "Shipping"),
                            ("warehouse_received", "Warehouse received"),
                            ("warehouse_cleared", "Warehouse cleared"),
                        ],
                        max_length=32,
                    ),
                ),
                ("delta_quantity", models.BigIntegerField()),
                ("source_type", models.CharField(max_length=64)),
                ("source_id", models.CharField(max_length=128)),
                ("source_version", models.PositiveIntegerField(default=1)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("production_complete", "Production complete"),
                            ("reserve_packing", "Reserve packing"),
                            ("release_packing", "Release packing"),
                            ("freeze_packing", "Freeze packing"),
                            ("reverse_packing", "Reverse packing"),
                            ("ship", "Ship"),
                            ("receive", "Receive"),
                            ("clear", "Clear"),
                        ],
                        max_length=40,
                    ),
                ),
                ("channel", models.CharField(default="internal", max_length=32)),
                ("reason", models.TextField(blank=True)),
                ("idempotency_key", models.CharField(max_length=255)),
                ("before_snapshot", models.JSONField(default=dict)),
                ("after_snapshot", models.JSONField(default=dict)),
                ("occurred_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supply_fulfillment_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fulfillment_events",
                        to="purchasing.supplypurchaseorder",
                    ),
                ),
                (
                    "order_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fulfillment_events",
                        to="purchasing.supplypurchaseorderline",
                    ),
                ),
                (
                    "reverse_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reversals",
                        to="purchasing.supplyfulfillmentevent",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="supply_fulfillment_events",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"ordering": ["tenant_id", "created_at", "id"]},
        ),
        migrations.AddIndex(
            model_name="supplyorderlinefulfillment",
            index=models.Index(
                fields=["tenant", "order", "order_line"], name="idx_fulfillment_scope"
            ),
        ),
        migrations.AddIndex(
            model_name="supplyfulfillmentevent",
            index=models.Index(
                fields=["tenant", "order_line", "stage", "created_at"],
                name="idx_fulfillment_event_line",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.UniqueConstraint(
                fields=("tenant", "order_line"), name="uniq_fulfillment_tenant_line"
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.CheckConstraint(
                condition=models.Q(ordered_quantity__gt=0),
                name="fulfillment_ordered_gt_zero",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.CheckConstraint(
                condition=models.Q(production_completed_quantity__gte=0)
                & models.Q(production_completed_quantity__lte=models.F("ordered_quantity")),
                name="fulfillment_production_lte_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.CheckConstraint(
                condition=models.Q(packing_reserved_quantity__gte=0)
                & models.Q(packed_quantity__gte=0)
                & models.Q(packing_reserved_quantity__lte=models.F("production_completed_quantity"))
                & models.Q(packed_quantity__lte=models.F("production_completed_quantity"))
                & models.Q(packing_reserved_quantity__lte=models.F("production_completed_quantity") - models.F("packed_quantity")),
                name="fulfillment_reserved_packed_lte_production",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.CheckConstraint(
                condition=models.Q(shipped_quantity__gte=0)
                & models.Q(warehouse_received_quantity__gte=0)
                & models.Q(warehouse_cleared_quantity__gte=0)
                & models.Q(shipped_quantity__lte=models.F("packed_quantity"))
                & models.Q(warehouse_received_quantity__lte=models.F("shipped_quantity"))
                & models.Q(warehouse_cleared_quantity__lte=models.F("warehouse_received_quantity")),
                name="fulfillment_downstream_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyorderlinefulfillment",
            constraint=models.CheckConstraint(
                condition=models.Q(version__gt=0), name="fulfillment_version_gt_zero"
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyfulfillmentevent",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="uniq_fulfillment_event_idempotency",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyfulfillmentevent",
            constraint=models.UniqueConstraint(
                fields=(
                    "tenant",
                    "source_type",
                    "source_id",
                    "source_version",
                    "order_line",
                    "stage",
                    "action",
                ),
                name="uniq_fulfillment_event_source_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyfulfillmentevent",
            constraint=models.CheckConstraint(
                condition=~models.Q(delta_quantity=0),
                name="fulfillment_event_delta_nonzero",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplyfulfillmentevent",
            constraint=models.CheckConstraint(
                condition=models.Q(source_id__gt=""),
                name="fulfillment_event_source_nonempty",
            ),
        ),
        migrations.RunPython(backfill_line_fulfillment, reverse_backfill),
    ]
