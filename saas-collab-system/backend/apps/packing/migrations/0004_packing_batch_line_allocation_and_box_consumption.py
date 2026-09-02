import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_allocations(apps, schema_editor):
    Batch = apps.get_model("packing", "PackingBatch")
    Allocation = apps.get_model("packing", "PackingBatchLineAllocation")
    Projection = apps.get_model("purchasing", "SupplyOrderLineFulfillment")
    FulfillmentEvent = apps.get_model("purchasing", "SupplyFulfillmentEvent")

    def classify_anomaly(batch, message):
        """Leave a durable migration classification without violating checks."""

        marker = f"[SC-F2-MULTI-1 backfill anomaly] {message}"
        current = batch.note or ""
        if marker not in current:
            batch.note = f"{current}\n{marker}".strip()
            Batch.objects.filter(pk=batch.pk).update(note=batch.note)

    for batch in Batch.objects.all().iterator():
        quantities = {}
        for item in batch.boxes.values_list("items__order_line_id", "items__quantity"):
            line_id, quantity = item
            if line_id is not None:
                quantities[line_id] = quantities.get(line_id, 0) + int(quantity or 0)
        state = {
            "completed": "frozen",
            "cancelled": "released",
        }.get(batch.status, "reserved")
        for line_id, quantity in quantities.items():
            if quantity <= 0:
                continue
            projection = Projection.objects.filter(order_line_id=line_id).first()
            if projection is None or projection.needs_manual_allocation:
                # Partial legacy production cannot be safely inferred.  Keep
                # the allocation identity for the manual queue but do not
                # manufacture a quantity projection or event.
                Allocation.objects.get_or_create(
                    batch_id=batch.pk,
                    order_line_id=line_id,
                    defaults={
                        "tenant_id": batch.tenant_id,
                        "quantity": quantity,
                        "state": state,
                        "allocation_version": batch.version,
                        "created_by_id": batch.created_by_id,
                        "frozen_at": (batch.completed_at or batch.created_at) if state == "frozen" else None,
                        "released_at": (batch.cancelled_at or batch.created_at) if state == "released" else None,
                    },
                )
                classify_anomaly(
                    batch,
                    f"line={line_id} requires manual line allocation (partial legacy production)",
                )
                continue
            if state == "released":
                # A cancelled historical batch has no trustworthy reserve
                # event to reverse.  Preserve the released allocation row but
                # do not emit an unmatched negative fulfillment event.
                Allocation.objects.get_or_create(
                    batch_id=batch.pk,
                    order_line_id=line_id,
                    defaults={
                        "tenant_id": batch.tenant_id,
                        "quantity": quantity,
                        "state": "released",
                        "allocation_version": batch.version,
                        "created_by_id": batch.created_by_id,
                        "frozen_at": None,
                        "released_at": batch.cancelled_at or batch.created_at,
                    },
                )
                continue

            current_reserved = int(projection.packing_reserved_quantity or 0)
            current_packed = int(projection.packed_quantity or 0)
            current_production = int(projection.production_completed_quantity or 0)
            new_reserved = current_reserved + quantity if state == "reserved" else current_reserved
            new_packed = current_packed + quantity if state == "frozen" else current_packed
            if (
                new_reserved < 0
                or new_packed < 0
                or new_reserved + new_packed > current_production
                or new_reserved + new_packed > int(projection.ordered_quantity or 0)
            ):
                # Do not let a historical over-allocation surface as an opaque
                # DB CHECK/IntegrityError.  Retain the source quantity as a
                # reversed allocation and classify it on the batch for manual
                # review; projection/event state remains unchanged.
                Allocation.objects.get_or_create(
                    batch_id=batch.pk,
                    order_line_id=line_id,
                    defaults={
                        "tenant_id": batch.tenant_id,
                        "quantity": quantity,
                        "state": "reversed",
                        "allocation_version": batch.version,
                        "created_by_id": batch.created_by_id,
                        "frozen_at": None,
                        "released_at": batch.completed_at or batch.created_at,
                    },
                )
                classify_anomaly(
                    batch,
                    f"line={line_id} quantity={quantity} exceeds production/ordered cap; allocation reversed",
                )
                continue

            allocation, created = Allocation.objects.get_or_create(
                batch_id=batch.pk,
                order_line_id=line_id,
                defaults={
                    "tenant_id": batch.tenant_id,
                    "quantity": quantity,
                    "state": state,
                    "allocation_version": batch.version,
                    "created_by_id": batch.created_by_id,
                    "frozen_at": (batch.completed_at or batch.created_at) if state == "frozen" else None,
                    "released_at": None,
                },
            )
            if not created:
                continue
            if state == "frozen":
                action = "freeze_packing"
            elif state == "reserved":
                action = "reserve_packing"
            projection.packing_reserved_quantity = new_reserved
            projection.packed_quantity = new_packed
            Projection.objects.filter(pk=projection.pk).update(
                packing_reserved_quantity=projection.packing_reserved_quantity,
                packed_quantity=projection.packed_quantity,
                version=projection.version + 1,
            )
            event_key = f"migration:packing:{batch.pk}:line:{line_id}:{state}"
            FulfillmentEvent.objects.get_or_create(
                tenant_id=batch.tenant_id,
                idempotency_key=event_key,
                defaults={
                    "order_id": projection.order_id,
                    "order_line_id": line_id,
                    "stage": "packing",
                    "delta_quantity": quantity,
                    "source_type": "packing_batch_migration",
                    "source_id": str(batch.pk),
                    "source_version": batch.version,
                    "action": action,
                    "actor_id": batch.created_by_id,
                    "channel": "internal",
                    "reason": "SC-F2-MULTI-1 local historical backfill",
                    "before_snapshot": {},
                    "after_snapshot": {
                        "packing_reserved_quantity": projection.packing_reserved_quantity,
                        "packed_quantity": projection.packed_quantity,
                    },
                    "occurred_at": batch.completed_at or batch.created_at,
                },
            )


