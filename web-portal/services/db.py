# -*- coding: utf-8 -*-
"""MySQL 连接（用户权限库，供后续登录模块使用）。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from services.settings import (
    DB_CHARSET,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)


def get_connection(*, dict_cursor: bool = True) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset=DB_CHARSET,
        cursorclass=DictCursor if dict_cursor else pymysql.cursors.Cursor,
        autocommit=False,
    )


@contextmanager
def db_session(*, dict_cursor: bool = True) -> Iterator[pymysql.connections.Connection]:
    conn = get_connection(dict_cursor=dict_cursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_one(sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    with db_session() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return row if isinstance(row, dict) else None


def fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    with db_session() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            return list(rows) if rows else []
