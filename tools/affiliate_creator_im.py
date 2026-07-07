# -*- coding: utf-8 -*-
"""
TikTok Shop 联盟达人：用户名 -> creator_id / IM 链接（影刀专用）

影刀用法:
    cids = get_creator_ids(["jho_official.acc"], region="ph")
    im_links = get_im_links(["jho_official.acc"], region="th")
"""

import re
import socket
import sys
import time
from pathlib import Path

import requests

# ===================== 写死配置（按需修改） =====================
DFCY_ROOT = r"C:\Users\Administrator\Desktop\dfcy"
SHOP_PREFIX = "TKKJ1"
DEFAULT_REGION = "PH"
REGION_SHOP_KEYS = {
    "PH": SHOP_PREFIX + "PH",
    "TH": SHOP_PREFIX + "TH",
    "MY": SHOP_PREFIX + "MY",
}
IM_LINK_TEMPLATE = "https://affiliate.tiktok.com/seller/im?creator_id={creator_id}"
CREATOR_GET_PATH = "/affiliate_seller/202406/marketplace_creators/{creator_user_id}"
TIKTOK_PROFILE_URL = "https://www.tiktok.com/@{username}"
RATE_LIMIT_CODE = 36009002
PROXY_PORTS = (7897, 7890, 10808, 10809)
REQUEST_RETRY_WAIT = (8, 15, 25)
HTTP_TIMEOUT = 25
# ===============================================================

_TEST_ENV = Path(DFCY_ROOT) / "platforms" / "tiktok" / "test_env"
_SHOP_HUB = Path(DFCY_ROOT) / "platforms" / "tiktok" / "shop"
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))
if DFCY_ROOT not in sys.path:
    sys.path.insert(0, DFCY_ROOT)

from tts_client import TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok, load_env


def resolve_shop_key(region_or_shop=None):
    raw = (region_or_shop or DEFAULT_REGION).strip().upper()
    if not raw:
        raw = DEFAULT_REGION
    if raw in REGION_SHOP_KEYS:
        return REGION_SHOP_KEYS[raw]
    if raw.startswith(SHOP_PREFIX):
        return raw
    candidate = SHOP_PREFIX + raw
    if (_SHOP_HUB / ("config_%s.env" % candidate)).is_file():
        return candidate
    supported = ", ".join(sorted(REGION_SHOP_KEYS))
    raise ValueError("不支持的国家/店键: %r，可选: %s" % (region_or_shop, supported))


def prepare_network():
    import os

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        os.environ.pop(key, None)
    for port in PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                proxy = "http://127.0.0.1:%d" % port
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
                return proxy
        except OSError:
            continue
    return ""


def _requests_proxies():
    import os

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def normalize_username(name):
    s = (name or "").strip()
    if s.startswith("@"):
        s = s[1:]
    s = s.split("?", 1)[0].strip()
    s = s.split("/", 1)[0].strip()
    return s.lower()


def build_im_link(creator_id):
    return IM_LINK_TEMPLATE.format(creator_id=str(creator_id).strip())


def _parse_usernames(usernames):
    if usernames is None:
        return []
    if isinstance(usernames, str):
        parts = re.split(r"[,，;\n\r\t]+", usernames)
    elif isinstance(usernames, (list, tuple, set)):
        parts = list(usernames)
    else:
        parts = [str(usernames)]
    out, seen = [], set()
    for p in parts:
        u = normalize_username(str(p))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_tiktok_user_id(username):
    target = normalize_username(username)
    url = TIKTOK_PROFILE_URL.format(username=target)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, proxies=_requests_proxies(), timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        return "", "TikTok 主页请求失败: %s" % exc
    if resp.status_code != 200:
        return "", "TikTok 主页 HTTP %s" % resp.status_code
    text = resp.text
    if not re.search(r'"uniqueId"\s*:\s*"%s"' % re.escape(target), text, re.I):
        return "", "TikTok 主页未找到 @%s" % target
    m = re.search(r'"id"\s*:\s*"(\d{10,25})"', text)
    if not m:
        return "", "TikTok 主页未解析到 user_id"
    return m.group(1), ""


