"""Offer only released permissions for new role assignments; keep old links."""
from apps.common.module_gate import module_statuses
from .menu_registry import load_menu_permission_definitions

# Match the route release gates in frontend/router/menu.js, most specific first.
MODULE_PATH_PREFIXES = (
    ("/integrations", "api_integrations"), ("/listings", "global_listing"),
    ("/influencers", "influencer"), ("/sales-management", "sales"), ("/pricing", "sales"),
    ("/finance", "finance"), ("/analytics", "analytics"), ("/decision/inventory", "inventory"),
    ("/inventory", "inventory"), ("/decision/lifecycle", "decision"), ("/decision/alerts", "decision"),
    ("/lifecycle", "decision"), ("/alerts/business", "decision"), ("/reports", "reports"),
    ("/workflow", "workflow"), ("/rpa", "rpa"), ("/development", "product_development"),
    ("/products/research", "product_development"), ("/products", "masterdata"),
    ("/purchasing", "supply_chain"), ("/supply-chain", "supply_chain"),
    ("/suppliers/performance", "supply_chain"), ("/master-data", "masterdata"),
    ("/system", "system"), ("/audit", "system"), ("/releases", "system"),
    ("/settings/platform-readiness", "api_integrations"), ("/settings/platform-risk", "api_integrations"),
    ("/settings/security-review", "api_integrations"), ("/settings", "system"),
    ("/governance", "governance"), ("/pilot", "governance"),
)
EXCLUSIVE_MODULES = {"development": "product_development", "rpa": "rpa", "supply": "supply_chain", "purchasing": "supply_chain", "listings": "global_listing"}

def module_for_path(path):
    return next((module for prefix, module in MODULE_PATH_PREFIXES if path == prefix or path.startswith(prefix + "/")), "")

def unavailable_assignment_codes(permissions, *, statuses=None, menus=None):
    states = module_statuses() if statuses is None else statuses
    definitions = load_menu_permission_definitions() if menus is None else menus
    disabled = lambda menu: states.get(module_for_path(menu.get("metadata", {}).get("path", ""))) == "disabled"
    unavailable = {menu["code"] for menu in definitions if disabled(menu)}
    stems = {}
    for menu in definitions:
        for code in menu.get("metadata", {}).get("action_codes", []):
            stems.setdefault(code.rsplit(".", 1)[0], []).append(menu)
    for permission in permissions:
        code = permission.code
        if permission.permission_type != "action":
            continue
        pages = stems.get(code.rsplit(".", 1)[0], [])
        exclusive = EXCLUSIVE_MODULES.get(permission.module)
        if (pages and all(disabled(menu) for menu in pages)) or (not pages and exclusive and states.get(exclusive) == "disabled"):
            unavailable.add(code)
    return unavailable
