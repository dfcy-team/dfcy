from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0050_tiktok_shop_binding")]

    operations = [
        migrations.AddField(model_name="adsoauthsession", name=name, field=field)
        for name, field in (
            ("cleanup_fence", models.UUIDField(null=True, blank=True)),
            ("cleanup_lease_until", models.DateTimeField(null=True, blank=True)),
            ("cleanup_attempts", models.PositiveIntegerField(default=0)),
            ("cleanup_error", models.CharField(max_length=80, blank=True, default="")),
        )
    ] + [
        migrations.AlterField(model_name="adsoauthsession", name="status", field=models.CharField(
            max_length=20, default="pending", choices=[(value, value) for value in (
                "pending", "exchanging", "authorized", "unknown", "failed", "bound",
                "cancelled", "cleanup_pending", "cleaning", "cleaned", "cleanup_owned")]))
    ]
