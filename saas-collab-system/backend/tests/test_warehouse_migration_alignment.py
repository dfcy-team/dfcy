"""Run on a fresh isolated database, never on an application database."""
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader


def test_warehouse_and_main_histories_have_one_integration_leaf():
    loader = MigrationLoader(None)
    assert not loader.detect_conflicts()
    target = ('integrations','0062_merge_warehouse_gmv_branches')
    assert loader.graph.leaf_nodes('integrations') == [target]
    ancestors = loader.graph.forwards_plan(target)
    assert ('integrations','0060_gmv_max_audit_lookup_index') in ancestors
    assert ('integrations','0060_best_ecapi_platform') in ancestors
    state = loader.project_state()
    assert state.apps.get_model('integrations','DeveloperEndpoint')._meta.get_field('warehouse_account')
    assert state.apps.get_model('masterdata','PlatformMaster')._meta.get_field('warehouse_connector_key')


def verify_upgrade(connection, *, legacy_first=False):
    assert connection.settings_dict['NAME'].startswith('test_warehouse_alignment_')
    executor = MigrationExecutor(connection)
    assert not executor.loader.applied_migrations, 'Use a fresh isolated database'
    base = [('integrations', '0058_merge_local_increment_vm370'), ('masterdata', '0022_merge_local_fx_vm370')]
    if not legacy_first:
        base[0] = ('integrations', '0060_gmv_max_audit_lookup_index')
    executor.migrate(base)
    apps = executor.loader.project_state(base).apps
    Tenant = apps.get_model('tenants','Tenant')
    User = apps.get_model('accounts','CustomUser')
    Platform = apps.get_model('masterdata','PlatformMaster')
    Warehouse = apps.get_model('masterdata','WarehouseMaster')
    Config = apps.get_model('integrations','PlatformIntegrationConfig')
    Authorization = apps.get_model('integrations','WarehouseAuthorization')
    tenant = Tenant.objects.create(code='alignment',name='Alignment test')
    user = User.objects.create(tenant=tenant,username='alignment',password='!',user_type='internal')
    expected = {}
    for index, (code, providers) in enumerate((('jf',[('jifeng_wms','active')]),('best',[('best_ecapi','active')]),
        ('mixed',[('jifeng_wms','active'),('best_ecapi','active')]),('revoked',[('jifeng_wms','revoked')]),('empty',[]))):
        platform = Platform.objects.create(tenant=tenant,code=code,name=code,platform_type='warehouse_third_party')
        for number, (provider,status) in enumerate(providers):
            config = Config.objects.create(tenant=tenant,platform=provider,account_alias=f'{code}-{number}',created_by=user)
            warehouse = Warehouse.objects.create(tenant=tenant,service_platform=platform,code=f'wh-{index}-{number}',
                name=code,country_code='MY',warehouse_type='third_party')
            Authorization.objects.create(tenant=tenant,warehouse=warehouse,integration_config=config,provider=provider,
                status=status,created_by=user,updated_by=user,credential_id='synthetic-reference')
        expected[platform.pk] = ('selected',providers[0][0]) if code in ('jf','best') else ('pending','')
    before = list(Authorization.objects.order_by('pk').values())
    if legacy_first:
        MigrationExecutor(connection).migrate([('integrations','0061_best_platform_master'),('masterdata','0024_backfill_platform_connectors')])
    target = [('integrations','0062_merge_warehouse_gmv_branches'),('masterdata','0024_backfill_platform_connectors')]
    executor = MigrationExecutor(connection)
    assert not executor.loader.detect_conflicts()
    executor.migrate(target)
    executor = MigrationExecutor(connection)
    executor.loader.check_consistent_history(connection)
    assert executor.migration_plan(target) == []
    apps = executor.loader.project_state(target).apps
    Platform = apps.get_model('masterdata','PlatformMaster')
    assert {row.pk:(row.warehouse_connector_state,row.warehouse_connector_key)
            for row in Platform.objects.filter(pk__in=expected)} == expected
    assert list(apps.get_model('integrations','WarehouseAuthorization').objects.order_by('pk').values()) == before
    assert Platform.objects.filter(tenant_id=tenant.pk,code='BEST').count() == 1
    with connection.cursor() as cursor:
        indexes = connection.introspection.get_constraints(cursor, apps.get_model('integrations','IntegrationAuditLog')._meta.db_table)
    assert indexes['idx_audit_tenant_action_result']['columns'] == ['tenant_id','action','result']
    return {'start':'legacy_warehouse' if legacy_first else 'main_0060','platform_cases':5,
            'authorizations_preserved':len(before),'history_consistent':True,'pending_migrations':0,'main_audit_index_preserved':True}
