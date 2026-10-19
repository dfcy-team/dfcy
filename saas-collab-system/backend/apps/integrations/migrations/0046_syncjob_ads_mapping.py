from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0045_adsoauthsession")]
    operations = [
        migrations.AddField(model_name="syncjob", name="ads_mapping", field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name="sync_jobs", to="integrations.tiktokadsadvertisermapping")),
        migrations.AlterField(model_name="syncjob", name="resource_type", field=models.CharField(
            max_length=40, choices=[("advertising_report", "Advertising report"),
                ("platform_product", "Platform product"), ("sales_order", "Sales order"),
                ("affiliate_order", "Affiliate order"), ("refund_return", "Refund or return"),
                ("inventory_snapshot", "Inventory snapshot"), ("inbound", "Inbound"),
                ("shipment", "Shipment"), ("settlement_bill", "Settlement bill"),
                ("withdrawal", "Withdrawal"), ("mock_record", "Mock record")])),
        migrations.AddConstraint(model_name="syncjob", constraint=models.CheckConstraint(
            condition=(models.Q(ads_mapping__isnull=True) & ~models.Q(resource_type="advertising_report"))
            | models.Q(ads_mapping__isnull=False, resource_type="advertising_report",
                       store_authorization__isnull=True, warehouse_authorization__isnull=True),
            name="chk_sync_job_ads_subject")),
        migrations.AddConstraint(model_name="syncjob", constraint=models.UniqueConstraint(
            fields=("tenant", "ads_mapping", "resource_type"), name="uniq_sync_job_ads_resource")),
    ]
