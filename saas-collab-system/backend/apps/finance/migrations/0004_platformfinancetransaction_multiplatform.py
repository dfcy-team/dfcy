from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0003_lazadafinancewide")]

    operations = [
        migrations.RemoveConstraint(
            model_name="platformfinancetransaction",
            name="chk_fin_tx_lazada",
        ),
        migrations.AddConstraint(
            model_name="platformfinancetransaction",
            constraint=models.CheckConstraint(
                condition=models.Q(platform__in=("lazada", "shopee", "tiktok")),
                name="chk_fin_tx_marketplace",
            ),
        ),
    ]
