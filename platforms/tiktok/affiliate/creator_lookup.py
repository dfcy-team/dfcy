# -*- coding: utf-8 -*-
"""TikTok Shop 联盟达人：用户名 -> creator_id（共用逻辑）"""

import os
import re
import socket
import sys
import time
from pathlib import Path

import requests

_AFFILIATE_DIR = Path(__file__).resolve().parent
ENV_ROOT = _AFFILIATE_DIR.parent
_TEST_ENV = ENV_ROOT / "test_env"
_PROJECT = _AFFILIATE_DIR.parents[2]
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tts_client import TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok, load_env

SHOP_PREFIX = "TKKJ1"
DEFAULT_REGION = "PH"
REGION_SHOP_KEYS = {
    "PH": f"{SHOP_PREFIX}PH",
    "TH": f"{SHOP_PREFIX}TH",
    "MY": f"{SHOP_PREFIX}MY",
}
DEFAULT_SHOP_KEY = REGION_SHOP_KEYS[DEFAULT_REGION]
IM_LINK_TEMPLATE = "https://affiliate.tiktok.com/seller/im?creator_id={user_id}"
DETAIL_LINK_TEMPLATE = (
    "https://affiliate.tiktok.com/connection/creator/detail"
    "?cid={affiliate_cid}&shop_region={region}"
)
CREATOR_SEARCH_PATH = "/affiliate_seller/202406/marketplace_creators/search"
CREATOR_GET_PATH = "/affiliate_seller/202406/marketplace_creators/{creator_user_id}"
TIKTOK_PROFILE_URL = "https://www.tiktok.com/@{username}"
RATE_LIMIT_CODE = 36009002
PROXY_PORTS = (7897, 7890, 10808, 10809)
REQUEST_RETRY_WAIT = (8, 15, 25)
HTTP_TIMEOUT = 25


def prepare_network() -> str:
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
                proxy = f"http://127.0.0.1:{port}"
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
                return proxy
        except OSError:
            continue
    return ""


def _requests_proxies() -> dict:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def resolve_shop_key(region_or_shop: str = DEFAULT_REGION) -> str:
    raw = (region_or_shop or DEFAULT_REGION).strip().upper()
    if not raw:
        raw = DEFAULT_REGION

    if raw in REGION_SHOP_KEYS:
        return REGION_SHOP_KEYS[raw]

    if raw.startswith(SHOP_PREFIX):
        return raw

    hub = ENV_ROOT / "shop"
    candidate = f"{SHOP_PREFIX}{raw}"
    if (hub / f"config_{candidate}.env").is_file():
        return candidate

    supported = ", ".join(sorted(REGION_SHOP_KEYS))
    raise ValueError(f"不支持的国家/店键: {region_or_shop!r}，可选: {supported} 或 {SHOP_PREFIX}PH 等")


def normalize_username(name: str) -> str:
    s = (name or "").strip()
    if s.startswith("@"):
        s = s[1:]
    s = s.split("?", 1)[0].strip()
    s = s.split("/", 1)[0].strip()
    return s.lower()


def build_im_link(user_id: str) -> str:
    return IM_LINK_TEMPLATE.format(user_id=str(user_id).strip())


def build_detail_link(affiliate_cid: str, region: str) -> str:
    return DETAIL_LINK_TEMPLATE.format(
        affiliate_cid=str(affiliate_cid).strip(),
        region=str(region or DEFAULT_REGION).strip().upper(),
    )


def _extract_affiliate_cid(item: dict) -> str:
    """联盟前台详情页 cid（oecuid）。Open API 202406 search 通常不返回该字段。"""
    if not item:
        return ""
    candidates = (
        "creator_oec_id",
        "creator_oecuid",
        "creator_oec_uid",
        "oec_id",
        "oecuid",
        "cid",
        "creator_id",
        "creator_user_id",
    )
    for key in candidates:
        val = item.get(key)
        if isinstance(val, dict):
            val = val.get("value") or val.get("id")
        if val is not None and re.fullmatch(r"\d{10,25}", str(val).strip()):
            return str(val).strip()
    return ""


