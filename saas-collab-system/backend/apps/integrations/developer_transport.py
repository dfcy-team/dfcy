"""Registered developer endpoints: public pinned IPs, TLS and bounded JSON only."""
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit, unquote, urlencode

from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .custody import get_custody_backend
from .net_guard import assert_host_allowed, PlatformHttpClient, HttpResponse, MAX_RESPONSE_BYTES


def is_verified_readonly(endpoint):
    if endpoint.method in ('GET', 'HEAD', 'OPTIONS'):
        return True
    if endpoint.method != 'POST':
        return False
    # These exact paths already have read-only implementations in this repository.
    # Registration and caller input cannot classify arbitrary POST operations as reads.
    if endpoint.auth_mode == 'tiktok_shop' and endpoint.connection.platform == 'tiktok':
        return endpoint.relative_path in {
            '/order/202309/orders/search', '/product/202502/products/search',
        }
    if endpoint.auth_mode == 'shopee_shop' and endpoint.connection.platform == 'shopee':
        from .readonly_clients import ShopeeReadonlyClient
        return endpoint.relative_path in ShopeeReadonlyClient.READONLY_POST_PATHS
    return False


def build_gateway_url(base_url, path, query):
    try:
        base = urlsplit(base_url)
        port = base.port
    except ValueError:
        raise ValidationError('平台地址格式无效。') from None
    if base.scheme != 'https' or not base.hostname or port not in (None, 443) or base.username or base.password or base.query or base.fragment or base.path not in ('', '/'):
        raise ValidationError('连接必须使用获准的 HTTPS 域名。')
    decoded = path
    for _ in range(4):
        decoded = unquote(decoded)
    if not path.startswith('/') or decoded.startswith('//') or '\\' in decoded or any(ord(c) < 32 for c in decoded) or any(p in ('.', '..') for p in decoded.split('/')) or any(c in decoded for c in ('?', '#', '%')):
        raise ValidationError('接口路径无效。')
    if not isinstance(query, dict) or any(not isinstance(k, str) for k in query):
        raise ValidationError('query 必须是对象。')
    url = f'https://{base.hostname}{path}'
    if query:
        url += '?' + urlencode(query, doseq=True)
    assert_host_allowed(url)
    return url


def gateway_transport(method, url, *, data=None, headers=None, connect_timeout=3, read_timeout=8):
    parsed = urlsplit(url)
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    ips = [row[4][0] for row in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global or getattr(ipaddress.ip_address(ip), 'ipv4_mapped', None) for ip in ips):
        raise OSError('Destination is not public')

    class PinnedConnection(http.client.HTTPSConnection):
        def connect(self):
            # No second hostname lookup: the TLS identity is still the original host.
            sock = socket.create_connection((ips[0], 443), self.timeout)
            try:
                self.sock = self._context.wrap_socket(sock, server_hostname=parsed.hostname)
            except Exception:
                sock.close()
                raise

    connection = PinnedConnection(parsed.hostname, timeout=connect_timeout, context=ssl.create_default_context())
    try:
        path = parsed.path + (('?' + parsed.query) if parsed.query else '')
        connection.request(method, path, body=data, headers=headers or {})
        connection.sock.settimeout(read_timeout)
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise OSError('Response exceeds limit')
        return HttpResponse(response.status, {}, payload.decode('utf-8'))
    finally:
        connection.close()


