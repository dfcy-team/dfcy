from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0024_platform_product_readonly_sync")]

    operations = [
        migrations.AlterField("warehouseauthorization", "token_id", models.CharField(blank=True, max_length=255)),
        migrations.AddField("warehouseauthorization", "email", models.EmailField(blank=True, default="", max_length=254)),
        migrations.AddField("warehouseauthorization", "bootstrap_credential_id", models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField("warehouseauthorization", "bootstrap_consumed_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("warehouseauthorization", "oauth_user_id", models.CharField(blank=True, default="", max_length=160)),
        migrations.AddField("warehouseauthorization", "oauth_expires_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("warehouseauthorization", "validation_status", models.CharField(
            choices=[("incomplete", "待补充"), ("pending", "待校验"), ("verified", "校验通过"), ("failed", "校验失败")],
            default="incomplete", max_length=20,
        )),
    ]
