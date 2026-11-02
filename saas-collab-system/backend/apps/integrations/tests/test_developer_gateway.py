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
