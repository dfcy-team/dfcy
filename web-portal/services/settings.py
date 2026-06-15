# -*- coding: utf-8 -*-
"""Web 站点配置（读取 web-portal/local.env）。"""
from __future__ import annotations

import os
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ROOT = WEB_ROOT.parent


def resolve_project_root() -> Path:
    """ERP 根目录：含 platforms/tiktok/shop 或 legacy 正式环境。"""
    root = DESKTOP_ROOT
    if (root / "platforms" / "tiktok" / "shop").is_dir():
        return root.resolve()
    nested = root / "TikTok_API"
    if (nested / "platforms" / "tiktok" / "shop").is_dir():
        return nested.resolve()
    if (nested / "正式环境").is_dir():
        return nested.resolve()
    if (root / "正式环境").is_dir():
        return root.resolve()
    return root.resolve()


PROJECT_ROOT = resolve_project_root()
TIKTOK_DIR = PROJECT_ROOT / "platforms" / "tiktok"
HUB_DIR = TIKTOK_DIR / "shop"
APP_ENV = HUB_DIR / "app.env"
SHOPS_JSON = HUB_DIR / "shops.json"
MASTER_CONFIG = PROJECT_ROOT / "config" / "导入总配置.ini"

ANALYTICS_SCRIPT = TIKTOK_DIR / "analytics" / "店铺分析.py"
FINANCE_SCRIPT = TIKTOK_DIR / "finance" / "流水分析.py"
ORDER_SCRIPT = TIKTOK_DIR / "orders" / "订单查询.py"
ANALYTICS_LOGS = TIKTOK_DIR / "analytics" / "logs"
ORDER_LOGS = TIKTOK_DIR / "orders"
CONTENT_DIR = TIKTOK_DIR / "content"

JOBS_DIR = WEB_ROOT / "data" / "jobs"
EXPORT_CACHE = WEB_ROOT / "data" / "exports"

LOCAL_ENV = WEB_ROOT / "local.env"


def load_local_env() -> None:
    if not LOCAL_ENV.is_file():
        return
    for raw in LOCAL_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_local_env()

HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
PORT = int(os.environ.get("LISTEN_PORT", "80"))
SITE_DOMAIN = os.environ.get("SITE_DOMAIN", "dingfengchuangyu.com").strip() or "dingfengchuangyu.com"
SITE_BRAND = os.environ.get("SITE_BRAND", "鼎峰 TikTok Shop 数据平台").strip()
COMPANY_NAME = os.environ.get("COMPANY_NAME", "厦门市鼎峰创域科技有限公司").strip()
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "postmaster@dingfengchuangyu.top").strip()
CONTACT_ADDRESS = os.environ.get(
    "CONTACT_ADDRESS",
    "福建省福州市厦门市厦门火炬高新区软件园三期溪西山尾路3号1901-4",
).strip()
PRODUCTION_SITE = os.environ.get("PRODUCTION_SITE", "dingfengchuangyu.top").strip() or "dingfengchuangyu.top"
CALLBACK_PATH = os.environ.get("CALLBACK_PATH", "/callback").rstrip() or "/callback"
INFO_PATH = os.environ.get("INFO_PATH", "/ruike").rstrip() or "/ruike"
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-local-env")

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1").strip() or "127.0.0.1"
DB_PORT = int(os.environ.get("DB_PORT", "3360"))
DB_USER = os.environ.get("DB_USER", "dingfeng").strip() or "dingfeng"
DB_PASSWORD = os.environ.get("DB_PASSWORD", "").strip()
DB_NAME = os.environ.get("DB_NAME", "dingfeng_portal").strip() or "dingfeng_portal"
DB_CHARSET = os.environ.get("DB_CHARSET", "utf8mb4").strip() or "utf8mb4"


def public_site_base(domain: str | None = None, port: int | None = None) -> str:
    """对外网站根 URL（浏览用，默认 SITE_DOMAIN/.com）。"""
    dom = (domain or SITE_DOMAIN).strip()
    p = PORT if port is None else int(port)
    if dom in ("127.0.0.1", "localhost"):
        return f"http://{dom}:{p}"
    scheme = "https" if os.environ.get("TTS_REDIRECT_URL", "").startswith("https") else "http"
    return f"{scheme}://{dom}"


def _production_public_base() -> str:
    if PRODUCTION_SITE.startswith("http"):
        return PRODUCTION_SITE.rstrip("/")
    scheme = "https" if os.environ.get("TTS_REDIRECT_URL", "").startswith("https") else "http"
    return f"{scheme}://{PRODUCTION_SITE}"


PRODUCTION_PUBLIC_BASE = _production_public_base()
PRODUCTION_CALLBACK_URL = os.environ.get(
    "PRODUCTION_CALLBACK_URL",
    f"{PRODUCTION_PUBLIC_BASE}{CALLBACK_PATH}",
).strip()
PRODUCTION_AUTHORIZE_PAGE = f"{PRODUCTION_PUBLIC_BASE}/authorize"
IS_LOCAL_DEV = SITE_DOMAIN in ("127.0.0.1", "localhost") or PORT not in (80, 443)
SITE_PUBLIC_BASE = public_site_base()

SERVICE_ID = os.environ.get("TTS_SERVICE_ID", "7641963005262366481").strip()
APP_KEY = os.environ.get("TTS_APP_KEY", "").strip()
APP_SECRET = os.environ.get("TTS_APP_SECRET", "").strip()
REDIRECT_URL = os.environ.get(
    "TTS_REDIRECT_URL",
    f"http://{SITE_DOMAIN}{CALLBACK_PATH if CALLBACK_PATH.startswith('/') else '/' + CALLBACK_PATH}",
).strip()

AUTH_BASE = os.environ.get("TIKTOK_AUTH_BASE", "https://auth.tiktok-shops.com").rstrip("/")
AUTHORIZE_URL = (
    os.environ.get("TIKTOK_AUTHORIZE_URL", "").strip()
    or f"https://services.tiktokshop.com/open/authorize?service_id={SERVICE_ID}"
)

AUTO_EXCHANGE_TOKEN = os.environ.get("TIKTOK_AUTO_EXCHANGE", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def sync_credentials_from_app_env() -> None:
    """若 local.env 未填密钥，则从 TikTok_API app.env 读取。"""
    global APP_KEY, APP_SECRET, SERVICE_ID, REDIRECT_URL
    if not APP_ENV.is_file():
        return
    vals: dict[str, str] = {}
    for raw in APP_ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        vals[k.strip()] = v.strip()
    if not APP_KEY:
        APP_KEY = vals.get("TTS_APP_KEY", "")
        os.environ.setdefault("TTS_APP_KEY", APP_KEY)
    if not APP_SECRET:
        APP_SECRET = vals.get("TTS_APP_SECRET", "")
        os.environ.setdefault("TTS_APP_SECRET", APP_SECRET)
    if SERVICE_ID == "7641963005262366481" and vals.get("TTS_SERVICE_ID"):
        SERVICE_ID = vals["TTS_SERVICE_ID"]
    if REDIRECT_URL.endswith("/callback") and vals.get("TTS_REDIRECT_URL"):
        REDIRECT_URL = vals["TTS_REDIRECT_URL"]


sync_credentials_from_app_env()

if not os.environ.get("TIKTOK_AUTHORIZE_URL", "").strip():
    AUTHORIZE_URL = f"https://services.tiktokshop.com/open/authorize?service_id={SERVICE_ID}"

for p in (JOBS_DIR, EXPORT_CACHE, WEB_ROOT / "data"):
    p.mkdir(parents=True, exist_ok=True)