def _extract_handle(item):
    for key in ("username", "handle", "creator_user_name", "unique_id", "nickname"):
        val = item.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            val = val.get("value") or val.get("text")
        s = normalize_username(str(val))
        if s:
            return s
    return ""


def get_affiliate_creator(client, token, cipher, creator_user_id):
    path = CREATOR_GET_PATH.format(creator_user_id=str(creator_user_id).strip())
    last_err = ""
    for wait in (0,) + REQUEST_RETRY_WAIT:
        if wait:
            time.sleep(wait)
        resp = client.get(path, token, {"shop_cipher": cipher})
        code = resp.get("code")
        if code == RATE_LIMIT_CODE:
            last_err = "限流 code=%s" % code
            continue
        if not is_ok(resp):
            last_err = "code=%s %s" % (code, str(resp.get("message", ""))[:120])
            break
        creator = (resp.get("data") or {}).get("creator") or {}
        if creator:
            return creator, ""
        last_err = "联盟 API 无 creator 数据"
        break
    return {}, last_err or "联盟 API 查询失败"


def search_creator_by_username(client, token, cipher, username):
    target = normalize_username(username)
    user_id, err = fetch_tiktok_user_id(target)
    if not user_id:
        return "", "", err or "未解析到 TikTok user_id"
    creator, err = get_affiliate_creator(client, token, cipher, user_id)
    if not creator:
        return "", "", err or "联盟未找到该达人"
    handle = _extract_handle(creator)
    if handle and handle != target:
        return "", handle, "handle 不匹配，期望 %s 实际 %s" % (target, handle)
    return user_id, handle or target, ""


def _init_client(shop_key):
    env_path = _SHOP_HUB / ("config_%s.env" % shop_key.upper())
    if not env_path.is_file():
        raise FileNotFoundError("env 不存在: %s" % env_path)
    hub = env_path.parent
    if (hub / "app.env").exists():
        load_env(hub / "app.env", override=False)
    init_shop_config(_TEST_ENV, ["--config", str(env_path)])
    client = TikTokShopClient(cfg("TTS_APP_KEY"), cfg("TTS_APP_SECRET"))
    client.config_path = env_path
    token = get_shop_token(client, env_path)
    cipher = cfg("TTS_SHOP_CIPHER")
    if not token or not cipher:
        raise RuntimeError("token/cipher 无效，请检查 %s" % env_path)
    return client, token, cipher


def resolve_im_links(usernames, region=DEFAULT_REGION, shop_key=None):
    names = _parse_usernames(usernames)
    if not names:
        return []

    key = resolve_shop_key(shop_key or region)
    region_code = key.replace(SHOP_PREFIX, "")
    for code, shop in REGION_SHOP_KEYS.items():
        if shop == key:
            region_code = code
            break

    proxy = prepare_network()
    client, token, cipher = _init_client(key)
    results = []
    for name in names:
        row = {
            "username": name,
            "region": region_code,
            "shop_key": key,
            "creator_id": "",
            "im_link": "",
            "ok": False,
            "source": "none",
            "msg": "",
            "proxy": proxy,
        }
        cid, matched_handle, err = search_creator_by_username(client, token, cipher, name)
        if cid:
            row["creator_id"] = cid
            row["im_link"] = build_im_link(cid)
            row["ok"] = True
            row["source"] = "api"
            if matched_handle and matched_handle != name:
                row["msg"] = "匹配 handle=%s" % matched_handle
        else:
            row["msg"] = err or "未找到达人"
        results.append(row)
        time.sleep(0.5)
    return results


def get_im_links(usernames, region=DEFAULT_REGION, shop_key=None):
    """传用户名列表 + 国家(ph/th/my) -> IM 链接列表"""
    return [
        r["im_link"] if r["ok"] else ""
        for r in resolve_im_links(usernames, region=region, shop_key=shop_key)
    ]


def get_creator_ids(usernames, region=DEFAULT_REGION, shop_key=None):
    """传用户名列表 + 国家(ph/th/my) -> creator_id 列表"""
    return [
        r["creator_id"] if r["ok"] else ""
        for r in resolve_im_links(usernames, region=region, shop_key=shop_key)
    ]
