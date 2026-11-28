from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0053_tiktok_video_evidence_oss")]
    operations = [migrations.AddField(model_name="outreachtask", name="paused_from_pending", field=models.BooleanField(default=False, db_default=False, editable=False))]
