from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('integrations', '0060_gmv_max_audit_lookup_index')]
    operations = [migrations.AlterField(
        model_name='connectioncapability', name='capability_code',
        field=models.CharField(max_length=30, choices=[
            ('PRODUCT', 'Product'), ('CATEGORY', 'Category'), ('LISTING', 'Listing'),
            ('PRICE', 'Price'), ('ORDER', 'Order'), ('INVENTORY', 'Inventory'),
            ('FULFILLMENT', 'Fulfillment'), ('WAREHOUSE', 'Warehouse'),
            ('RETURN_REFUND', 'Return and refund'), ('SETTLEMENT', 'Settlement'),
            ('PAYMENT', 'Payment'), ('ADVERTISING', 'Advertising'),
            ('AFFILIATE', 'Affiliate'), ('CREATOR', 'TikTok creator'),
            ('VIDEO', 'TikTok video'), ('REVIEW', 'Review'), ('REPORT', 'Report'),
            ('WEBHOOK', 'Webhook'),
        ]))]