def execute_endpoint(endpoint, query, body):
    config = endpoint.connection
    account = endpoint.account
    if not config.network_enabled or config.status not in ('active', 'verified'):
        raise PermissionDenied('平台连接未启用。')
    if is_verified_readonly(endpoint) and not config.sync_read_enabled:
        raise PermissionDenied('连接的只读同步未启用。')
    if account and (account.tenant_id != config.tenant_id or account.integration_config_id != config.id or account.status != 'active' or (account.expires_at and account.expires_at <= timezone.now())):
        raise PermissionDenied('平台账号授权不可用。')
    if not is_verified_readonly(endpoint) and (config.environment != 'sandbox' or not config.sync_write_enabled):
        raise PermissionDenied('写入接口仅允许已启用写入的测试连接。')
    if endpoint.auth_mode not in ('bearer', 'api_key', 'tiktok_shop', 'shopee_shop', 'lazada'):
        raise ValidationError('该鉴权方式尚未配置适配器。')
    if body is not None and not isinstance(body, dict):
        raise ValidationError('body 必须是对象。')
    if len(json.dumps({'query': query, 'body': body}).encode()) > 65536:
        raise ValidationError('请求超过 64 KiB 限制。')
    if endpoint.method in ('GET', 'HEAD', 'OPTIONS') and body:
        raise ValidationError('查询接口请通过 query 传参。')
    url = build_gateway_url(endpoint.base_url, endpoint.relative_path, query)
    token_id = account.token_id if account else config.token_id
    if not token_id:
        raise PermissionDenied('连接尚未配置可用的托管令牌。')
    secret = get_custody_backend().retrieve_access_token(token_id)
    if '\r' in secret or '\n' in secret:
        raise PermissionDenied('托管凭证格式无效。')
    headers = {'Authorization': f'Bearer {secret}'} if endpoint.auth_mode == 'bearer' else {'X-API-Key': secret}
    redactions = [secret]
    if endpoint.auth_mode in ('tiktok_shop', 'shopee_shop', 'lazada'):
        from .live_providers import _tiktok_sign, _lazada_sign, _hmac_sha256
        from .production_settings import get_runtime_platform_config
        platform = {'tiktok_shop': 'tiktok', 'shopee_shop': 'shopee', 'lazada': 'lazada'}[endpoint.auth_mode]
        if config.platform != platform or account is None:
            raise PermissionDenied('签名适配器与平台账号不匹配。')
        runtime = get_runtime_platform_config(platform)
        expected_host = urlsplit(runtime.get('api_host', '')).hostname
        if platform == 'lazada':
            from .readonly_clients import _lazada_api_host
            expected_host = urlsplit(_lazada_api_host(account.region, runtime.get('api_host', ''))).hostname
        if not expected_host or urlsplit(url).hostname != expected_host:
            raise PermissionDenied('接口域名与平台配置不匹配。')
        if platform == 'lazada' and endpoint.method != 'GET':
            raise ValidationError('Lazada 当前适配器支持 GET 查询。')
        app_id = str((config.platform_config or {}).get('partner_id' if platform == 'shopee' else 'app_key') or runtime.get('app_id') or '')
        secret_reference = config.credential_id or (config.platform_config or {}).get('app_secret_reference')
        if not app_id or not secret_reference:
            raise PermissionDenied('平台应用签名配置不完整。')
        signing_secret = get_custody_backend().retrieve_secret(secret_reference)
        redactions.append(signing_secret)
        reserved = {'app_key', 'partner_id', 'timestamp', 'sign', 'sign_method', 'access_token', 'shop_id', 'shop_cipher'}
        if reserved.intersection(query) or (body and reserved.intersection(body)):
            raise ValidationError('平台身份和签名参数由服务端填写。')
        params = dict(query)
        headers = {}
        if platform == 'tiktok':
            params.update(app_key=app_id, timestamp=int(time.time()), shop_cipher=account.shop_cipher)
            params['sign'] = _tiktok_sign(endpoint.relative_path, params, signing_secret, json.dumps(body, separators=(',', ':')) if body is not None and endpoint.method not in ('GET', 'HEAD', 'OPTIONS') else '')
            headers['x-tts-access-token'] = secret
        elif platform == 'shopee':
            timestamp = int(time.time())
            params.update(partner_id=app_id, timestamp=timestamp, access_token=secret, shop_id=account.platform_store_id)
            params['sign'] = _hmac_sha256(signing_secret, f'{app_id}{endpoint.relative_path}{timestamp}{secret}{account.platform_store_id}')
        else:
            params.update(app_key=app_id, access_token=secret, sign_method='sha256', timestamp=int(time.time()*1000))
            params['sign'] = _lazada_sign(endpoint.relative_path, params, signing_secret)
        redactions.append(params['sign'])
        url = build_gateway_url(endpoint.base_url, endpoint.relative_path, params)
    response = PlatformHttpClient(transport=gateway_transport, max_retries=0).request(
        endpoint.method, url, json_body=body if endpoint.method not in ('GET', 'HEAD', 'OPTIONS') else None,
        headers=headers, retry=False, connect_timeout=3, read_timeout=8,
    )
    # Never expose a reflected credential, even if a provider echoes request headers.
    def redact(value):
        if isinstance(value, str):
            for sensitive in redactions:
                value = value.replace(sensitive, '[REDACTED]')
            return value
        if isinstance(value, dict):
            return {redact(k): redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return '[REDACTED]' if json.dumps(value) in redactions else value
    try:
        return redact(json.loads(response.text))
    except ValueError:
        raise ValidationError('第三方响应不是有效 JSON。') from None
