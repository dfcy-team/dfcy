# -*- coding: utf-8 -*-
"""网站登录与会话。"""
from __future__ import annotations

from datetime import datetime
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

from services.db import db_session, fetch_one

SESSION_USER_ID = "user_id"
SESSION_USERNAME = "username"
SESSION_DISPLAY_NAME = "display_name"

PUBLIC_ENDPOINTS = frozenset(
    {
        "index",
        "about",
        "contact",
        "terms",
        "privacy",
        "login_page",
        "logout",
        "callback",
        "content_callback",
        "authorize_page",
        "tiktok_site_verification_new",
        "tiktok_service_verification",
        "tiktok_terms_verification",
        "tiktok_privacy_verification",
        "tiktok_content_verification",
        "tiktok_site_verification_jyha",
        "favicon",
        "static",
    }
)


def get_current_user() -> dict[str, Any] | None:
    user_id = session.get(SESSION_USER_ID)
    if not user_id:
        return None
    return {
        "id": user_id,
        "username": session.get(SESSION_USERNAME, ""),
        "display_name": session.get(SESSION_DISPLAY_NAME) or session.get(SESSION_USERNAME, ""),
    }


def login_user(user: dict[str, Any]) -> None:
    session.permanent = True
    session[SESSION_USER_ID] = user["id"]
    session[SESSION_USERNAME] = user["username"]
    session[SESSION_DISPLAY_NAME] = user.get("display_name") or user["username"]


def logout_user() -> None:
    session.clear()


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "")


def _write_login_log(
    *,
    user_id: int | None,
    username: str,
    success: bool,
    message: str = "",
) -> None:
    try:
        with db_session() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO login_logs (user_id, username, ip_address, user_agent, success, message)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        username,
                        _client_ip()[:45],
                        (request.headers.get("User-Agent") or "")[:512],
                        1 if success else 0,
                        message[:255],
                    ),
                )
    except Exception:
        pass


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    name = (username or "").strip()
    if not name or not password:
        _write_login_log(user_id=None, username=name or "?", success=False, message="缺少用户名或密码")
        return None

    user = fetch_one(
        """
        SELECT id, username, password_hash, display_name, is_active
        FROM users
        WHERE username = %s
        LIMIT 1
        """,
        (name,),
    )
    if not user or not user.get("is_active"):
        _write_login_log(user_id=None, username=name, success=False, message="用户不存在或已禁用")
        return None
    if not check_password_hash(user["password_hash"], password):
        _write_login_log(user_id=user["id"], username=name, success=False, message="密码错误")
        return None

    try:
        with db_session() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET last_login_at = %s WHERE id = %s",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
                )
    except Exception:
        pass

    _write_login_log(user_id=user["id"], username=name, success=True, message="登录成功")
    return user


def safe_next_url(raw: str | None) -> str:
    target = (raw or "").strip()
    if not target:
        return url_for("index")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return url_for("index")
    if not target.startswith("/"):
        return url_for("index")
    return target


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if get_current_user():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "请先登录"}), 401
        return redirect(url_for("login_page", next=request.full_path.rstrip("?")))

    return wrapped


def _is_public_path(path: str) -> bool:
    p = (path or "").rstrip("/") or "/"
    if p in ("/callback", "/content/callback"):
        return True
    if p.endswith(".txt") and "tiktok" in p.rsplit("/", 1)[-1]:
        return True
    return False


def check_request_auth() -> Any | None:
    if _is_public_path(request.path):
        return None
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC_ENDPOINTS:
        return None
    if get_current_user():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "请先登录"}), 401
    return redirect(url_for("login_page", next=request.path))