def search_marketplace_creators(
    client,
    token,
    cipher,
    keyword: str,
    *,
    page_size: int = 20,
) -> tuple[list[dict], str]:
    """POST marketplace_creators/search；失败时返回 ([], 原因)。"""
    last_err = ""
    for wait in (0, *REQUEST_RETRY_WAIT):
        if wait:
            time.sleep(wait)
        resp = client.post(
            CREATOR_SEARCH_PATH,
            token,
            {"keyword": keyword},
            {"shop_cipher": cipher, "page_size": page_size},
        )
        code = resp.get("code")
        if code == RATE_LIMIT_CODE:
            last_err = f"search 限流 code={code}"
            continue
        if not is_ok(resp):
            last_err = f"search code={code} {str(resp.get('message', ''))[:120]}"
            break
        creators = (resp.get("data") or {}).get("creators") or []
        return creators if isinstance(creators, list) else [], ""
    return [], last_err or "search 失败"


def lookup_affiliate_cid(
    client,
    token,
    cipher,
    username: str,
    *,
    user_id: str = "",
) -> tuple[str, str]:
    """尝试从 search 结果取联盟前台 cid；Open API 无字段时返回空 + 说明。"""
    target = normalize_username(username)
    creators, err = search_marketplace_creators(client, token, cipher, target)
    if err and not creators:
        return "", err

    matched: dict | None = None
    for item in creators:
        if not isinstance(item, dict):
            continue
        if normalize_username(_extract_handle(item) or str(item.get("username") or "")) == target:
            matched = item
            break
    if matched is None and len(creators) == 1:
        matched = creators[0] if isinstance(creators[0], dict) else None

    if matched:
        cid = _extract_affiliate_cid(matched)
        if cid and user_id and cid == user_id:
            cid = ""
        if cid:
            return cid, ""

    if creators:
        return "", "search 成功但 Open API 响应无 affiliate_cid 字段（联盟前台 cid 未开放）"
    return "", err or "search 无结果"


