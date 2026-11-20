import ast,sys,types,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

class Invalid(Exception):pass
class JifengSelected(BaseException):pass

class RouteTest(unittest.TestCase):
    def run_route(self, platform='best_ecapi', provider='best_ecapi', selection=False, blocked=False):
        source=(Path(__file__).resolve().parents[1] / 'apps/integrations/warehouse_credential_views.py').read_text(encoding='utf-8')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='warehouse_readonly_check')
        node.decorator_list=[]
        helper=Mock(return_value=NS(data={'data':{'selection_required':selection}}))
        mod=types.ModuleType('route_package.best_access');mod.check_connection_for_warehouse=helper
        sys.modules['route_package.best_access']=mod
        record=NS(status='active',provider=provider,integration_config_id=41,external_warehouse_region='MY',warehouse_id=6,pk=5)
        client=Mock();client.preflight.side_effect=JifengSelected('jifeng selected')
        env={'__name__':'route_package.views','__package__':'route_package','check_user_permission':lambda *a:True,
             'get_scoped_object_or_404':lambda *a,**k:record,'_warehouse_authorization_queryset':lambda *a:None,
             '_get_config_for_user':lambda *a:NS(platform=platform,environment="production",pk=41,status="verified"),'WarehouseAuthorization':NS(Status=NS(ACTIVE='active')),
             'integration_values_allowed':lambda *a,**k:True,'warehouse_config_blockers':lambda c:['blocked'] if blocked else [],
             'ValidationError':Invalid,'PermissionDenied':Invalid,'JifengWmsReadonlyClient':Mock(return_value=client)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<route>','exec'),env)
        return env,helper,lambda:env['warehouse_readonly_check'](NS(user=object()),5)

    def test_best_uses_existing_glink_flow(self):
        env,helper,run=self.run_route()
        result=run()
        helper.assert_called_once()
        self.assertEqual(helper.call_args.args[1],6)
        self.assertEqual(helper.call_args.kwargs,{'authorization_id':5})
        env['JifengWmsReadonlyClient'].assert_not_called()
        self.assertFalse(result.data['data']['selection_required'])

    def test_selection_is_not_reported_as_connected(self):
        _,_,run=self.run_route(selection=True)
        with self.assertRaises(Invalid):run()

    def test_provider_mismatch_does_not_call_either_client(self):
        env,helper,run=self.run_route(provider='jifeng_wms')
        with self.assertRaises(Invalid):run()
        helper.assert_not_called();env['JifengWmsReadonlyClient'].assert_not_called()

    def test_jifeng_path_is_unchanged(self):
        env,helper,run=self.run_route(platform='jifeng_wms',provider='jifeng_wms')
        with self.assertRaises(JifengSelected):run()
        helper.assert_not_called()

    def test_scope_denial_precedes_best_client(self):
        env,helper,run=self.run_route()
        env['integration_values_allowed']=lambda *a,**k:False
        with self.assertRaises(Invalid):run()
        helper.assert_not_called();env['JifengWmsReadonlyClient'].assert_not_called()

    def test_config_blockers_precede_best_client(self):
        mod=types.ModuleType('route_package.readiness_service');mod.BLOCKER_LABELS={'blocked':'not approved'}
        sys.modules['route_package.readiness_service']=mod
        env,helper,run=self.run_route(blocked=True)
        with self.assertRaises(Invalid):run()
        helper.assert_not_called();env['JifengWmsReadonlyClient'].assert_not_called()

    def test_configured_best_can_recheck_without_ignoring_network_approval(self):
        env,helper,run=self.run_route()
        env['_get_config_for_user']=lambda *a:NS(platform='best_ecapi',environment='production',pk=41,status='configured')
        env['warehouse_config_blockers']=lambda c:['config_not_approved']
        run();helper.assert_called_once()
        env['warehouse_config_blockers']=lambda c:['config_not_approved','blocked']
        helper.reset_mock()
        with self.assertRaises(Invalid):run()
        helper.assert_not_called()

if __name__=='__main__':unittest.main()
