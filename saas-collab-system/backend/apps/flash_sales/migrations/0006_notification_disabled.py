from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("flash_sales", "0005_plan_deleted_at")]
    operations = [
        migrations.AddField(model_name="tenantcontrol", name="notifications_not_before",
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(model_name="storeconfig", name="notification_mode",
                              field=models.CharField(max_length=12, default="owner", choices=[
                                  ("owner", "店铺负责人"), ("custom", "自定义人员"),
                                  ("fallback", "使用兜底"), ("disabled", "关闭"),
                              ])),
    ]