def _parse_usernames(usernames) -> list[str]:
    if usernames is None:
        return []
    if isinstance(usernames, str):
        parts = re.split(r"[,，;\n\r\t]+", usernames)
    elif isinstance(usernames, (list, tuple, set)):
        parts = list(usernames)
    else:
        parts = [str(usernames)]
    out = []
    seen = set()
    for p in parts:
        u = normalize_username(str(p))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_tiktok_user_id(username: str) -> tuple[str, str]:
    target = normalize_username(username)
    url = TIKTOK_PROFILE_URL.format(username=target)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(
            url,
            headers=headers,
            proxies=_requests_proxies(),
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        return "", f"TikTok 主页请求失败: {exc}"

    if resp.status_code != 200:
        return "", f"TikTok 主页 HTTP {resp.status_code}"

    text = resp.text
    if not re.search(rf'"uniqueId"\s*:\s*"{re.escape(target)}"', text, re.I):
        return "", f"TikTok 主页未找到 @{target}"

    uid_match = re.search(r'"id"\s*:\s*"(\d{10,25})"', text)
    if not uid_match:
        return "", "TikTok 主页未解析到 user_id"
    return uid_match.group(1), ""


def _extract_handle(item: dict) -> str:
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


def get_affiliate_creator(client, token, cipher, creator_user_id: str) -> tuple[dict, str]:
    path = CREATOR_GET_PATH.format(creator_user_id=str(creator_user_id).strip())
    last_err = ""

    for wait in (0, *REQUEST_RETRY_WAIT):
        if wait:
            time.sleep(wait)
        resp = client.get(path, token, {"shop_cipher": cipher})
        code = resp.get("code")
        if code == RATE_LIMIT_CODE:
            last_err = f"限流 code={code}，稍后重试"
            continue
        if not is_ok(resp):
            last_err = f"code={code} {str(resp.get('message', ''))[:120]}"
            break
        creator = (resp.get("data") or {}).get("creator") or {}
        if creator:
            return creator, ""
        last_err = "联盟 API 无 creator 数据"
        break
    return {}, last_err or "联盟 API 查询失败"


def search_creator_by_username(client, token, cipher, username) -> tuple[str, str, str, str]:
    """返回 (user_id, affiliate_cid, matched_handle, err)。"""
    target = normalize_username(username)
    user_id, err = fetch_tiktok_user_id(target)
    if not user_id:
        return "", "", "", err or "未解析到 TikTok user_id"

    creator, err = get_affiliate_creator(client, token, cipher, user_id)
    if not creator:
        return "", "", "", err or "联盟未找到该达人"

    handle = _extract_handle(creator)
    if handle and handle != target:
        return "", "", handle, f"handle 不匹配，期望 {target} 实际 {handle}"

    affiliate_cid = _extract_affiliate_cid(creator)
    if affiliate_cid and affiliate_cid == user_id:
        affiliate_cid = ""
    if not affiliate_cid:
        affiliate_cid, search_err = lookup_affiliate_cid(
            client, token, cipher, target, user_id=user_id
        )
        if not affiliate_cid and search_err and "限流" in search_err:
            return user_id, "", handle or target, search_err

    return user_id, affiliate_cid, handle or target, ""


def _init_client(shop_key: str):
    hub = ENV_ROOT / "shop"
    env_path = hub / f"config_{shop_key.upper()}.env"
    if not env_path.is_file():
        raise FileNotFoundError(f"env 不存在: {env_path}")

    if (hub / "app.env").exists():
        load_env(hub / "app.env", override=False)
    init_shop_config(_TEST_ENV, ["--config", str(env_path)])

    app_key = cfg("TTS_APP_KEY")
    app_secret = cfg("TTS_APP_SECRET")
    cipher = cfg("TTS_SHOP_CIPHER")
    if not app_key or not app_secret or not cipher:
        raise RuntimeError(f"{env_path.name} 缺少 TTS_APP_KEY / TTS_APP_SECRET / TTS_SHOP_CIPHER")

    client = TikTokShopClient(app_key, app_secret)
    client.config_path = env_path
    token = get_shop_token(client, env_path)
    if not token:
        raise RuntimeError("无法获取 access_token，请检查 env 或重新授权")
    return client, token, cipher


def resolve_creators(
    usernames,
    region: str = DEFAULT_REGION,
    shop_key: str | None = None,
) -> list[dict]:
    """用户名列表 -> user_id / affiliate_cid（含 region / shop_key / 链接）。"""
    names = _parse_usernames(usernames)
    if not names:
        return []

    key = resolve_shop_key(shop_key or region)
    region_code = next((r for r, k in REGION_SHOP_KEYS.items() if k == key), key.replace(SHOP_PREFIX, ""))

    proxy = prepare_network()
    client, token, cipher = _init_client(key)
    results = []

    for name in names:
        row = {
            "username": name,
            "region": region_code,
            "shop_key": key,
            "user_id": "",
            "affiliate_cid": "",
            "creator_id": "",  # 兼容旧字段 = user_id
            "im_link": "",
            "detail_link": "",
            "ok": False,
            "source": "none",
            "msg": "",
            "proxy": proxy,
        }
        user_id, affiliate_cid, matched_handle, err = search_creator_by_username(
            client, token, cipher, name
        )
        if user_id:
            row["user_id"] = user_id
            row["creator_id"] = user_id
            row["im_link"] = build_im_link(user_id)
            row["ok"] = True
            row["source"] = "api"
            if affiliate_cid:
                row["affiliate_cid"] = affiliate_cid
                row["detail_link"] = build_detail_link(affiliate_cid, region_code)
            else:
                row["msg"] = (
                    "已得 user_id；affiliate_cid 需联盟前台链接或更高版本 Open API（当前 search 不返回 cid）"
                )
            if matched_handle and matched_handle != name:
                extra = f"匹配 handle={matched_handle}"
                row["msg"] = f"{row['msg']}；{extra}" if row["msg"] else extra
        else:
            row["msg"] = err or "未找到达人"
        results.append(row)
        time.sleep(0.5)
    return results


def get_user_ids(
    usernames,
    region: str = DEFAULT_REGION,
    shop_key: str | None = None,
) -> list[str]:
    return [r["user_id"] if r["ok"] else "" for r in resolve_creators(usernames, region=region, shop_key=shop_key)]


def get_creator_ids(
    usernames,
    region: str = DEFAULT_REGION,
    shop_key: str | None = None,
) -> list[str]:
    """兼容旧名：返回 TikTok user_id 列表（非联盟前台 cid）。"""
    return get_user_ids(usernames, region=region, shop_key=shop_key)


def get_im_links(
    usernames,
    region: str = DEFAULT_REGION,
    shop_key: str | None = None,
) -> list[str]:
    return [
        r["im_link"] if r["ok"] else ""
        for r in resolve_creators(usernames, region=region, shop_key=shop_key)
    ]


# 兼容旧名
resolve_im_links = resolve_creators
