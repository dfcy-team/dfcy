from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("influencers", "0048_requirement_feedback")]
    operations = [migrations.CreateModel(
        name="InfluencerRequirementImage",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("content", models.BinaryField()),
            ("requirement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="images", to="influencers.influencerrequirement")),
        ],
        options={"ordering": ["id"]},
    )]
