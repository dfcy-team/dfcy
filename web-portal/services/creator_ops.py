# -*- coding: utf-8 -*-
"""BD creator outreach workspace backed by Feishu and video reporting data."""
from __future__ import annotations

import configparser
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pymysql
import requests
from flask import Blueprint, jsonify, render_template, request
from pymysql.cursors import DictCursor


WEB_ROOT = Path(__file__).resolve().parents[1]
STATE_DB = WEB_ROOT / "data" / "creator_ops.db"
DAILY_ROOT = Path.home() / "Desktop" / "每日数据导入数据库"
FEISHU_CONFIG = DAILY_ROOT / "配置.ini"
DATABASE_CONFIG = DAILY_ROOT / "db.ini"

FEISHU_BASE = "https://open.feishu.cn/open-apis"
FEISHU_APP_TOKEN = "USftbsnwbaNwV7sP9UUctwzBnrb"
TASK_TABLE_ID = "tblw5dYiCB3q5Xdy"
TASK_VIEW_ID = "vewDAlV5BA"
SAMPLE_TABLE_ID = "tblRe8gcDq5ebj2c"
SAMPLE_VIEW_ID = "vewI1stNKF"

bp = Blueprint("creator_ops", __name__)
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    with _cache_lock:
        value = _cache.get(key)
        if value and value[0] > time.time():
            return value[1]
    return None


def _cache_set(key: str, value: Any, seconds: int = 300) -> Any:
    with _cache_lock:
        _cache[key] = (time.time() + seconds, value)
    return value


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    parser.read(path, encoding="utf-8")
    return parser


def _feishu_token() -> str:
    cached = _cache_get("feishu_token")
    if cached:
        return str(cached)
    parser = _read_config(FEISHU_CONFIG)
    response = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={
            "app_id": parser.get("飞书", "应用ID"),
            "app_secret": parser.get("飞书", "应用密钥"),
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") not in (0, None):
        raise RuntimeError(payload.get("msg") or "飞书鉴权失败")
    return _cache_set("feishu_token", payload["tenant_access_token"], 6000)


def _feishu_records(table_id: str, view_id: str, *, cache_key: str) -> list[dict[str, Any]]:
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    headers = {"Authorization": f"Bearer {_feishu_token()}"}
    url = f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records"
    records: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"view_id": view_id, "page_size": 500}
        if page_token:
            params["page_token"] = page_token
        payload = _feishu_request("GET", url, headers=headers, params=params)
        if payload.get("code") not in (0, None):
            raise RuntimeError(payload.get("msg") or "飞书读取失败")
        data = payload.get("data") or {}
        records.extend(data.get("items") or [])
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return _cache_set(cache_key, records, 300)


def _feishu_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.request(method, url, timeout=45, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, None):
                raise RuntimeError(payload.get("msg") or "飞书请求失败")
            return payload
        except (requests.RequestException, RuntimeError, ValueError) as error:
            last_error = error
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"飞书请求失败: {last_error}")


def _feishu_record_page(
    table_id: str,
    view_id: str,
    *,
    page_token: str = "",
    page_size: int = 50,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {_feishu_token()}"}
    url = f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records/search"
    params: dict[str, Any] = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    payload = _feishu_request(
        "POST",
        url,
        headers=headers,
        params=params,
        json={"view_id": view_id, "sort": [{"field_name": "建联时间", "desc": True}]},
    )
    data = payload.get("data") or {}
    return {
        "items": list(data.get("items") or []),
        "total": _int(data.get("total")),
        "next_page_token": str(data.get("page_token") or ""),
        "has_more": bool(data.get("has_more")),
    }


def _task_samples(task_id: str) -> list[dict[str, Any]]:
    cache_key = f"task_samples:{task_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    url = f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{SAMPLE_TABLE_ID}/records/search"
    headers = {"Authorization": f"Bearer {_feishu_token()}"}
    body: dict[str, Any] = {
        "view_id": SAMPLE_VIEW_ID,
        "page_size": 500,
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "任务ID", "operator": "is", "value": [task_id]}],
        },
    }
    rows: list[dict[str, Any]] = []
    page_token = ""
    while True:
        if page_token:
            body["page_token"] = page_token
        payload = _feishu_request("POST", url, headers=headers, json=body)
        data = payload.get("data") or {}
        rows.extend(data.get("items") or [])
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    samples = [_normalize_sample(item) for item in rows]
    samples.sort(key=lambda item: (item.get("date") or "", item["id"]), reverse=True)
    return _cache_set(cache_key, samples, 300)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return ""
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    return str(value).strip()


