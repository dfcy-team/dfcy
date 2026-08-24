from decimal import Decimal

from django.db import migrations
from django.db.models.query import QuerySet
from django.utils import timezone


def backfill_sample_pricing(apps, schema_editor):
    SampleFulfillment = apps.get_model("influencers", "SampleFulfillment")
    SampleItem = apps.get_model("influencers", "SampleItem")

    for fulfillment in SampleFulfillment.objects.all().iterator(chunk_size=500):
        items = list(SampleItem.objects.filter(fulfillment_id=fulfillment.pk).order_by("id"))
        quantity = sum(item.quantity for item in items)
        sales_total = Decimal("0")
        cost_total = Decimal("0")
        any_price = False
        any_cost = False
        all_prices = bool(items)
        all_costs = bool(items)

        for item in items:
            sales_amount = item.unit_price * item.quantity if item.unit_price is not None else None
            cost_amount = item.unit_cost * item.quantity if item.unit_cost is not None else None
            item.sales_amount = sales_amount
            item.cost_amount = cost_amount
            if sales_amount is None:
                all_prices = False
            else:
                any_price = True
                sales_total += sales_amount
                item.price_source = item.price_source or "legacy_snapshot"
            if cost_amount is None:
                all_costs = False
            else:
                any_cost = True
                cost_total += cost_amount
                item.cost_match_status = "matched_snapshot"
                item.cost_source = item.cost_source or "legacy_snapshot"
            QuerySet.update(
                SampleItem.objects.filter(pk=item.pk),
                sales_amount=item.sales_amount,
                cost_amount=item.cost_amount,
                price_source=item.price_source,
                cost_match_status=item.cost_match_status,
                cost_source=item.cost_source,
            )

        if not items:
            pricing_status = "pending"
        elif all_prices and all_costs:
            pricing_status = "full"
        elif any_price or any_cost:
            pricing_status = "partial"
        else:
            pricing_status = "not_found"
        QuerySet.update(
            SampleFulfillment.objects.filter(pk=fulfillment.pk),
            sku_quantity=quantity,
            sales_amount=sales_total if any_price else None,
            calculated_cost=cost_total if any_cost else None,
            pricing_status=pricing_status,
            priced_at=timezone.now() if items else None,
        )


class Migration(migrations.Migration):
    dependencies = [("influencers", "0005_task_product_and_sample_pricing")]

    operations = [migrations.RunPython(backfill_sample_pricing, migrations.RunPython.noop)]
