# -*- coding: utf-8 -*-
"""Web 层封装：视频上传模块。"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CONTENT_ROOT = Path(__file__).resolve().parents[2] / "platforms" / "tiktok" / "content"
if str(CONTENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTENT_ROOT))

import oauth as content_oauth  # noqa: E402
import upload_client as content_upload  # noqa: E402
from config import CLIENT_KEY, REDIRECT_URI, save_client_secret  # noqa: E402

UPLOAD_DIR = CONTENT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_DB = Path(__file__).resolve().parents[1] / "data" / "content_oauth.db"


def _token_connection() -> sqlite3.Connection:
    TOKEN_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(TOKEN_DB)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_oauth_sessions (
            session_id TEXT PRIMARY KEY,
            open_id TEXT NOT NULL DEFAULT '',
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            expires_at TEXT,
            token_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def save_session_token(session_id: str, data: dict[str, Any]) -> None:
    if not session_id or not data.get("access_token"):
        raise RuntimeError("TikTok authorization did not return a usable access token")
    now = datetime.now(timezone.utc)
    expires_in = int(data.get("expires_in") or 0)
    expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    with _token_connection() as connection:
        connection.execute(
            """
            INSERT INTO content_oauth_sessions
                (session_id, open_id, access_token, refresh_token, scope,
                 expires_at, token_payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                open_id=excluded.open_id,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                scope=excluded.scope,
                expires_at=excluded.expires_at,
                token_payload=excluded.token_payload,
                updated_at=excluded.updated_at
            """,
            (
                session_id,
                str(data.get("open_id") or ""),
                str(data["access_token"]),
                str(data.get("refresh_token") or ""),
                str(data.get("scope") or ""),
                expires_at.isoformat() if expires_at else None,
                json.dumps(data, ensure_ascii=False),
                now.isoformat(),
                now.isoformat(),
            ),
        )


def exchange_code_for_session(code: str, session_id: str) -> dict[str, Any]:
    data = content_oauth.exchange_code(code, persist=False)
    save_session_token(session_id, data)
    return data


def load_session_token(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _token_connection() as connection:
        row = connection.execute(
            "SELECT * FROM content_oauth_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def session_token_status(session_id: str) -> dict[str, Any]:
    token = load_session_token(session_id)
    if not token:
        return {"authorized": False}
    expires_at = str(token.get("expires_at") or "")
    expired = bool(expires_at and expires_at <= datetime.now(timezone.utc).isoformat())
    return {
        "authorized": not expired,
        "expired": expired,
        "open_id": token.get("open_id", ""),
        "scope": token.get("scope", ""),
    }


def session_access_token(session_id: str) -> str:
    status = session_token_status(session_id)
    token = load_session_token(session_id)
    if token and status.get("expired") and token.get("refresh_token"):
        refreshed = content_oauth.refresh_token(
            str(token["refresh_token"]),
            persist=False,
        )
        save_session_token(session_id, refreshed)
        token = load_session_token(session_id)
        status = session_token_status(session_id)
    if not status.get("authorized") or not token:
        raise RuntimeError("Please connect your TikTok account before publishing")
    return str(token["access_token"])


def disconnect_session(session_id: str) -> None:
    if not session_id:
        return
    with _token_connection() as connection:
        connection.execute(
            "DELETE FROM content_oauth_sessions WHERE session_id = ?",
            (session_id,),
        )

build_authorize_url = content_oauth.build_authorize_url
exchange_code = content_oauth.exchange_code
exchange_callback_url = content_oauth.exchange_callback_url
extract_code_from_query = content_oauth.extract_code_from_query
verify_credentials = content_oauth.verify_credentials
is_content_callback = content_oauth.is_content_callback
token_status = content_oauth.token_status
upload_draft = content_upload.upload_draft
upload_direct = content_upload.upload_direct
fetch_publish_status = content_upload.fetch_publish_status
query_creator_info = content_upload.query_creator_info
