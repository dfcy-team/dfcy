# -*- coding: utf-8 -*-
"""初始化 dingfeng_portal 数据库、权限表与默认管理员。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402

import pymysql  # noqa: E402

from services.settings import (  # noqa: E402
    DB_CHARSET,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)

SQL_FILE = WEB_ROOT / "sql" / "init_auth.sql"

DEFAULT_ROLES = (
    ("admin", "管理员", "系统全部功能"),
    ("operator", "运营", "店铺授权、数据导出、内容上传"),
    ("viewer", "只读", "仅查看，不可操作"),
)

DEFAULT_PERMISSIONS = (
    ("shop.view", "查看店铺", "查看已授权店铺列表"),
    ("shop.authorize", "店铺授权", "发起 TikTok Shop OAuth"),
    ("shop.export", "数据导出", "导出 Excel 报表"),
    ("content.view", "查看内容", "查看 Content Posting 状态"),
    ("content.upload", "内容上传", "上传草稿或直接发布"),
    ("admin.users", "用户管理", "管理账号与权限"),
    ("admin.settings", "系统设置", "修改站点配置"),
)

ROLE_PERMISSIONS = {
    "admin": [p[0] for p in DEFAULT_PERMISSIONS],
    "operator": [
        "shop.view",
        "shop.authorize",
        "shop.export",
        "content.view",
        "content.upload",
    ],
    "viewer": ["shop.view", "content.view"],
}


def _connect(database: str | None = None) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        charset=DB_CHARSET,
        autocommit=True,
    )


def _run_sql_file(conn: pymysql.connections.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


def _seed_roles_permissions(conn: pymysql.connections.Connection) -> None:
    with conn.cursor() as cur:
        for code, name, desc in DEFAULT_ROLES:
            cur.execute(
                "INSERT IGNORE INTO roles (code, name, description) VALUES (%s, %s, %s)",
                (code, name, desc),
            )
        for code, name, desc in DEFAULT_PERMISSIONS:
            cur.execute(
                "INSERT IGNORE INTO permissions (code, name, description) VALUES (%s, %s, %s)",
                (code, name, desc),
            )

        cur.execute("SELECT id, code FROM roles")
        role_map = {row[1]: row[0] for row in cur.fetchall()}
        cur.execute("SELECT id, code FROM permissions")
        perm_map = {row[1]: row[0] for row in cur.fetchall()}

        for role_code, perm_codes in ROLE_PERMISSIONS.items():
            role_id = role_map.get(role_code)
            if not role_id:
                continue
            for perm_code in perm_codes:
                perm_id = perm_map.get(perm_code)
                if perm_id:
                    cur.execute(
                        "INSERT IGNORE INTO role_permissions (role_id, permission_id) VALUES (%s, %s)",
                        (role_id, perm_id),
                    )


EXTRA_USERS = (
    ("yanxinjie", "yanxinjie001", "严新杰", "operator"),
)


def _ensure_user(
    conn: pymysql.connections.Connection,
    *,
    username: str,
    password: str,
    display_name: str,
    role_code: str,
    email: str = "",
) -> None:
    pwd_hash = generate_password_hash(password)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if row:
            user_id = row[0]
            print(f"[skip] 用户已存在: {username}")
        else:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, email, display_name, is_active)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (username, pwd_hash, email or None, display_name),
            )
            user_id = cur.lastrowid
            print(f"[ok] 创建用户: {username}")

        cur.execute("SELECT id FROM roles WHERE code = %s", (role_code,))
        role = cur.fetchone()
        if role:
            cur.execute(
                "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                (user_id, role[0]),
            )


def _seed_extra_users(conn: pymysql.connections.Connection) -> None:
    for username, password, display_name, role_code in EXTRA_USERS:
        _ensure_user(
            conn,
            username=username,
            password=password,
            display_name=display_name,
            role_code=role_code,
        )


def _seed_admin(conn: pymysql.connections.Connection) -> None:
    username = os.environ.get("PORTAL_ADMIN_USER", "admin").strip() or "admin"
    password = os.environ.get("PORTAL_ADMIN_PASSWORD", "dfcyadmin").strip() or "dfcyadmin"
    display_name = os.environ.get("PORTAL_ADMIN_NAME", "系统管理员").strip() or "系统管理员"
    email = os.environ.get("PORTAL_ADMIN_EMAIL", "postmaster@dingfengchuangyu.top").strip()
    pwd_hash = generate_password_hash(password)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if row:
            print(f"[skip] 管理员已存在: {username}")
            user_id = row[0]
        else:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, email, display_name, is_active)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (username, pwd_hash, email, display_name),
            )
            user_id = cur.lastrowid
            print(f"[ok] 创建管理员: {username}")

        cur.execute("SELECT id FROM roles WHERE code = 'admin'")
        admin_role = cur.fetchone()
        if admin_role:
            cur.execute(
                "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                (user_id, admin_role[0]),
            )


def main() -> int:
    if not SQL_FILE.is_file():
        print(f"缺少 SQL 文件: {SQL_FILE}", file=sys.stderr)
        return 1

    print(f"连接 MySQL {DB_HOST}:{DB_PORT} ...")
    conn = _connect()
    try:
        _run_sql_file(conn, SQL_FILE)
        print(f"[ok] 数据库 {DB_NAME} 与表结构已就绪")
    finally:
        conn.close()

    conn = _connect(DB_NAME)
    try:
        _seed_roles_permissions(conn)
        print("[ok] 角色与权限已写入")
        _seed_admin(conn)
        print("[ok] 默认管理员已配置")
        _seed_extra_users(conn)
        print("[ok] 业务账号已配置")
    finally:
        conn.close()

    print("\n初始化完成。后续可在 Navicat 中查看 dingfeng_portal 库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
