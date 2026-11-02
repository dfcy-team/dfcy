from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError, PermissionDenied
from apps.integrations import developer_transport as transport


class DeveloperTransportTests(SimpleTestCase):
    def endpoint(self):
        return SimpleNamespace(connection=SimpleNamespace(network_enabled=True, status='active', environment='production', sync_read_enabled=True, sync_write_enabled=False, token_id='tok_ref'), account=None, method='GET', auth_mode='bearer', base_url='https://api.example.com', relative_path='/v1/orders')

    @patch.object(transport, 'assert_host_allowed')
    def test_path_cannot_escape_registered_host(self, allowed):
        for origin in ['https://[', 'https://api.example.com:invalid', 'https://api.example.com/other']:
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                transport.build_gateway_url(origin, '/orders', {})
        for path in ['//evil.com/a', '/%2e%2e/a', '/%252e%252e/a', '/a%3fx=1', '/a\\b', '/a%0d']:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                transport.build_gateway_url('https://api.example.com', path, {})
        self.assertEqual(transport.build_gateway_url('https://api.example.com', '/orders', {'page': 2}), 'https://api.example.com/orders?page=2')

    @patch.object(transport.socket, 'getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))])
    @patch.object(transport.socket, 'create_connection')
    def test_private_dns_never_connects(self, connect, resolve):
        with self.assertRaises(OSError):
            transport.gateway_transport('GET', 'https://api.example.com/orders')
        connect.assert_not_called()

    @patch.object(transport.socket, 'getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('10.0.0.1',443))])
    @patch.object(transport.socket, 'create_connection')
    def test_mixed_dns_never_connects(self, connect, resolve):
        with self.assertRaises(OSError):
            transport.gateway_transport('GET', 'https://api.example.com/orders')
        connect.assert_not_called()

    def test_production_write_denied_before_custody(self):
        endpoint = self.endpoint(); endpoint.method = 'POST'
        with patch.object(transport, 'get_custody_backend') as custody, self.assertRaises(PermissionDenied):
            transport.execute_endpoint(endpoint, {}, {})
        custody.assert_not_called()

    def test_read_disabled_denied_before_custody_or_network(self):
        endpoint = self.endpoint()
        endpoint.connection.sync_read_enabled = False
        with patch.object(transport, 'get_custody_backend') as custody, patch.object(transport, 'PlatformHttpClient') as client, self.assertRaises(PermissionDenied):
            transport.execute_endpoint(endpoint, {}, None)
        custody.assert_not_called()
        client.assert_not_called()

    @patch.object(transport, 'assert_host_allowed')
    @patch.object(transport, 'get_custody_backend')
    @patch.object(transport, 'PlatformHttpClient')
    def test_relative_path_and_escaped_secret_redaction(self, client, custody, allowed):
        custody.return_value.retrieve_access_token.return_value = 'secret'
        client.return_value.request.return_value.text = '{"echo":"\\u0073ecret", "nested":[{"secret":"secret"}]}'
        result = transport.execute_endpoint(self.endpoint(), {'page': 1}, None)
        self.assertEqual(result, {'echo':'[REDACTED]', 'nested':[{'[REDACTED]':'[REDACTED]'}]})
        self.assertEqual(client.return_value.request.call_args.args[1], 'https://api.example.com/v1/orders?page=1')
        self.assertFalse(client.return_value.request.call_args.kwargs['retry'])
        endpoint = self.endpoint()
        endpoint.connection.status = 'verified'
        self.assertEqual(transport.execute_endpoint(endpoint, {}, None), result)

    @patch('apps.integrations.production_settings.get_runtime_platform_config', return_value={'api_host':'https://api.example.com','app_id':'app-1'})
    @patch.object(transport, 'assert_host_allowed')
    @patch.object(transport, 'get_custody_backend')
    @patch.object(transport, 'PlatformHttpClient')
    def test_shop_signing_preserves_server_identity(self, client, custody, allowed, runtime):
        from urllib.parse import urlsplit, parse_qs
        from apps.integrations.live_providers import _tiktok_sign, _hmac_sha256
        custody.return_value.retrieve_access_token.return_value = 'shop-token'
        custody.return_value.retrieve_secret.return_value = 'app-secret'
        client.return_value.request.return_value.text = '{"ok":true}'
        for mode, platform in [('tiktok_shop','tiktok'),('shopee_shop','shopee')]:
            endpoint = self.endpoint(); endpoint.auth_mode = mode
            endpoint.connection.platform=platform; endpoint.connection.platform_config={}; endpoint.connection.credential_id='secret-ref'
            endpoint.connection.id=2; endpoint.connection.tenant_id=3
            endpoint.account=SimpleNamespace(tenant_id=3,integration_config_id=2,status='active',expires_at=None,token_id='token-ref',shop_cipher='cipher',platform_store_id='42')
            self.assertEqual(transport.execute_endpoint(endpoint, {'page':1}, None), {'ok':True})
            params={k:v[0] for k,v in parse_qs(urlsplit(client.return_value.request.call_args.args[1]).query).items()}
            if platform=='tiktok':
                self.assertEqual(params['sign'], _tiktok_sign('/v1/orders',params,'app-secret'))
                self.assertEqual(client.return_value.request.call_args.kwargs['headers']['x-tts-access-token'],'shop-token')
            else:
                self.assertEqual(params['sign'], _hmac_sha256('app-secret',f"app-1/v1/orders{params['timestamp']}shop-token42"))
            with self.assertRaises(ValidationError):
                transport.execute_endpoint(endpoint, {'shop_id':'other-shop'}, None)

    @patch('apps.integrations.production_settings.get_runtime_platform_config', return_value={'api_host':'https://api.example.com','app_id':'app-1'})
    @patch.object(transport, 'assert_host_allowed')
    @patch.object(transport, 'get_custody_backend')
    @patch.object(transport, 'PlatformHttpClient')
    def test_tiktok_search_post_uses_existing_reference_without_enabling_writes(self, client, custody, allowed, runtime):
        endpoint = self.endpoint()
        endpoint.auth_mode='tiktok_shop'; endpoint.method='POST'; endpoint.relative_path='/order/202309/orders/search'
        endpoint.connection.platform='tiktok'; endpoint.connection.platform_config={'app_secret_reference':'existing-ref'}
        endpoint.connection.credential_id=''; endpoint.connection.id=2; endpoint.connection.tenant_id=3
        endpoint.account=SimpleNamespace(tenant_id=3,integration_config_id=2,status='active',expires_at=None,token_id='token-ref',shop_cipher='cipher',platform_store_id='42')
        custody.return_value.retrieve_access_token.return_value='token'
        custody.return_value.retrieve_secret.return_value='signing-secret'
        client.return_value.request.return_value.text='{"data":{"orders":[]}}'
        self.assertEqual(transport.execute_endpoint(endpoint, {'page_size':1}, {'create_time_ge':1}), {'data':{'orders':[]}})
        custody.return_value.retrieve_secret.assert_called_once_with('existing-ref')
        self.assertEqual(client.return_value.request.call_args.kwargs['json_body'], {'create_time_ge':1})
        endpoint.relative_path='/order/202309/orders/cancel'
        with self.assertRaises(PermissionDenied): transport.execute_endpoint(endpoint, {}, {})
