from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0004_pr48_bd_workflow")]

    operations = [
        migrations.AddField("outreachtask", "product_name_snapshot", models.CharField(blank=True, max_length=240)),
        migrations.AddField("outreachtask", "product_match_status", models.CharField(default="pending", max_length=20)),
        migrations.AddField("outreachtask", "product_match_source", models.CharField(blank=True, max_length=40)),
        migrations.AddField("outreachtask", "product_matched_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("outreachtask", "priority", models.CharField(default="normal", max_length=20)),
        migrations.AddField("samplefulfillment", "sku_quantity", models.PositiveIntegerField(default=0)),
        migrations.AddField("samplefulfillment", "sales_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
        migrations.AddField("samplefulfillment", "calculated_cost", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
        migrations.AddField("samplefulfillment", "pricing_status", models.CharField(default="pending", max_length=20)),
        migrations.AddField("samplefulfillment", "priced_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("sampleitem", "normalized_sku", models.CharField(blank=True, max_length=160)),
        migrations.AddField("sampleitem", "matched_sku_code", models.CharField(blank=True, max_length=80)),
        migrations.AddField("sampleitem", "matched_legacy_sku_code", models.CharField(blank=True, max_length=160)),
        migrations.AddField("sampleitem", "sales_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
        migrations.AddField("sampleitem", "cost_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
        migrations.AddField("sampleitem", "cost_match_status", models.CharField(default="pending", max_length=20)),
        migrations.AddField("sampleitem", "price_source", models.CharField(blank=True, max_length=40)),
        migrations.AddField("sampleitem", "cost_source", models.CharField(blank=True, max_length=40)),
        migrations.AddField("sampleitem", "price_snapshot_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("sampleitem", "cost_snapshot_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("sampleitem", "match_notes", models.CharField(blank=True, max_length=240)),
    ]
