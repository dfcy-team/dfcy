# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import time
from datetime import date, timedelta
from pathlib import Path

from common.excel_names import (
    FINANCE_DIR_KEYS,
    FINANCE_STEM_LEGACY,
    analytics_export_filename,
    finance_export_filename,
    finance_export_filename_legacy,
    zhanfu_day_tag,
)


def analytics_filenames(
    export_tag: str,
    day: str,
    stems: dict[str, str] | None = None,
) -> dict[str, str]:
    api_end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    return {
        kind: analytics_export_filename(export_tag, kind, day, api_end, stems=stems, zhanfu=True)
        for kind in ("product", "sku", "video", "shop")
    }


CACHE_STEMS: dict[str, str] = {
    "product": "product_list",
    "sku": "sku_list",
    "video": "video_detail",
}


def analytics_cache_filename(export_tag: str, kind: str, start: str, api_end: str) -> str:
    """Z 盘 json缓存 文件名（含店名标签，便于同目录多店）。"""
    stem = CACHE_STEMS[kind]
    return f"{export_tag}_{stem}_{start}_{api_end}.json"


def local_cache_filename(kind: str, start: str, api_end: str) -> str:
    """店铺分析.py 写入 logs 的隐藏缓存名。"""
    stem = CACHE_STEMS[kind]
    return f".cache_{stem}_{start}_{api_end}.json"


def order_filename(
    export_tag: str,
    start: str,
    end: str,
    order_stem: str = "订单数据表",
) -> str:
    d0 = start or end
    d1 = end or start
    return f"{export_tag}_{order_stem}_{d0}_{d1}.xlsx"


def finance_json_filename(export_tag: str, start: str, api_end: str) -> str:
    return f"{export_tag}_finance_{start}_{api_end}.json"


def finance_summary_json_filename(export_tag: str, start: str, api_end: str) -> str:
    return f"{export_tag}_finance_summary_{start}_{api_end}.json"


def order_json_filename(export_tag: str, start: str, end: str) -> str:
    d0 = start or end
    d1 = end or start
    return f"{export_tag}_orders_{d0}_{d1}.json"


def order_summary_json_filename(export_tag: str, start: str, end: str) -> str:
    d0 = start or end
    d1 = end or start
    return f"{export_tag}_orders_summary_{d0}_{d1}.json"


def finance_filenames(
    export_tag: str,
    start: str,
    api_end: str,
    stems: dict[str, str] | None = None,
) -> dict[str, str]:
    return {
        kind: finance_export_filename(export_tag, kind, start, api_end, stems=stems)
        for kind in ("statements", "statement_tx", "order_tx", "payments", "withdrawals", "unsettled")
    }


LEGACY_FINANCE_FILENAMES: dict[str, str] = {
    "statements": "statements_{start}_{api_end}.xlsx",
    "statement_tx": "statement_transactions_{start}_{api_end}.xlsx",
    "order_tx": "order_transactions_{start}_{api_end}.xlsx",
    "payments": "payments_{start}_{api_end}.xlsx",
    "withdrawals": "withdrawals_{start}_{api_end}.xlsx",
    "unsettled": "unsettled_{start}_{api_end}.xlsx",
}


def resolve_finance_src(
    src_dir: Path,
    kind: str,
    start: str,
    api_end: str,
    stems: dict[str, str] | None = None,
    *,
    export_tag: str = "",
) -> Path:
    tag = export_tag or "shop"
    names = finance_filenames(tag, start, api_end, stems)
    src = src_dir / names[kind]
    if src.exists():
        return src
    legacy_no_tag = src_dir / finance_export_filename_legacy(kind, start, api_end, stems=stems)
    if legacy_no_tag.exists():
        return legacy_no_tag
    legacy = LEGACY_FINANCE_FILENAMES.get(kind, "").format(start=start, api_end=api_end)
    if legacy:
        alt = src_dir / legacy
        if alt.exists():
            return alt
    merged = {**(stems or {})}
    for old in FINANCE_STEM_LEGACY.get(kind, ()):
        alt_name = f"{tag}_{old}_{start}_{api_end}.xlsx"
        alt = src_dir / alt_name
        if alt.exists():
            return alt
    return src


