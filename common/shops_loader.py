# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from common.shop_registry import merge_shop_tags


def load_shops(hub_dir: Path, enabled: list[str] | str = "all") -> list[dict]:
    manifest = hub_dir / "shops.json"
    if not manifest.exists():
        raise FileNotFoundError(f"找不到 shops.json: {manifest}")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    shops = data.get("shops") or []
    if enabled != "all":
        wanted = {k.upper() for k in enabled}
        shops = [s for s in shops if s.get("key", "").upper() in wanted]
        missing = wanted - {s.get("key", "").upper() for s in shops}
        if missing:
            print(f"警告: 以下店铺键不在 shops.json 中: {', '.join(sorted(missing))}")

    return merge_shop_tags(shops)
