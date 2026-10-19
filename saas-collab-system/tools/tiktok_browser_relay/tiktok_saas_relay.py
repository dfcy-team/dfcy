"""Isolated browser-only Shop OAuth relay. No token exchange or persistence."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from flask import Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from tiktok_bridge_protocol import (
    CALLBACK_URI, RETURN_URI, START_URI, flow_payload, sign_token,
    validate_flow, verify_token,
)

COOKIE = "__Host-saas_tk_bridge"
SCRIPT = """(async()=>{
const fragment=location.hash.slice(1);
history.replaceState(null,'',location.pathname);
const match=/^ticket=([A-Za-z0-9_-]+[.][A-Za-z0-9_-]+)$/.exec(fragment);
const ticket=match&&match[0]===fragment?match[1]:null;
if(!ticket||ticket.length>3000){document.body.textContent='授权跳转信息无效，请返回 SaaS 店铺重新发起授权。';return;}
try{
const r=await fetch(location.pathname,{method:'POST',credentials:'same-origin',
headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})});
if(r.status===409){document.body.textContent='已有一项 TK 授权尚未完成，请先完成原授权，或等待十分钟后重新发起；不会覆盖原授权会话。';return;}
const data=await r.json();
if(!r.ok||typeof data.next!=='string')throw new Error();
location.assign(data.next);
}catch{document.body.textContent='授权转接未完成，请返回 SaaS 店铺重新发起；请勿重复使用旧回调地址。';}
})();"""
SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
PAGE = ('<!doctype html><html><head><meta charset="utf-8">'
        '<title>TK 店铺授权</title></head><body>正在前往 TikTok 授权…<script>'
        + SCRIPT + '</script></body></html>')
ERROR = '\u6388\u6743\u672a\u5b8c\u6210\uff0c\u8bf7\u8fd4\u56de\u7cfb\u7edf\u91cd\u65b0\u53d1\u8d77\u6388\u6743\u3002'


def _secure(response):
    # Gunicorn logs after request handling; scrub only intercepted requests.
    request.environ['QUERY_STRING'] = ''
    request.environ['RAW_URI'] = request.path
    request.environ['REQUEST_URI'] = request.path
    response.headers.update({
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'none'; script-src 'sha256-"
        + SCRIPT_HASH + "'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    })
    return response


def _reject(status=400):
    return _secure(Response(ERROR, status=status, content_type='text/html; charset=utf-8'))


def _key():
    try:
        path = (current_app.config.get('TIKTOK_BROWSER_BRIDGE_KEY_FILE')
                or os.environ.get('TIKTOK_BROWSER_BRIDGE_KEY_FILE', ''))
        if not path:
            return None
        with Path(path).open('rb') as source:
            value = source.read(4097)
        if len(value) > 4096:
            return None
        value = value.strip()
        return value if 32 <= len(value) <= 4096 else None
    except (OSError, ValueError):
        return None


def _claims(ticket, key):
    if (not isinstance(ticket, str) or len(ticket.encode('utf-8')) > 3000
            or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', ticket)):
        raise ValueError('Invalid ticket')
    return validate_flow(verify_token(ticket, key, 'start'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _handle():
    start = urlsplit(START_URI).path
    callback = urlsplit(CALLBACK_URI).path
    if request.path not in {start, callback, callback + '/'}:
        return None
    if request.path == start:
        if request.query_string:
            return _reject()
        key = _key()
        if key is None:
            return _reject(503)
        if request.method == 'GET':
            return _secure(Response(PAGE, content_type='text/html; charset=utf-8'))
        if request.method != 'POST':
            return _reject(405)
        if (request.headers.get('Origin') != 'https://dingfengchuangyu.com'
                or request.mimetype != 'application/json'
                or request.content_length and request.content_length > 30000):
            return _reject()
        try:
            raw = request.stream.read(30001)
            if len(raw) > 30000:
                return _reject()
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError, BadRequest, RequestEntityTooLarge):
            return _reject()
        if not isinstance(data, dict) or set(data) != {'ticket'}:
            return _reject()
        ticket = data['ticket']
        try:
            claims = _claims(ticket, key)
        except (ValueError, TypeError):
            return _reject()
        old = request.cookies.get(COOKIE)
        if old:
            try:
                previous = _claims(old, key)
            except (ValueError, TypeError):
                previous = None
            if previous and (previous['state'] != claims['state']
                             or previous['session_id'] != claims['session_id']):
                return _reject(409)
        response = _secure(jsonify(next=claims['authorization_url']))
        response.set_cookie(COOKIE, ticket, max_age=min(600, claims['exp'] - int(time.time())),
                            secure=True, httponly=True, samesite='Lax', path='/')
        return response

    ticket = request.cookies.get(COOKIE)
    if not ticket:
        return None
    args = request.args
    states = args.getlist('state')
    if ('auth_code' in args or (len(states) == 1 and states[0].startswith('ads_'))
            or ('scopes' in args and 'app_key' not in args)):
        return None
    if 'app_key' not in args or not any(k in args for k in ('code', 'error', 'state')):
        return None
    key = _key()
    if key is None:
        return _reject(503)
    if request.method != 'GET':
        return _reject(405)
    try:
        claims = _claims(ticket, key)
        if len(request.query_string) > 16000:
            return _reject()
        pairs = parse_qsl(request.query_string.decode('utf-8', errors='strict'),
                          keep_blank_values=True, max_num_fields=40, errors='strict')
        params = dict(pairs)
        if (len(params) != len(pairs)
                or any(len(value) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in name + value)
                       for name, value in pairs)
                or not set(params) <= {'code', 'state', 'error', 'app_key', 'locale', 'shop_region'}
                or params.get('app_key') != claims['app_key']
                or ('state' in params and params['state'] != claims['state'])
                or params.get('shop_region', '').upper() != claims['region']
                or not (params.get('code', '').strip() or params.get('error', '').strip())):
            return _reject()
        remaining = claims['exp'] - int(time.time())
        receipt = sign_token({**flow_payload(claims), 'callback_params': params,
                              'flow_expires_at': claims['exp']}, key, 'callback',
                             ttl=min(120, remaining))
    except (ValueError, TypeError, UnicodeError):
        return _reject()
    response = Response(status=303, headers={
        'Location': RETURN_URI + '#' + urlencode({'receipt': receipt})})
    response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='Lax')
    return _secure(response)


def install(app, key_file=None):
    """Install before existing publicCreator/login gates, once per app."""
    if key_file is not None:
        app.config['TIKTOK_BROWSER_BRIDGE_KEY_FILE'] = key_file
    handlers = app.before_request_funcs.setdefault(None, [])
    if _handle not in handlers:
        handlers.insert(0, _handle)
