import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("purchasing", "0004_supplypurchaseorderevent_idempotency_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplypurchaseorder",
            name="shipping_route",
            field=models.CharField(
                choices=[
                    ("undecided", "Undecided"),
                    ("loose_cargo", "Loose cargo"),
                    ("container_cargo", "Container cargo"),
                ],
                default="undecided",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="supplypurchaseorder",
            name="shipping_route_decided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="supplypurchaseorder",
            name="shipping_route_decided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shipping_route_decisions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="supplypurchaseorderevent",
            name="after_shipping_route",
            field=models.CharField(
                choices=[
                    ("undecided", "Undecided"),
                    ("loose_cargo", "Loose cargo"),
                    ("container_cargo", "Container cargo"),
                ],
                default="undecided",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="supplypurchaseorderevent",
            name="before_shipping_route",
            field=models.CharField(
                choices=[
                    ("undecided", "Undecided"),
                    ("loose_cargo", "Loose cargo"),
                    ("container_cargo", "Container cargo"),
                ],
                default="undecided",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="supplypurchaseorderevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("accept", "Accept"),
                    ("start_production", "Start production"),
                    ("update_progress", "Update progress"),
                    ("complete_production", "Complete production"),
                    ("assign_shipping_route", "Assign shipping route"),
                    ("change_shipping_route", "Change shipping route"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="supplypurchaseorder",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        shipping_route="undecided",
                        shipping_route_decided_at__isnull=True,
                        shipping_route_decided_by__isnull=True,
                    )
                    | (
                        models.Q(shipping_route__in=["loose_cargo", "container_cargo"])
                        & models.Q(shipping_route_decided_at__isnull=False)
                        & models.Q(shipping_route_decided_by__isnull=False)
                    )
                ),
                name="supply_po_route_decision_consistent",
            ),
        ),
    ]