def _person(value: Any) -> tuple[str, str]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("name") or ""), str(value[0].get("avatar_url") or "")
    return _text(value), ""


def _date_text(value: Any) -> str:
    if not value:
        return ""
    try:
        timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return _text(value)


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalize_task(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    owner, avatar = _person(fields.get("负责人"))
    product = _text(fields.get("建联商品"))
    return {
        "id": _text(fields.get("任务ID")) or str(record.get("record_id") or ""),
        "record_id": str(record.get("record_id") or ""),
        "name": _text(fields.get("任务名称")) or "未命名任务",
        "shop": _text(fields.get("建联店铺")),
        "product_id": product,
        "sku_prefix": _text(fields.get("SKU前缀")),
        "priority": _text(fields.get("建联优先级")) or "T2",
        "status": _text(fields.get("任务状态")) or "进行中",
        "target_count": _int(fields.get("建联数量")),
        "linked_count": _int(fields.get("已建联数量")),
        "owner": owner or "BD",
        "owner_avatar": avatar,
        "start_date": _date_text(fields.get("开始时间")),
        "dispatch_date": _date_text(fields.get("下发时间")),
        "feedback": _text(fields.get("任务处理反馈")),
        "source": "飞书",
    }


def _normalize_sample(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    owner, _avatar = _person(fields.get("送样人"))
    recovered = _int(fields.get("送样回收视频"))
    breakout = _text(fields.get("出道视频"))
    ordered = _text(fields.get("出单视频"))
    order_no = _text(fields.get("样品订单"))
    status = "已发布" if recovered or breakout or ordered else ("已发货" if order_no else "待发样")
    return {
        "id": _text(fields.get("建联编号")) or str(record.get("record_id") or ""),
        "record_id": str(record.get("record_id") or ""),
        "task_id": _text(fields.get("任务ID")),
        "date": _date_text(fields.get("建联时间")),
        "product": _text(fields.get("建联产品")),
        "product_id": _text(fields.get("商品ID转文本")) or _text(fields.get("商品ID")),
        "handle": _text(fields.get("用户名称")),
        "creator_id": _text(fields.get("达人ID")),
        "shop": _text(fields.get("店铺")),
        "country": _text(fields.get("国家")),
        "owner": owner or "BD",
        "order_no": order_no,
        "sku": _text(fields.get("具体sku")) or _text(fields.get("单件SKU")),
        "cost": _float(fields.get("总成本")),
        "recovered_videos": recovered,
        "status": status,
        "note": _text(fields.get("备注")),
        "source": "飞书",
    }


def _init_state_db() -> None:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(STATE_DB)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ops_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                shop TEXT NOT NULL,
                product_id TEXT,
                sku_prefix TEXT,
                priority TEXT NOT NULL DEFAULT 'T2',
                target_count INTEGER NOT NULL DEFAULT 0,
                owner TEXT NOT NULL DEFAULT 'BD',
                status TEXT NOT NULL DEFAULT '进行中',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ops_creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                shop TEXT NOT NULL,
                handle TEXT NOT NULL,
                normalized_handle TEXT NOT NULL,
                creator_id TEXT,
                outreach_result TEXT NOT NULL DEFAULT 'pending',
                sample_status TEXT NOT NULL DEFAULT 'none',
                sample_order TEXT,
                sku TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, normalized_handle)
            );
            """
        )
        connection.commit()


def _state_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    _init_state_db()
    with closing(sqlite3.connect(STATE_DB)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _all_tasks() -> list[dict[str, Any]]:
    feishu = [_normalize_task(item) for item in _feishu_records(TASK_TABLE_ID, TASK_VIEW_ID, cache_key="tasks")]
    local = _state_rows("SELECT * FROM ops_tasks ORDER BY created_at DESC")
    for task in local:
        task.update(
            {
                "record_id": "",
                "linked_count": len(
                    _state_rows(
                        "SELECT id FROM ops_creators WHERE task_id = ? AND outreach_result = 'success'",
                        (task["id"],),
                    )
                ),
                "owner_avatar": "",
                "start_date": task["created_at"][:10],
                "dispatch_date": task["created_at"][:10],
                "feedback": "",
                "source": "网站",
            }
        )
    tasks = local + feishu
    tasks.sort(key=lambda item: (item.get("dispatch_date") or item.get("start_date") or "", item["id"]), reverse=True)
    return tasks


def _all_samples() -> list[dict[str, Any]]:
    rows = _feishu_records(SAMPLE_TABLE_ID, SAMPLE_VIEW_ID, cache_key="samples")
    samples = [_normalize_sample(item) for item in rows]
    samples.sort(key=lambda item: (item.get("date") or "", item["id"]), reverse=True)
    return samples


def _sample_total() -> int:
    cached = _cache_get("sample_total")
    if cached is not None:
        return _int(cached)
    result = _feishu_record_page(SAMPLE_TABLE_ID, SAMPLE_VIEW_ID, page_size=1)
    return _cache_set("sample_total", result["total"], 300)


def _database_connection() -> pymysql.connections.Connection:
    parser = _read_config(DATABASE_CONFIG)
    section = "数据库"
    return pymysql.connect(
        host=parser.get(section, "host"),
        port=parser.getint(section, "port"),
        user=parser.get(section, "user"),
        password=parser.get(section, "password"),
        database=parser.get(section, "database"),
        charset=parser.get(section, "charset", fallback="utf8mb4"),
        cursorclass=DictCursor,
        connect_timeout=5,
        read_timeout=45,
        autocommit=True,
    )


def _latest_video_date() -> str:
    cached = _cache_get("latest_video_date")
    if cached:
        return str(cached)
    with _database_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT data_time FROM video_performance_report ORDER BY data_time DESC LIMIT 1")
        row = cursor.fetchone() or {}
    return _cache_set("latest_video_date", str(row.get("data_time") or ""), 300)


def _video_results(handle: str, shop: str) -> dict[str, Any]:
    handle = handle.strip().lstrip("@")
    shop = shop.strip().upper()
    if not handle or not shop:
        return {"summary": {}, "videos": [], "latest_date": _latest_video_date()}
    latest = _latest_video_date()
    start = (date.fromisoformat(latest) - timedelta(days=29)).isoformat()
    sql = """
        SELECT video_id,
               MAX(NULLIF(video_title, '0')) AS video_title,
               MAX(NULLIF(product_info, '0')) AS product_info,
               MAX(publish_time) AS publish_time,
               SUM(COALESCE(vv, 0)) AS vv,
               SUM(COALESCE(orders, 0)) AS orders,
               SUM(COALESCE(items_sold, 0)) AS items_sold,
               SUM(COALESCE(gmv_video, 0)) AS gmv
        FROM video_performance_report FORCE INDEX (idx_shop_date)
        WHERE shop_abbr = %s
          AND data_time BETWEEN %s AND %s
          AND video_type IN ('creator', '达人')
          AND creator_name = %s
          AND video_id NOT IN ('0', '__ZERO_VIDEO__')
        GROUP BY video_id
        ORDER BY MAX(publish_time) DESC, SUM(COALESCE(gmv_video, 0)) DESC
        LIMIT 50
    """
    with _database_connection() as connection, connection.cursor() as cursor:
        cursor.execute(sql, (shop, start, latest, handle))
        rows = list(cursor.fetchall() or [])
    videos = []
    for row in rows:
        videos.append(
            {
                "video_id": str(row.get("video_id") or ""),
                "title": str(row.get("video_title") or "未填写标题"),
                "product": str(row.get("product_info") or ""),
                "publish_time": str(row.get("publish_time") or ""),
                "vv": _int(row.get("vv")),
                "orders": _int(row.get("orders")),
                "items_sold": _int(row.get("items_sold")),
                "gmv": _float(row.get("gmv")),
            }
        )
    summary = {
        "videos": len(videos),
        "vv": sum(item["vv"] for item in videos),
        "orders": sum(item["orders"] for item in videos),
        "items_sold": sum(item["items_sold"] for item in videos),
        "gmv": round(sum(item["gmv"] for item in videos), 2),
    }
    return {"summary": summary, "videos": videos, "latest_date": latest, "start_date": start}


def _json_error(error: Exception, status: int = 500):
    return jsonify({"ok": False, "error": str(error)}), status


@bp.get("/creator-ops")
def page():
    return render_template("creator_ops.html")


@bp.get("/api/creator-ops/bootstrap")
def bootstrap():
    try:
        tasks = _all_tasks()
        local_creators = _state_rows("SELECT * FROM ops_creators ORDER BY updated_at DESC")
        active = [task for task in tasks if task.get("status") not in ("已完成", "已关闭", "已取消")]
        linked = sum(_int(task.get("linked_count")) for task in tasks)
        return jsonify(
            {
                "ok": True,
                "tasks": tasks,
                "creators": local_creators,
                "stats": {
                    "tasks": len(tasks),
                    "active_tasks": len(active),
                    "linked": linked,
                    "samples": _sample_total(),
                    "published": sum(1 for item in local_creators if item.get("sample_status") == "published"),
                },
                "latest_video_date": _latest_video_date(),
                "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )
    except Exception as error:
        return _json_error(error)


@bp.get("/api/creator-ops/samples")
def samples():
    try:
        page_number = max(_int(request.args.get("page")), 1)
        page_size = min(max(_int(request.args.get("page_size")), 20), 200)
        query = (request.args.get("q") or "").strip().lower()
        shop = (request.args.get("shop") or "").strip().upper()
        status = (request.args.get("status") or "").strip()
        page_token = (request.args.get("page_token") or "").strip()
        if not query and not shop and not status:
            result = _feishu_record_page(
                SAMPLE_TABLE_ID,
                SAMPLE_VIEW_ID,
                page_token=page_token,
                page_size=page_size,
            )
            return jsonify(
                {
                    "ok": True,
                    "items": [_normalize_sample(item) for item in result["items"]],
                    "total": result["total"],
                    "page": page_number,
                    "page_size": page_size,
                    "next_page_token": result["next_page_token"],
                    "has_more": result["has_more"],
                }
            )
        rows = _all_samples()
        if query:
            rows = [row for row in rows if query in " ".join(str(value).lower() for value in row.values())]
        if shop:
            rows = [row for row in rows if row.get("shop") == shop]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        start = (page_number - 1) * page_size
        return jsonify(
            {
                "ok": True,
                "items": rows[start : start + page_size],
                "total": len(rows),
                "page": page_number,
                "page_size": page_size,
                "next_page_token": "",
                "has_more": start + page_size < len(rows),
            }
        )
    except Exception as error:
        return _json_error(error)


@bp.get("/api/creator-ops/tasks/<task_id>")
def task_detail(task_id: str):
    try:
        task = next((item for item in _all_tasks() if item["id"] == task_id), None)
        if not task:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        local = _state_rows("SELECT * FROM ops_creators WHERE task_id = ? ORDER BY updated_at DESC", (task_id,))
        feishu = _task_samples(task_id)
        return jsonify({"ok": True, "task": task, "creators": local, "samples": feishu})
    except Exception as error:
        return _json_error(error)


@bp.post("/api/creator-ops/tasks")
def create_task():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    shop = str(payload.get("shop") or "").strip().upper()
    if not name or not shop:
        return jsonify({"ok": False, "error": "任务名称和店铺不能为空"}), 400
    _init_state_db()
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    task_id = f"WEB{datetime.now().strftime('%y%m%d%H%M%S')}"
    with closing(sqlite3.connect(STATE_DB)) as connection:
        connection.execute(
            """
            INSERT INTO ops_tasks
                (id, name, shop, product_id, sku_prefix, priority, target_count, owner, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'BD', '进行中', ?)
            """,
            (
                task_id,
                name,
                shop,
                str(payload.get("product_id") or "").strip(),
                str(payload.get("sku_prefix") or "").strip(),
                str(payload.get("priority") or "T2").strip(),
                _int(payload.get("target_count")),
                now,
            ),
        )
        connection.commit()
    return jsonify({"ok": True, "task_id": task_id})


@bp.post("/api/creator-ops/tasks/<task_id>/creators")
def add_creator(task_id: str):
    payload = request.get_json(silent=True) or {}
    handle = str(payload.get("handle") or "").strip().lstrip("@")
    task = next((item for item in _all_tasks() if item["id"] == task_id), None)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if not handle:
        return jsonify({"ok": False, "error": "达人账号不能为空"}), 400
    _init_state_db()
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    try:
        with closing(sqlite3.connect(STATE_DB)) as connection:
            connection.execute(
                """
                INSERT INTO ops_creators
                    (task_id, task_name, shop, handle, normalized_handle, creator_id,
                     outreach_result, sample_status, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'none', ?, ?, ?)
                """,
                (
                    task_id,
                    task["name"],
                    task["shop"],
                    handle,
                    handle.casefold(),
                    str(payload.get("creator_id") or "").strip(),
                    str(payload.get("outreach_result") or "pending"),
                    str(payload.get("note") or "").strip(),
                    now,
                    now,
                ),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "该任务中已存在这个达人"}), 409
    return jsonify({"ok": True})


@bp.patch("/api/creator-ops/creators/<int:creator_id>")
def update_creator(creator_id: int):
    payload = request.get_json(silent=True) or {}
    allowed_results = {"pending", "success", "rejected", "no_response", "blocked"}
    allowed_stages = {"none", "pending_sample", "shipped", "signed", "creating", "published"}
    updates: list[str] = []
    values: list[Any] = []
    result = str(payload.get("outreach_result") or "")
    stage = str(payload.get("sample_status") or "")
    if result:
        if result not in allowed_results:
            return jsonify({"ok": False, "error": "无效的建联结果"}), 400
        updates.append("outreach_result = ?")
        values.append(result)
    if stage:
        if stage not in allowed_stages:
            return jsonify({"ok": False, "error": "无效的履约状态"}), 400
        updates.append("sample_status = ?")
        values.append(stage)
    for field in ("sample_order", "sku", "note"):
        if field in payload:
            updates.append(f"{field} = ?")
            values.append(str(payload.get(field) or "").strip())
    if not updates:
        return jsonify({"ok": False, "error": "没有可更新的字段"}), 400
    updates.append("updated_at = ?")
    values.append(datetime.now().replace(microsecond=0).isoformat(sep=" "))
    values.append(creator_id)
    _init_state_db()
    with closing(sqlite3.connect(STATE_DB)) as connection:
        cursor = connection.execute(f"UPDATE ops_creators SET {', '.join(updates)} WHERE id = ?", values)
        if not cursor.rowcount:
            return jsonify({"ok": False, "error": "达人记录不存在"}), 404
        connection.commit()
    return jsonify({"ok": True})


@bp.get("/api/creator-ops/videos")
def videos():
    try:
        handle = str(request.args.get("handle") or "")
        shop = str(request.args.get("shop") or "")
        return jsonify({"ok": True, **_video_results(handle, shop)})
    except Exception as error:
        return _json_error(error)