def copy_file(src: Path, dst: Path, *, skip_existing: bool = False, retries: int = 3) -> bool:
    if not src.exists():
        print(f"  [跳过] 源文件不存在: {src.name}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if skip_existing and dst.exists():
        print(f"  [已有] {dst}")
        return True
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            if src.resolve() == dst.resolve():
                print(f"  [已在Z盘] {dst.name}")
                return True
            shutil.copy2(src, dst)
            print(f"  [导入] {src.name} -> {dst.parent.name}\\{dst.name}")
            return True
        except PermissionError as exc:
            last_err = exc
            if attempt + 1 < retries:
                time.sleep(1.5)
                continue
            print(f"  [失败] 文件被占用（请关闭 Excel/资源管理器预览）: {dst.name}")
            return False
        except OSError as exc:
            last_err = exc
            break
    if last_err:
        print(f"  [失败] 复制 {src.name}: {last_err}")
    return False


def import_analytics_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    api_end: str,
    data_types: set[str],
    import_dirs: dict[str, Path],
    copy_api_copy: bool,
    skip_existing: bool,
    filename_stems: dict[str, str] | None = None,
) -> list[str]:
    day = zhanfu_day_tag(start, api_end)
    src_dir = logs_dir / shop_key
    names = analytics_filenames(export_tag, day, filename_stems)
    copied: list[str] = []

    mapping = {
        "product": [("产品目录", False), ("产品_API目录", True)],
        "sku": [("SKU目录", False), ("SKU_API目录", True)],
        "video": [("视频目录", False), ("视频_API目录", True)],
        "shop": [("店铺数据目录", False)],
    }

    for kind, targets in mapping.items():
        if kind not in data_types:
            continue
        src = src_dir / names[kind]
        for dir_key, is_api in targets:
            if is_api and not copy_api_copy:
                continue
            dst = import_dirs[dir_key] / names[kind]
            if copy_file(src, dst, skip_existing=skip_existing):
                copied.append(str(dst))

    return copied


def import_analytics_cache_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    api_end: str,
    data_types: set[str],
    import_dirs: dict[str, Path],
    skip_existing: bool,
) -> list[str]:
    """将 logs/.cache_*.json 复制到 Z 盘 json缓存 分类目录。"""
    src_dir = logs_dir / shop_key
    dir_map = {
        "product": "产品_JSON目录",
        "sku": "SKU_JSON目录",
        "video": "视频_JSON目录",
    }
    copied: list[str] = []
    for kind, dir_key in dir_map.items():
        if kind not in data_types:
            continue
        src = src_dir / local_cache_filename(kind, start, api_end)
        dst = import_dirs[dir_key] / analytics_cache_filename(export_tag, kind, start, api_end)
        if copy_file(src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
    return copied


def import_finance_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    api_end: str,
    data_types: set[str],
    import_dirs: dict[str, Path],
    skip_existing: bool,
    filename_stems: dict[str, str] | None = None,
) -> list[str]:
    from common.shop_registry import load_filename_stems

    src_dir = logs_dir / shop_key
    tag = export_tag or shop_key
    stems = filename_stems or load_filename_stems()
    dir_map = dict(FINANCE_DIR_KEYS)
    copied: list[str] = []
    for kind, dir_key in dir_map.items():
        if kind not in data_types:
            continue
        dst_name = finance_export_filename(tag, kind, start, api_end, stems=stems)
        src = resolve_finance_src(src_dir, kind, start, api_end, stems, export_tag=tag)
        dst = import_dirs[dir_key] / dst_name
        if copy_file(src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
    return copied


def import_finance_json_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    api_end: str,
    import_dirs: dict[str, Path],
    skip_existing: bool,
) -> list[str]:
    """财务完整 JSON / 摘要 JSON → Z:\\...\\店铺分析API接口\\json缓存\\店铺财务"""
    json_dir = import_dirs.get("财务_JSON目录") or import_dirs.get("流水_JSON目录")
    if not json_dir:
        return []
    src_dir = logs_dir / shop_key
    copied: list[str] = []
    full_candidates = sorted(
        src_dir.glob("finance_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for src in full_candidates:
        if src.name == "finance_last_summary.json":
            continue
        dst = json_dir / finance_json_filename(export_tag, start, api_end)
        if copy_file(src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
        break
    summary_src = src_dir / "finance_last_summary.json"
    if summary_src.exists():
        dst = json_dir / finance_summary_json_filename(export_tag, start, api_end)
        if copy_file(summary_src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
    return copied


def import_order_json_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    end: str,
    import_dirs: dict[str, Path],
    skip_existing: bool,
) -> list[str]:
    """订单 JSON → Z:\\...\\店铺分析API接口\\json缓存\\订单数据表"""
    json_dir = import_dirs.get("订单_JSON目录")
    if not json_dir:
        return []
    src_dir = logs_dir / shop_key
    copied: list[str] = []
    full_candidates = sorted(
        src_dir.glob("orders_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for src in full_candidates:
        if src.name == "orders_last_summary.json":
            continue
        dst = json_dir / order_json_filename(export_tag, start, end)
        if copy_file(src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
        break
    summary_src = src_dir / "orders_last_summary.json"
    if summary_src.exists():
        dst = json_dir / order_summary_json_filename(export_tag, start, end)
        if copy_file(summary_src, dst, skip_existing=skip_existing):
            copied.append(str(dst))
    return copied


def import_order_files(
    *,
    shop_key: str,
    export_tag: str,
    logs_dir: Path,
    start: str,
    end: str,
    import_dirs: dict[str, Path],
    skip_existing: bool,
    order_stem: str = "订单数据表",
) -> list[str]:
    src_dir = logs_dir / shop_key
    name = order_filename(export_tag, start, end, order_stem)
    src = src_dir / name
    dst = import_dirs["订单目录"] / name
    copied: list[str] = []
    if copy_file(src, dst, skip_existing=skip_existing):
        copied.append(str(dst))
    return copied
