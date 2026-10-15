"""Documented WorkTool HTTP adapter. No appchat or mass-send fallback."""
import json
from datetime import timedelta
import requests
from django.db import transaction
from django.utils import timezone
from .models import NotificationThrottle
from .notification_config import resolve_robot

API = 'https://api.worktool.ymdyes.cn'


class TransportError(Exception):
    def __init__(self, code, *, ambiguous=False):
        self.code, self.ambiguous = code, ambiguous
        super().__init__(code)


class RateLimited(TransportError):
    def __init__(self):
        super().__init__('rate_limited')


@transaction.atomic
def reserve_request():
    obj, _ = NotificationThrottle.objects.select_for_update().get_or_create(provider='worktool')
    now = timezone.now()
    if obj.next_at > now:
        raise RateLimited()
    # Provider documents 60 requests/min/IP; reserve all reads and writes alike.
    obj.next_at = now + timedelta(seconds=1.1)
    obj.save(update_fields=['next_at'])


class WorkTool:
    def _request(self, channel, method, path, *, params=None, body=None):
        robot = resolve_robot(channel)
        reserve_request()
        try:
            response = requests.request(method, API + path, params={'robotId': robot, **(params or {})},
                json=body, timeout=(5, 20), allow_redirects=False)
            if response.status_code >= 500:
                raise TransportError('provider_server_error', ambiguous=method == 'POST')
            if response.status_code != 200:
                raise TransportError('provider_http_rejected', ambiguous=method == 'POST' and response.status_code not in (400,401,403,404,429))
            if len(response.content) > 1024 * 1024:
                raise TransportError('provider_response_too_large', ambiguous=method == 'POST')
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            if result.get('code') not in (0, 200):
                code = result.get('code')
                if code == 101014:
                    raise TransportError('provider_duplicate_unknown', ambiguous=method == 'POST')
                raise TransportError('provider_rejected', ambiguous=method == 'POST' and code not in (101011,101012,101013,201101,201102,201103,201104,201107,201108))
            return result
        except requests.ConnectTimeout:
            raise TransportError('connect_timeout') from None
        except requests.RequestException:
            # Do not log str(exc): its URL contains robot credentials.
            raise TransportError('network_result_unknown', ambiguous=method == 'POST') from None
        except (ValueError, TypeError):
            raise TransportError('provider_schema_unknown', ambiguous=method == 'POST') from None
        finally:
            robot = None

    def online(self, channel):
        data = self._request(channel, 'GET', '/robot/robotInfo/online').get('data')
        if isinstance(data, bool):
            return data
        if isinstance(data, dict) and isinstance(data.get('online'), bool):
            return data['online']
        raise TransportError('online_schema_unknown')

    def send(self, channel, target, *, text=None, file_url=None, object_name=None):
        command = {'titleList': [target]}
        if file_url:
            command.update(type=218, objectName=object_name, fileUrl=file_url, fileType='file')
        else:
            command.update(type=203, receivedContent=text)
        result = self._request(channel, 'POST', '/wework/sendRawMessage',
            body={'socketType': 2, 'list': [command]})
        message_id = result.get('data')
        if isinstance(message_id, bool) or not isinstance(message_id, (str, int)) or not str(message_id).strip() or len(str(message_id)) > 128:
            raise TransportError('accepted_without_message_id', ambiguous=True)
        return str(message_id)

    def result(self, channel, message_id):
        result = self._request(channel, 'GET', '/robot/rawMsg/list',
            params={'page': 1, 'size': 10, 'messageId': message_id, 'sort': 'run_time,desc'})
        data = result.get('data')
        if not isinstance(data, list):
            raise TransportError('execution_schema_unknown')
        rows = [row for row in data if isinstance(row, dict) and str(row.get('messageId')) == message_id]
        if not rows:
            return None
        if len(rows) != 1:
            raise TransportError('execution_schema_unknown')
        row = rows[0]
        def names(value):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    return None
            return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else None
        return {'messageId': message_id, 'errorCode': row.get('rawSuccess'), 'type': row.get('type'),
                'successList': names(row.get('successList')), 'failList': names(row.get('failList'))}
