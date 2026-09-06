"""Read the checked-in, shared menu permission contract.

``backend/apps/permissions/menu_registry.json`` is generated from the
frontend sidebar declaration by the release/build step and is shipped with
both application images.  Django never imports or executes frontend
JavaScript at runtime; therefore ``sync_permissions`` and the
permission-package API work in the minimal Python image as well as on a
developer workstation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class MenuRegistryError(RuntimeError):
    """Raised when the shared menu contract is missing or malformed."""


def contract_path() -> Path:
    override = os.environ.get("MENU_REGISTRY_PATH")
    if override:
        return Path(override).expanduser().resolve()

    # Keep the generated snapshot beside this loader.  The backend Dockerfile
    # already copies the whole permissions package, so no Node/frontend files
    # are needed in the runtime image.
    return Path(__file__).with_name("menu_registry.json")


def load_menu_registry(*, timeout=20):
    """Return the shared menu registry and route contract.

    ``timeout`` is accepted for backwards compatibility with the previous
    JavaScript bridge; the static contract makes the read deterministic and
    does not spawn a child process.
    """
    del timeout
    path = contract_path()
    if not path.exists():
        raise MenuRegistryError(f"菜单权限契约不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MenuRegistryError(f"读取菜单权限契约失败: {path}: {exc}") from exc

    menus = payload.get("menus") if isinstance(payload, dict) else None
    routes = payload.get("routes", []) if isinstance(payload, dict) else None
    if not isinstance(menus, list) or not isinstance(routes, list):
        raise MenuRegistryError("菜单权限契约必须包含 menus/routes 数组")
    if not all(isinstance(item, dict) and item.get("code") for item in menus):
        raise MenuRegistryError("菜单权限契约包含无效登记项")
    return {"menus": menus, "routes": routes}


def load_menu_permission_definitions(*, timeout=20):
    """Return normalized menu permission definitions for the sync command."""

    return load_menu_registry(timeout=timeout)["menus"]
