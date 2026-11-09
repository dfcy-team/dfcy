import time
import uuid
from copy import copy
import redis
from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from .developer_apps import authenticate_developer_token
from .developer_transport import execute_endpoint
from .models import DeveloperEndpoint, DeveloperCallLog
from .oauth_errors import OAuthFlowError


_RATE_LIMIT_TTL_SECONDS = 120
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def _consume_rate_limit(app_id):
    """Consume one shared per-app minute slot; the script makes INCR/EXPIRE atomic."""
    minute = int(time.time() // 60)
    key = f'saas-collab:developer-gateway:rate:v1:{app_id}:{minute}'
    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        return int(client.eval(_RATE_LIMIT_SCRIPT, 1, key, _RATE_LIMIT_TTL_SECONDS)) <= 60
    finally:
        client.close()


@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def invoke(request, app_id, endpoint_code):
    request_id = uuid.uuid4().hex
    header = request.headers.get('Authorization', '')
    token = header[7:] if header.startswith('Bearer ') else ''
    app = authenticate_developer_token(token)
    if app is None or app.pk != app_id:
        return Response({'message': '开发令牌无效、已停用或已过期。', 'request_id': request_id}, status=401)
    status = 200
    started = time.monotonic()
    endpoint = None
    audit_path = None
    audit_method = None
    try:
        try:
            within_limit = _consume_rate_limit(app.pk)
        except (redis.RedisError, OSError, ValueError):
            status = 503
            return Response({'message': '调用服务暂时不可用，请稍后重试。', 'request_id': request_id}, status=status)
        if not within_limit:
            status = 429
            return Response({'message': '每分钟最多 60 次调用。', 'request_id': request_id}, status=status)
        endpoint = DeveloperEndpoint.objects.select_related('config', 'account').filter(
            config__tenant_id=app.tenant_id, approved=True, id__in=app.approved_endpoint_ids, code=endpoint_code,
        ).first()
        if endpoint is None:
            status = 403
            return Response({'message': '该接口尚未授权。', 'request_id': request_id}, status=status)
        if not isinstance(request.data, dict) or set(request.data) - {'query', 'body', 'path', 'method'}:
            status = 400
            return Response({'message': '仅允许 query、body、path 和 method 参数。', 'request_id': request_id}, status=status)
        if endpoint.scope_mode != 'platform' and ({'path', 'method'} & set(request.data)):
            status = 400
            return Response({'message': '固定路径接口不接受 path 或 method 参数。', 'request_id': request_id}, status=status)
        target = endpoint
        if endpoint.scope_mode == 'platform':
            dynamic_path = request.data.get('path')
            dynamic_method = request.data.get('method')
            if not isinstance(dynamic_path, str) or not 1 <= len(dynamic_path) <= 240 or not isinstance(dynamic_method, str):
                status = 400
                return Response({'message': '相对路径或调用方法无效。', 'request_id': request_id}, status=status)
            dynamic_method = dynamic_method.upper()
            if dynamic_method not in {'GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'}:
                status = 400
                return Response({'message': '请求方法无效。', 'request_id': request_id}, status=status)
            from .developer_transport import build_gateway_url
            build_gateway_url(endpoint.base_url, dynamic_path, {})
            audit_path, audit_method = dynamic_path, dynamic_method
            target = copy(endpoint)
            target.relative_path, target.method = dynamic_path, dynamic_method
        data = execute_endpoint(target, request.data.get('query', {}), request.data.get('body'))
        return Response({'data': data, 'request_id': request_id})
    except OAuthFlowError:
        status = 502
        return Response({'message': '第三方平台授权或调用失败，请检查平台连接。', 'request_id': request_id}, status=status)
    except APIException as exc:
        status = exc.status_code
        return Response({'message': '接口参数或平台授权不可用。', 'request_id': request_id}, status=status)
    except (OSError, ValueError):
        status = 502
        return Response({'message': '平台调用失败，请检查连接、平台授权及接口参数。', 'request_id': request_id}, status=status)
    finally:
        DeveloperCallLog.objects.create(tenant_id=app.tenant_id, application=app, action='invoke', detail={
            'request_id': request_id, 'endpoint_code': endpoint_code, 'status_code': status,
            'duration_ms': round((time.monotonic() - started) * 1000),
            **({'path': audit_path, 'method': audit_method} if audit_path is not None else {}),
        })
