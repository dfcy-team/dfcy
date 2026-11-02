from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory
from apps.integrations import developer_gateway as gateway


class DeveloperGatewayTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.rate_limit = patch.object(gateway, '_consume_rate_limit', return_value=True)
        self.rate_limit.start()

    def tearDown(self):
        self.rate_limit.stop()

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
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, '_consume_rate_limit', return_value=False)
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7))
    def test_61st_shared_request_is_denied_before_provider(self, authenticate, consume, execute, log):
        response = self.request()
        self.assertEqual(response.status_code, 429)
        execute.assert_not_called()
        log.objects.create.assert_called_once()
        self.assertEqual(log.objects.create.call_args.kwargs['detail']['status_code'], 429)

    @patch.object(gateway, 'DeveloperCallLog')
    @patch.object(gateway, 'execute_endpoint')
    @patch.object(gateway, '_consume_rate_limit', side_effect=ConnectionError('redis unavailable'))
    @patch.object(gateway, 'authenticate_developer_token', return_value=SimpleNamespace(pk=1, tenant_id=7))
    def test_redis_failure_fails_closed_without_provider_call(self, authenticate, consume, execute, log):
        response = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('redis unavailable', str(response.data))
        execute.assert_not_called()
        self.assertEqual(log.objects.create.call_args.kwargs['detail']['status_code'], 503)

    @patch.object(gateway.redis.Redis, 'from_url')
    @patch.object(gateway.time, 'time', return_value=1200)
    def test_shared_counter_uses_one_atomic_script_and_expires(self, now, from_url):
        self.rate_limit.stop()
        client = from_url.return_value
        count = {'value': 0}

        def eval_script(script, key_count, key, ttl):
            count['value'] += 1
            return count['value']

        client.eval.side_effect = eval_script
        self.assertTrue(all(gateway._consume_rate_limit(17) for _ in range(60)))
        self.assertFalse(gateway._consume_rate_limit(17))
        self.assertEqual(count['value'], 61)
        self.assertEqual(client.eval.call_args_list[0].args[1:], (1, 'saas-collab:developer-gateway:rate:v1:17:20', 120))
        script = client.eval.call_args_list[0].args[0]
        self.assertIn("redis.call('INCR', KEYS[1])", script)
        self.assertIn("redis.call('EXPIRE', KEYS[1], ARGV[1])", script)
        self.assertEqual(client.eval.call_args_list[0].args[1:], client.eval.call_args_list[1].args[1:])
