"""Independent Ads browser relay; callbacks stay encrypted on the public server."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from flask import Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from tiktok_ads_bridge_protocol import (
    CALLBACK_URI, FETCH_URI, RETURN_URI, START_URI, derived_key, flow_payload,
    sign_token, unique_object, validate_fetch, validate_flow, verify_token,
)

COOKIE = "__Host-saas_tk_ads_bridge"
_WINDOWS_TEST_LOCK = threading.Lock()
SCRIPT = """(async()=>{
const fragment=location.hash.slice(1);history.replaceState(null,'',location.pathname);
function showRestart(message){const link=document.createElement('a');link.href='https://192.168.2.34:8443/master-data/stores';link.textContent='返回 SaaS 重新发起授权';document.body.replaceChildren(document.createTextNode(message+' '),link);}
const match=/^ticket=([A-Za-z0-9_-]+[.][A-Za-z0-9_-]+)$/.exec(fragment);
if(!match||match[0]!==fragment||match[1].length>6200){showRestart('当前跳转信息已失效，刷新此页不能恢复授权，无需等待。');return;}
try{const r=await fetch(location.pathname,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:match[1]})});
if(r.status===409){showRestart('当前浏览器另有不同账号或店铺的授权，请返回 SaaS 核对账号与店铺。');return;}
const d=await r.json();if(!r.ok||typeof d.next!=='string')throw new Error();location.assign(d.next);
}catch{showRestart('广告授权转接未完成，请重新发起，无需等待。');}})();"""
SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
PAGE = ('<!doctype html><html><head><meta charset="utf-8"><title>TK 广告授权</title></head>'
        '<body>正在前往 TikTok 广告授权…<script>' + SCRIPT + '</script></body></html>')


def _secure(response):
    request.environ["QUERY_STRING"] = ""
    request.environ["RAW_URI"] = request.path
    request.environ["REQUEST_URI"] = request.path
    response.headers.update({
        "Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; script-src 'sha256-" + SCRIPT_HASH
        + "'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    })
    return response


def _reject(status=400):
    return _secure(jsonify(error="ADS_RELAY_REJECTED")), status


def _key():
    path = current_app.config.get("TIKTOK_ADS_BRIDGE_KEY_FILE")
    if not path:
        raise ValueError("Ads relay key unavailable")
    path = Path(path)
    info = path.lstat()
    if not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise ValueError("Ads relay key unavailable")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
        raise ValueError("Ads relay key unavailable")
    value = path.read_bytes().strip()
    if len(value) < 32:
        raise ValueError("Ads relay key unavailable")
    return value


def _directory():
    path = Path(current_app.config["TIKTOK_ADS_RECEIPT_DIRECTORY"])
    if not path.is_absolute():
        raise ValueError("Invalid receipt directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("Invalid receipt directory")
    return path


def _json_body():
    if request.mimetype != "application/json" or request.content_length and request.content_length > 8192:
        raise ValueError("Invalid request")
    raw = request.stream.read(8193)
    if len(raw) > 8192:
        raise ValueError("Invalid request")
    body = json.loads(raw.decode(), object_pairs_hook=unique_object)
    if not isinstance(body, dict) or set(body) != {"ticket"}:
        raise ValueError("Invalid request")
    return body["ticket"]


def _fernet(key):
    return Fernet(base64.urlsafe_b64encode(derived_key(key, b"dfcy-ads-callback-cache-v1")))


@contextmanager
def _directory_lock(directory):
    if os.name == "nt":
        with _WINDOWS_TEST_LOCK:
            yield
        return
    import fcntl
    fd = os.open(directory / ".capacity.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _unlink_owned(path, info):
    current = path.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError("Receipt identity changed")
    path.unlink()


def _reap_receipts(directory, key):
    # Bounded reclamation; never remove active, oversized, linked, or valid receipts.
    entries = []
    for path in directory.glob("*.receipt"):
        try:
            entries.append((path.lstat().st_mtime, path))
        except FileNotFoundError:
            continue
    candidates = [path for _, path in sorted(entries)[:256]]
    removed = 0
    for path in candidates:
        if removed >= 64:
            break
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                if os.name != "nt":
                    import fcntl
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 30000 or info.st_nlink != 1:
                    continue
                raw = stream.read(30001)
                expired = raw == b"USED"
                if not expired:
                    try:
                        payload = json.loads(_fernet(key).decrypt(raw))
                        expired = type(payload.get("exp")) is int and payload["exp"] <= int(time.time())
                    except (ValueError, InvalidToken):
                        expired = info.st_mtime < time.time() - 600
                if expired:
                    _unlink_owned(path, info)
                    removed += 1
        except (OSError, ValueError):
            continue
    return removed


def _save_receipt(claims, params, key):
    directory = _directory()
    with _directory_lock(directory):
        _reap_receipts(directory, key)
        if sum(1 for _ in directory.glob("*.receipt")) >= 1000:
            raise ValueError("Receipt storage capacity reached")
        receipt_id = secrets.token_hex(32)
        payload = {"flow": flow_payload(claims), "callback_params": params,
                   "exp": min(claims["exp"], int(time.time()) + 120)}
        encrypted = _fernet(key).encrypt(json.dumps(payload, sort_keys=True).encode())
        path = directory / (receipt_id + ".receipt")
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
    return receipt_id


def _take_receipt(claims, key):
    import fcntl
    path = _directory() / (claims["receipt_id"] + ".receipt")
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 30000 or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("Invalid receipt")
        payload = json.loads(_fernet(key).decrypt(stream.read(30001), ttl=120))
        if payload["exp"] <= int(time.time()):
            raise ValueError("Expired receipt")
        flow = validate_flow(payload["flow"])
        if any(claims[field] != flow[field] for field in
               ("session_id", "actor_id", "tenant_id", "store_id", "config_id")):
            raise ValueError("Invalid receipt context")
        # Clear only this claimed, bounded receipt; do not replay a callback after an uncertain fetch.
        stream.seek(0)
        stream.write(b"USED")
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
        _unlink_owned(path, info)
    return {"session_id": flow["session_id"], "callback_params": payload["callback_params"]}


def _handle():
    start, fetch, callback = map(lambda uri: urlsplit(uri).path, (START_URI, FETCH_URI, CALLBACK_URI))
    if request.path not in {start, fetch, callback, callback + "/"}:
        return None
    if request.path in {start, fetch}:
        if request.query_string:
            return _reject()
        if request.path == start and request.method == "GET":
            return _secure(Response(PAGE, content_type="text/html; charset=utf-8"))
        if request.method != "POST":
            return _reject(405)
        try:
            key = _key()
            if request.path == fetch:
                claims = validate_fetch(verify_token(_json_body(), key, "fetch"))
                return _secure(jsonify(_take_receipt(claims, key)))
            if request.headers.get("Origin") != "https://dingfengchuangyu.com":
                return _reject()
            ticket = _json_body()
            claims = validate_flow(verify_token(ticket, key, "start"))
            old = request.cookies.get(COOKIE)
            if old:
                try:
                    previous = validate_flow(verify_token(old, key, "start"))
                except ValueError:
                    previous = None
                # A new signed request for the same owner and store can replace
                # an unfinished browser flow immediately. Old callbacks still
                # fail the exact state check against the newest cookie.
                context = ("actor_id", "tenant_id", "store_id", "config_id", "app_id", "callback_uri", "return_uri")
                if previous and any(previous[field] != claims[field] for field in context):
                    return _reject(409)
            response = _secure(jsonify(next=claims["authorization_url"]))
            response.set_cookie(COOKIE, ticket, max_age=min(600, claims["exp"] - int(time.time())),
                                secure=True, httponly=True, samesite="Lax", path="/")
            return response
        except (ValueError, TypeError, OSError, KeyError, InvalidToken, BadRequest, RequestEntityTooLarge):
            return _reject()

    # Leave all Shop, Content, and existing dfcy Ads callbacks to their original handlers.
    if "app_key" in request.args or "scopes" in request.args:
        return None
    states = request.args.getlist("state")
    if not any(value.startswith("saas_ads_") for value in states):
        return None
    if request.method != "GET" or len(states) != 1 or len(request.query_string) > 16000:
        return _reject()
    try:
        key = _key()
        claims = validate_flow(verify_token(request.cookies.get(COOKIE), key, "start"))
        pairs = parse_qsl(request.query_string.decode("utf-8", errors="strict"),
                          keep_blank_values=True, max_num_fields=12, errors="strict")
        params = dict(pairs)
        if (len(params) != len(pairs) or params.get("state") != claims["state"]
                or set(params) - {"state", "auth_code", "code", "id", "error", "error_description"}
                or any(len(v) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in k + v) for k, v in pairs)
                or params.get("id", claims["app_id"]) != claims["app_id"]
                or not (params.get("auth_code", "").strip() or params.get("error", "").strip())):
            raise ValueError("Invalid callback")
        clean = {"state": claims["state"]}
        if params.get("error"):
            clean["error"] = "authorization_denied"
        else:
            clean["auth_code"] = params["auth_code"]
        receipt_id = _save_receipt(claims, clean, key)
        response = Response(status=303, headers={"Location": RETURN_URI + "#" + urlencode({
            "session_id": claims["session_id"], "receipt_id": receipt_id})})
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return _secure(response)
    except (ValueError, TypeError, OSError, KeyError):
        return _reject()


def install(app, key_file, receipt_directory):
    app.config["TIKTOK_ADS_BRIDGE_KEY_FILE"] = key_file
    app.config["TIKTOK_ADS_RECEIPT_DIRECTORY"] = receipt_directory
    handlers = app.before_request_funcs.setdefault(None, [])
    if _handle not in handlers:
        handlers.insert(0, _handle)
