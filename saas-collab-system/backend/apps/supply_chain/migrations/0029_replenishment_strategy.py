from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('masterdata', '0018_archive_code_rule'),
        ('supply_chain', '0028_dashboard_menu'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReplenishmentStrategy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('version', models.PositiveIntegerField(default=1)),
                ('name', models.CharField(max_length=120)),
                ('cycle_days', models.PositiveSmallIntegerField(default=10)),
                ('lead_days', models.PositiveSmallIntegerField(default=45)),
                ('safety_days', models.PositiveSmallIntegerField(default=35)),
                ('sales_model', models.CharField(choices=[('weighted', '加权日均'), ('ordinary', '普通30天日均')], default='weighted', max_length=16)),
                ('sales_weights', models.JSONField(default=dict)),
                ('active', models.BooleanField(default=True)),
                ('country', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='masterdata.countrysitemaster')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='accounts.customuser')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ],
            options={'ordering': ['country_id']},
        ),
        migrations.AddConstraint(model_name='replenishmentstrategy', constraint=models.UniqueConstraint(fields=('tenant', 'country'), name='sc2_replenishment_country')),
        migrations.AddConstraint(model_name='replenishmentstrategy', constraint=models.CheckConstraint(condition=models.Q(('cycle_days__gte', 1)), name='sc2_replenishment_cycle_positive')),
        migrations.AddConstraint(model_name='replenishmentstrategy', constraint=models.CheckConstraint(condition=models.Q(('lead_days__gte', 1)), name='sc2_replenishment_lead_positive')),
        migrations.AddConstraint(model_name='replenishmentstrategy', constraint=models.CheckConstraint(condition=models.Q(('safety_days__gte', 0)), name='sc2_replenishment_safety_nonnegative')),
    ]