def reverse_allocations(apps, schema_editor):
    # Keep additive rows in a read-only rollback.  A destructive reverse would
    # erase the audit bridge needed to converge an order back to the legacy
    # single-batch invariant.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("packing", "0003_packingapiidempotencyrecord_tenant_key"),
        ("purchasing", "0006_supplyfulfillment_projection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PackingBatchLineAllocation",
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
                ("quantity", models.PositiveBigIntegerField()),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("frozen", "Frozen"),
                            ("released", "Released"),
                            ("reversed", "Reversed"),
                        ],
                        default="reserved",
                        max_length=16,
                    ),
                ),
                ("allocation_version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("frozen_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="line_allocations",
                        to="packing.packingbatch",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_packing_allocations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="packing_allocations",
                        to="purchasing.supplypurchaseorderline",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="packing_batch_line_allocations",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"ordering": ["batch_id", "order_line_id"]},
        ),
        migrations.CreateModel(
            name="PackingBoxConsumption",
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
                    "consumer_type",
                    models.CharField(
                        choices=[
                            ("consolidation", "Consolidation"),
                            ("shipment", "Shipment"),
                        ],
                        max_length=24,
                    ),
                ),
                ("consumer_id", models.PositiveBigIntegerField()),
                ("consumer_version", models.PositiveIntegerField(default=1)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("committed", "Committed"),
                            ("released", "Released"),
                            ("reversed", "Reversed"),
                        ],
                        default="reserved",
                        max_length=16,
                    ),
                ),
                ("active_guard", models.BooleanField(default=True, editable=False, null=True)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("reason", models.TextField(blank=True)),
                ("reserved_at", models.DateTimeField(auto_now_add=True)),
                ("committed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="packing_box_consumptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "box",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="consumptions",
                        to="packing.packingbox",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="packing_box_consumptions",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "transferred_from",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transferred_consumptions",
                        to="packing.packingboxconsumption",
                    ),
                ),
            ],
            options={"ordering": ["box_id", "-reserved_at", "-id"]},
        ),
        migrations.RemoveConstraint(
            model_name="packingbatchorder",
            name="uniq_pack_active_order",
        ),
        migrations.AddIndex(
            model_name="packingbatchlineallocation",
            index=models.Index(
                fields=["tenant", "order_line", "state"],
                name="idx_pack_alloc_line_state",
            ),
        ),
        migrations.AddIndex(
            model_name="packingboxconsumption",
            index=models.Index(
                fields=["tenant", "consumer_type", "consumer_id", "state"],
                name="idx_pack_consumption_consumer",
            ),
        ),
        migrations.AddConstraint(
            model_name="packingbatchlineallocation",
            constraint=models.UniqueConstraint(
                fields=("batch", "order_line"), name="uniq_pack_batch_line_allocation"
            ),
        ),
        migrations.AddConstraint(
            model_name="packingbatchlineallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="pack_allocation_qty_gt_zero"
            ),
        ),
        migrations.AddConstraint(
            model_name="packingbatchlineallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(allocation_version__gt=0),
                name="pack_allocation_version_gt_zero",
            ),
        ),
        migrations.AddConstraint(
            model_name="packingboxconsumption",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key"), name="uniq_pack_box_consumption_key"
            ),
        ),
        migrations.AddConstraint(
            model_name="packingboxconsumption",
            constraint=models.UniqueConstraint(
                fields=("box", "active_guard"), name="uniq_pack_box_active_consumption"
            ),
        ),
        migrations.AddConstraint(
            model_name="packingboxconsumption",
            constraint=models.CheckConstraint(
                condition=models.Q(active_guard=True)
                | models.Q(active_guard__isnull=True),
                name="pack_box_consumption_guard_true_null",
            ),
        ),
        migrations.AddConstraint(
            model_name="packingboxconsumption",
            constraint=models.CheckConstraint(
                condition=models.Q(consumer_id__gt=0)
                & models.Q(consumer_version__gt=0),
                name="pack_box_consumption_identity_positive",
            ),
        ),
        migrations.RunPython(backfill_allocations, reverse_allocations),
    ]
