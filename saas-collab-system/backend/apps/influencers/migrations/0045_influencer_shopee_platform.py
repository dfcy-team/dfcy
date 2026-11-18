from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('influencers', '0044_influencer_archive_soft_delete')]
    operations = [migrations.AlterField(
        model_name='influencerplatformaccount', name='platform',
        field=models.CharField(max_length=20, choices=[
            ('tiktok', 'TikTok'), ('facebook', 'Facebook'),
            ('instagram', 'Instagram'), ('youtube', 'YouTube'), ('shopee', 'Shopee'),
        ]),
    )]
