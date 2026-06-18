# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from services.settings import AFFILIATE_LOGS, ANALYTICS_LOGS, DESKTOP_ROOT, EXPORT_DOWNLOAD_ROOT, FINANCE_LOGS, ORDER_LOGS, PROJECT_ROOT


def _safe_roots() -> list[Path]:
    roots = [
        EXPORT_DOWNLOAD_ROOT,
        ANALYTICS_LOGS,
        FINANCE_LOGS,
        ORDER_LOGS,
        AFFILIATE_LOGS,
        DESKTOP_ROOT,
        PROJECT_ROOT / "platforms" / "tiktok",
    ]
    api = DESKTOP_ROOT / "店铺分析API接口"
    if api.exists():
        roots.append(api)
    return [r.resolve() for r in roots if r.exists()]


def is_allowed_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _safe_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def list_excel_files(shop_key: str = "", limit: int = 80) -> list[dict]:
    roots = _safe_roots()
    items: list[dict] = []
    patterns = ["*.xlsx"]
    for root in roots:
        if shop_key:
            candidates = [root / shop_key]
            if (root / "店铺分析API接口").exists():
                candidates.append(root / "店铺分析API接口")
            glob_roots = [p for p in candidates if p.exists()]
            if not glob_roots:
                glob_roots = [root]
        else:
            glob_roots = [root]
        for gr in glob_roots:
            for pat in patterns:
                for f in gr.rglob(pat):
                    if not f.is_file():
                        continue
                    if shop_key and shop_key.upper() not in f.name.upper() and shop_key.upper() not in str(
                        f.parent
                    ).upper():
                        continue
                    try:
                        stat = f.stat()
                    except OSError:
                        continue
                    items.append(
                        {
                            "name": f.name,
                            "path": str(f.resolve()),
                            "size": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                            "folder": str(f.parent),
                        }
                    )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        if it["path"] in seen:
            continue
        seen.add(it["path"])
        out.append(it)
        if len(out) >= limit:
            break
    return out
