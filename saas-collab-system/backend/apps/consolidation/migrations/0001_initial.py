import django.db.models.deletion

from django.conf import settings

from django.db import migrations, models





class Migration(migrations.Migration):



    initial = True



    dependencies = [

        ('packing', '0006_packingboxconsumptionaction'),

        ('tenants', '0001_initial'),

        migrations.swappable_dependency(settings.AUTH_USER_MODEL),

    ]



    operations = [

        migrations.CreateModel(

            name='ConsolidationBoxAllocation',

            fields=[

                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),

                ('supplier_id_snapshot', models.PositiveBigIntegerField(blank=True, null=True)),

                ('order_id_snapshot', models.PositiveBigIntegerField(blank=True, null=True)),

                ('order_no_snapshot', models.CharField(blank=True, max_length=80)),

                ('batch_id_snapshot', models.PositiveBigIntegerField(blank=True, null=True)),

                ('batch_no_snapshot', models.CharField(blank=True, max_length=80)),

                ('box_no_snapshot', models.CharField(max_length=100)),

                ('quantity_snapshot', models.PositiveBigIntegerField(default=0)),

                ('weight_snapshot', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),

                ('volume_snapshot', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),

                ('snapshot', models.JSONField(blank=True, default=dict)),

                ('state', models.CharField(choices=[('allocated', 'Allocated'), ('handover_submitted', 'Handover submitted'), ('received', 'Received'), ('transferred', 'Transferred'), ('exception', 'Exception'), ('released', 'Released')], default='allocated', max_length=24)),

                ('version', models.PositiveIntegerField(default=1)),

                ('handover_method', models.CharField(blank=True, max_length=40)),

                ('handover_reference', models.CharField(blank=True, max_length=128)),

                ('handover_evidence_id', models.CharField(blank=True, max_length=128)),

                ('submitted_at', models.DateTimeField(blank=True, null=True)),

                ('received_at', models.DateTimeField(blank=True, null=True)),

                ('exception_code', models.CharField(blank=True, max_length=40)),

                ('exception_note', models.TextField(blank=True)),

                ('released_at', models.DateTimeField(blank=True, null=True)),

                ('created_at', models.DateTimeField(auto_now_add=True)),

                ('updated_at', models.DateTimeField(auto_now=True)),

                ('box', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='consolidation_allocations', to='packing.packingbox')),

                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_consolidation_allocations', to=settings.AUTH_USER_MODEL)),

                ('packing_box_consumption', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='consolidation_allocations', to='packing.packingboxconsumption')),

                ('received_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='received_consolidation_boxes', to=settings.AUTH_USER_MODEL)),

                ('submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='submitted_consolidation_handovers', to=settings.AUTH_USER_MODEL)),

                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consolidation_box_allocations', to='tenants.tenant')),

            ],

            options={

                'ordering': ['consolidation_id', 'box_id', 'id'],

            },

        ),

        migrations.CreateModel(

            name='ConsolidationSite',

            fields=[

                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),

                ('site_code', models.CharField(max_length=80)),

                ('name', models.CharField(max_length=160)),

                ('region_code', models.CharField(max_length=80)),

                ('country_code', models.CharField(blank=True, max_length=8)),

                ('province_state', models.CharField(blank=True, max_length=80)),

                ('city', models.CharField(blank=True, max_length=80)),

                ('district', models.CharField(blank=True, max_length=80)),

                ('address_line', models.CharField(blank=True, max_length=255)),

                ('postal_code', models.CharField(blank=True, max_length=32)),

                ('timezone', models.CharField(default='Asia/Shanghai', max_length=64)),

                ('contact_name', models.CharField(blank=True, max_length=100)),

                ('contact_phone', models.CharField(blank=True, max_length=32)),

                ('delivery_instructions', models.TextField(blank=True)),

                ('is_active', models.BooleanField(default=True)),

                ('effective_from', models.DateTimeField(blank=True, null=True)),

                ('effective_to', models.DateTimeField(blank=True, null=True)),

                ('version', models.PositiveIntegerField(default=1)),

                ('created_at', models.DateTimeField(auto_now_add=True)),

                ('updated_at', models.DateTimeField(auto_now=True)),

                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_consolidation_sites', to=settings.AUTH_USER_MODEL)),

                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consolidation_sites', to='tenants.tenant')),

                ('updated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='updated_consolidation_sites', to=settings.AUTH_USER_MODEL)),

            ],

            options={

                'ordering': ['tenant_id', 'site_code'],

            },

        ),

        migrations.CreateModel(

            name='LooseCargoConsolidation',

            fields=[

                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),

                ('consolidation_no', models.CharField(max_length=80)),

                ('region_code', models.CharField(max_length=80)),

                ('site_code_snapshot', models.CharField(blank=True, max_length=80)),

                ('site_name_snapshot', models.CharField(blank=True, max_length=160)),

                ('site_region_code_snapshot', models.CharField(blank=True, max_length=80)),

                ('site_country_code_snapshot', models.CharField(blank=True, max_length=8)),

                ('site_province_state_snapshot', models.CharField(blank=True, max_length=80)),

                ('site_city_snapshot', models.CharField(blank=True, max_length=80)),

                ('site_district_snapshot', models.CharField(blank=True, max_length=80)),

                ('site_address_line_snapshot', models.CharField(blank=True, max_length=255)),

                ('site_postal_code_snapshot', models.CharField(blank=True, max_length=32)),

                ('site_timezone_snapshot', models.CharField(blank=True, max_length=64)),

                ('site_contact_name_snapshot', models.CharField(blank=True, max_length=100)),

                ('site_contact_phone_snapshot', models.CharField(blank=True, max_length=32)),

                ('site_delivery_instructions_snapshot', models.TextField(blank=True)),

                ('site_snapshot', models.JSONField(blank=True, default=dict)),

                ('collection_cutoff_at', models.DateTimeField(blank=True, null=True)),

                ('expected_dispatch_at', models.DateTimeField(blank=True, null=True)),

                ('status', models.CharField(choices=[('draft', 'Draft'), ('released', 'Released'), ('receiving', 'Receiving'), ('ready_for_shipment', 'Ready for shipment'), ('transferred', 'Transferred'), ('cancelled', 'Cancelled')], default='draft', max_length=30)),

                ('version', models.PositiveIntegerField(default=1)),

                ('note', models.TextField(blank=True)),

                ('external_forwarder_ref', models.CharField(blank=True, max_length=128)),

                ('external_groupage_ref', models.CharField(blank=True, max_length=128)),

                ('release_site_snapshot', models.JSONField(blank=True, default=dict)),

                ('release_allocation_snapshot', models.JSONField(blank=True, default=list)),

                ('released_at', models.DateTimeField(blank=True, null=True)),

                ('ready_at', models.DateTimeField(blank=True, null=True)),

                ('cancelled_at', models.DateTimeField(blank=True, null=True)),

                ('cancelled_reason', models.TextField(blank=True)),

                ('created_at', models.DateTimeField(auto_now_add=True)),

                ('updated_at', models.DateTimeField(auto_now=True)),

                ('cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cancelled_consolidations', to=settings.AUTH_USER_MODEL)),

                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_consolidations', to=settings.AUTH_USER_MODEL)),

                ('ready_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ready_consolidations', to=settings.AUTH_USER_MODEL)),

                ('released_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='released_consolidations', to=settings.AUTH_USER_MODEL)),

                ('site', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='consolidations', to='consolidation.consolidationsite')),

                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loose_cargo_consolidations', to='tenants.tenant')),

            ],

            options={

                'ordering': ['tenant_id', '-created_at', '-id'],

            },

        ),

        migrations.CreateModel(

            name='ConsolidationEvent',

            fields=[

                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),

                ('action', models.CharField(choices=[('site_create', 'Create site'), ('site_update', 'Update site'), ('site_deactivate', 'Deactivate site'), ('create', 'Create consolidation'), ('update', 'Update consolidation'), ('allocate', 'Allocate box'), ('remove', 'Remove box'), ('release', 'Release consolidation'), ('receive', 'Receive box'), ('exception', 'Mark exception'), ('controlled_release', 'Controlled release'), ('ready', 'Ready for shipment'), ('cancel', 'Cancel consolidation')], max_length=40)),

                ('channel', models.CharField(default='internal', max_length=32)),

                ('before', models.JSONField(blank=True, default=dict)),

                ('after', models.JSONField(blank=True, default=dict)),

                ('reason', models.TextField(blank=True)),

                ('evidence_reference', models.CharField(blank=True, max_length=128)),

                ('idempotency_key', models.CharField(max_length=128)),

                ('request_hash', models.CharField(max_length=64)),

                ('expected_version', models.PositiveIntegerField(blank=True, null=True)),

                ('source_type', models.CharField(blank=True, max_length=64)),

                ('source_id', models.CharField(blank=True, max_length=128)),

                ('source_version', models.PositiveIntegerField(blank=True, null=True)),

                ('occurred_at', models.DateTimeField()),

                ('created_at', models.DateTimeField(auto_now_add=True)),

                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='consolidation_events', to=settings.AUTH_USER_MODEL)),

                ('allocation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='events', to='consolidation.consolidationboxallocation')),

                ('box', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='consolidation_events', to='packing.packingbox')),

                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consolidation_events', to='tenants.tenant')),

                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='events', to='consolidation.consolidationsite')),

                ('consolidation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='events', to='consolidation.loosecargoconsolidation')),

            ],

            options={

                'ordering': ['tenant_id', 'created_at', 'id'],

            },

        ),

        migrations.AddField(

            model_name='consolidationboxallocation',

            name='consolidation',

            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='allocations', to='consolidation.loosecargoconsolidation'),

        ),

        migrations.AddIndex(

            model_name='consolidationsite',

            index=models.Index(fields=['tenant', 'region_code', 'is_active'], name='idx_consolidation_site_scope'),

        ),

        migrations.AddConstraint(

            model_name='consolidationsite',

            constraint=models.UniqueConstraint(fields=('tenant', 'site_code'), name='uniq_consolidation_site_code'),

        ),

        migrations.AddConstraint(

            model_name='consolidationsite',

            constraint=models.CheckConstraint(condition=models.Q(('version__gt', 0)), name='consolidation_site_version_gt_zero'),

        ),

        migrations.AddIndex(

            model_name='loosecargoconsolidation',

            index=models.Index(fields=['tenant', 'region_code', 'status'], name='idx_consolidation_scope'),

        ),

        migrations.AddConstraint(

            model_name='loosecargoconsolidation',

            constraint=models.UniqueConstraint(fields=('tenant', 'consolidation_no'), name='uniq_consolidation_no_tenant'),

        ),

        migrations.AddConstraint(

            model_name='loosecargoconsolidation',

            constraint=models.CheckConstraint(condition=models.Q(('version__gt', 0)), name='consolidation_version_gt_zero'),

        ),

        migrations.AddIndex(

            model_name='consolidationevent',

            index=models.Index(fields=['tenant', 'consolidation', 'action', 'created_at'], name='idx_consolidation_event_action'),

        ),

        migrations.AddIndex(

            model_name='consolidationevent',

            index=models.Index(fields=['tenant', 'source_type', 'source_id', 'source_version'], name='idx_consolidation_event_source'),

        ),

        migrations.AddConstraint(

            model_name='consolidationevent',

            constraint=models.UniqueConstraint(fields=('tenant', 'idempotency_key'), name='uniq_consolidation_event_key'),

        ),

        migrations.AddConstraint(

            model_name='consolidationevent',

            constraint=models.CheckConstraint(condition=models.Q(('request_hash__regex', '^[0-9a-fA-F]{64}$')), name='consolidation_event_hash_hex'),

        ),

        migrations.AddIndex(

            model_name='consolidationboxallocation',

            index=models.Index(fields=['tenant', 'box', 'state'], name='idx_consolidation_box_state'),

        ),

        migrations.AddConstraint(

            model_name='consolidationboxallocation',

            constraint=models.UniqueConstraint(fields=('consolidation', 'box'), name='uniq_consolidation_box'),

        ),

        migrations.AddConstraint(

            model_name='consolidationboxallocation',

            constraint=models.CheckConstraint(condition=models.Q(('version__gt', 0)), name='consolidation_allocation_version_gt_zero'),

        ),

        migrations.AddConstraint(

            model_name='consolidationboxallocation',

            constraint=models.CheckConstraint(condition=models.Q(('quantity_snapshot__gt', 0)), name='consolidation_allocation_qty_gt_zero'),

        ),

    ]
