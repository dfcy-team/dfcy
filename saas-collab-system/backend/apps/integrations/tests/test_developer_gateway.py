from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import SimpleTestCase
from django.core.cache import cache
from rest_framework.test import APIRequestFactory
from apps.integrations import developer_gateway as gateway


class DeveloperGatewayTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        cache.clear()
        self.rate_limit = patch.object(gateway, '_consume_rate_limit', return_value=True)
        self.rate_limit.start()
        self.addCleanup(self.rate_limit.stop)

    def request(self, app_id=1, payload=None):
        return gateway.invoke(self.factory.post('/', payload or {'query': {}}, format='json', HTTP_AUTHORIZATION='Bearer 1.secret'), app_id, 'orders')

    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=None)
    def test_invalid_token_never_calls_provider(self, authenticate, execute):
        self.assertEqual(self.request().status_code, 401)
        execute.assert_not_called()

    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=2))
    def test_token_cannot_address_other_app(self, authenticate, execute):
        self.assertEqual(self.request().status_code, 401)
        execute.assert_not_called()

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_only_tenant_approved_endpoint_is_queried(self, authenticate, execute, endpoint, log):
        query = endpoint.objects.select_related.return_value.filter
        query.return_value.first.return_value = None
        self.assertEqual(self.request().status_code, 403)
        self.assertEqual(query.call_args.kwargs, {'config__tenant_id':7,'approved':True,'id__in':[9],'code':'orders'})
        execute.assert_not_called()
        self.assertEqual(log.objects.create.call_args.kwargs['detail']['status_code'], 403)

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint', return_value={'items': []})
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_invocation_logs_metadata_not_request_body(self, authenticate, execute, endpoint, log):
        response = self.request(payload={'query': {'sensitive': 'private-data'}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], {'items': []})
        self.assertNotIn('private-data', str(log.objects.create.call_args))
        self.assertTrue(response.data['request_id'])

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_provider_auth_failure_is_not_developer_token_failure(self, authenticate, execute, endpoint, log):
        from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_AUTH_REJECTED
        execute.side_effect = OAuthFlowError(OAUTH_AUTH_REJECTED, 'private upstream details')
        response = self.request()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private upstream details', str(response.data))
        self.assertEqual(log.objects.create.call_args.kwargs['detail']['status_code'], 502)

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint', return_value={'ok': True})
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_platform_scope_passes_dynamic_route_to_transport(self, authenticate, execute, endpoint, log):
        record = SimpleNamespace(scope_mode='platform', relative_path='/', method='GET', base_url='https://api.example.com')
        endpoint.objects.select_related.return_value.filter.return_value.first.return_value = record
        with patch('apps.integrations.developer_transport.build_gateway_url', return_value='https://api.example.com/orders/search'):
            response = self.request(payload={'path': '/orders/search', 'method': 'POST', 'query': {'page': 2}})
        self.assertEqual(response.status_code, 200)
        target = execute.call_args.args[0]
        self.assertEqual((target.relative_path, target.method), ('/orders/search', 'POST'))
        detail = log.objects.create.call_args.kwargs['detail']
        self.assertEqual((detail['path'], detail['method']), ('/orders/search', 'POST'))
        self.assertNotIn('page', str(detail))

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_fixed_scope_rejects_dynamic_route(self, authenticate, execute, endpoint, log):
        endpoint.objects.select_related.return_value.filter.return_value.first.return_value = SimpleNamespace(scope_mode='fixed')
        response = self.request(payload={'path': '/other', 'method': 'GET'})
        self.assertEqual(response.status_code, 400)
        execute.assert_not_called()

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'DeveloperEndpoint')
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7, approved_endpoint_ids=[9]))
    def test_invalid_platform_paths_never_execute_or_enter_audit(self, auth, execute, endpoints, logs):
        endpoints.objects.select_related.return_value.filter.return_value.first.return_value=SimpleNamespace(scope_mode='platform',base_url='https://api.example.com')
        for value in [None, [], {}, 7, '/'+('x'*241), '//evil.test/x', '/%2e%2e/x', '/x?secret=bad', '/\x00']:
            with self.subTest(path=value):
                result=self.request(payload={'path':value,'method':'GET'})
                self.assertEqual(result.status_code,400)
                self.assertNotIn('path',logs.objects.create.call_args.kwargs['detail'])
        execute.assert_not_called()
