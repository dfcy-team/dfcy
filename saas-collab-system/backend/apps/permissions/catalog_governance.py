"""Deterministic permission catalog and URL release manifest."""
import hashlib
import json
import inspect
from pathlib import Path

from apps.permissions.packages import is_high_risk_permission

SCHEMA_VERSION = 1
HTTP_ACTIONS = {"GET": "read", "HEAD": "read", "OPTIONS": "read", "POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(route, method, action, code=None, policy="review_required", classes=(), owner="unknown"):
    return {"route": route, "method": method, "action": action, "permission_code": code, "policy": policy, "permission_classes": list(classes), "owner": owner}


def classify_endpoint(route, callback, catalog_by_code):
    view = getattr(callback, "cls", None)
    if view is None:
        if route.startswith("admin/"):
            return [_row(route, m, HTTP_ACTIONS[m], policy="django_admin_session_staff_csrf", owner="django_admin")
                    for m in ("GET", "HEAD", "POST")]
        methods = sorted(set(getattr(callback, "allowed_methods", ())) & set(HTTP_ACTIONS)) or ["GET"]
        return [_row(route, m, "read" if m == "GET" else "exempt", policy="function_callback_default_get" if m == "GET" else "framework_exemption") for m in methods]
    route_actions = getattr(callback, "actions", None)
    names = [getattr(c, "__name__", str(c)) for c in getattr(view, "permission_classes", ())]
    declared = any(name == "DeclaredApplicationPermission" for name in names)
    owner_parts = getattr(view, "__module__", "").split(".")
    owner = owner_parts[1] if len(owner_parts) > 1 else "unknown"
    available = {str(m).lower() for m in getattr(view, "http_method_names", ())}
    methods = set()
    supported = {m.lower() for m in HTTP_ACTIONS}
    if route_actions:
        route_actions = {str(m).lower() for m in route_actions}
        methods.update(m for m in route_actions if m in supported and m != "options")
        if "get" in route_actions or "head" in route_actions: methods.add("head")
    else:
        methods.update(m for m in available if m in supported and m != "options" and hasattr(view, m))
        if "get" in methods: methods.add("head")
    if "options" in available: methods.add("options")
    rows = []
    for method in sorted(methods, key=lambda m: (m != "options", list(HTTP_ACTIONS).index(m.upper()) if m.upper() in HTTP_ACTIONS else 99)):
        verb = method.upper()
        if method == "options":
            rows.append(_row(route, verb, "exempt", policy="framework_options_exemption", classes=names, owner=owner)); continue
        code = getattr(view, "read_permission_code", None) if method in ("get", "head") else getattr(view, "write_permission_code", None)
        if declared and not code and view.__module__ in {"apps.pilot.views", "apps.pilot.ui_p8_views"}:
            # These reviewed dispatchers declare their operation from fixed
            # URL initkwargs, before executing any business request.
            instance = view(**getattr(callback, "initkwargs", {}))
            instance.get_permissions()
            code = getattr(instance, "read_permission_code", None) if method in ("get", "head") else getattr(instance, "write_permission_code", None)
        if not code: code = getattr(view, "permission_code", None)
        actual_special_codes = []
        for permission_class in getattr(view, "permission_classes", ()):
            pc = getattr(permission_class, "permission_code", None)
            if pc: actual_special_codes.append(pc)
            # Existing specialized guards include method-specific and OR
            # grants; record the declarations without replacing their logic.
            read = getattr(permission_class, "read_permission_code", None)
            write = getattr(permission_class, "write_permission_code", None)
            if read or write:
                get_only = permission_class.__module__ == "apps.products.permissions"
                chosen = read if method == "get" or (method == "head" and not get_only) else write
                if chosen: actual_special_codes.append(chosen)
            for attr in ("permission_codes", "codes"):
                values = getattr(permission_class, attr, ())
                if isinstance(values, (list, tuple, set)):
                    actual_special_codes.extend(value for value in values if isinstance(value, str))
        if code is None and actual_special_codes:
            code = actual_special_codes[0]
        if declared and not code:
            rows.append(_row(route, verb, "error", policy="declared_permission_missing", classes=names, owner=owner))
        elif (declared or actual_special_codes) and code not in catalog_by_code:
            rows.append(_row(route, verb, HTTP_ACTIONS[verb], code, "catalog_declaration_missing", names, owner))
        elif declared:
            row = _row(route, verb, HTTP_ACTIONS[verb], code, "catalog_permission", names, owner)
            definition = catalog_by_code.get(code, {})
            row["risk"] = "high" if is_high_risk_permission(code, action=definition.get("action"), permission_type=definition.get("permission_type", "action")) else "normal"
            rows.append(row)
        elif actual_special_codes:
            for specialized_code in sorted(set(actual_special_codes)):
                if specialized_code not in catalog_by_code:
                    rows.append(_row(route, verb, HTTP_ACTIONS[verb], specialized_code, "catalog_declaration_missing", names, owner)); continue
                row = _row(route, verb, HTTP_ACTIONS[verb], specialized_code, "specialized_catalog_permission", names, owner)
                row["permission_logic"] = "existing_specialized_guard"
                guard_sources = []
                for cls in getattr(view, "permission_classes", ()):
                    try: guard_sources.append(inspect.getsource(cls.has_permission))
                    except (AttributeError, OSError, TypeError): pass
                row["guard_source_sha256"] = hashlib.sha256("\n".join(guard_sources).encode()).hexdigest()
                definition = catalog_by_code.get(specialized_code, {})
                row["risk"] = "high" if is_high_risk_permission(specialized_code, action=definition.get("action"), permission_type=definition.get("permission_type", "action")) else "normal"
                rows.append(row)
        else:
            policy = "public_handler_guard" if "AllowAny" in names or not names else "subject_channel_or_object_guard"
            row = _row(route, verb, HTTP_ACTIONS[verb], policy=policy, classes=names, owner=owner)
            sources = []
            for cls in getattr(view, "permission_classes", ()):
                for guard in ("has_permission", "has_object_permission"):
                    try: sources.append(inspect.getsource(getattr(cls, guard)))
                    except (AttributeError, OSError, TypeError): pass
            # Internal checks inside public callbacks/channel handlers remain
            # visible in release diffs; identity policies are never new grants.
            try: sources.append(inspect.getsource(getattr(view, method if method != "head" else "get")))
            except (AttributeError, OSError, TypeError): pass
            row["guard_source_sha256"] = hashlib.sha256("\n".join(sources).encode()).hexdigest()
            rows.append(row)
    return rows


def build_manifest(definitions, endpoints):
    definitions = list(definitions)
    codes = [d.get("code") for d in definitions]
    if None in codes or len(codes) != len(set(codes)):
        raise ValueError("Duplicate or missing permission code in catalog")
    permissions = []
    for d in definitions:
        metadata = d.get("metadata") or {}
        from .resource_policies import permission_resource, RESOURCE_DEFINITIONS
        resource = permission_resource(d["code"])
        permissions.append({"code": d["code"], "name": d.get("name", ""), "module": d.get("module", ""), "action": d.get("action", ""), "permission_type": d.get("permission_type", "action"), "description": d.get("description", ""), "risk": "high" if is_high_risk_permission(d["code"], action=d.get("action"), permission_type=d.get("permission_type", "action")) else "normal", "lifecycle": metadata.get("registry_status", metadata.get("status", "active")), "menu_path": metadata.get("path", metadata.get("route", "")), "menu_code": d["code"], "resource_code": resource or metadata.get("resource", "legacy_resource"), "scope_adapter": "resource_policy_v1" if resource else "existing_business_adapter", "allowed_dimensions": RESOURCE_DEFINITIONS.get(resource, {}).get("dimensions", []), "owner": d.get("module", "unknown")})
    permissions.sort(key=lambda x: x["code"])
    endpoints.sort(key=lambda x: (x["route"], x["method"], x["action"], x.get("permission_code") or ""))
    if any(e["policy"] in ("declared_permission_missing", "catalog_declaration_missing") for e in endpoints):
        raise ValueError("Declared endpoint permission missing or absent from catalog")
    core = {"schema_version": SCHEMA_VERSION, "permissions": permissions, "endpoints": endpoints}
    core["catalog_hash"] = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    return core


def manifest_diff(old, new):
    def index(data, key): return {canonical_json(tuple(row.get(k) for k in key)): row for row in data}
    oldp, newp = index(old.get("permissions", []), ("code",)), index(new.get("permissions", []), ("code",))
    olde, newe = index(old.get("endpoints", []), ("route", "method", "permission_code")), index(new.get("endpoints", []), ("route", "method", "permission_code"))
    changes = []
    for bucket, a, b in (("permission", oldp, newp), ("endpoint", olde, newe)):
        for k in sorted(a.keys() - b.keys()): changes.append({"kind": bucket, "change": "removed", "before": a[k]})
        for k in sorted(b.keys() - a.keys()): changes.append({"kind": bucket, "change": "added", "after": b[k]})
        for k in sorted(a.keys() & b.keys()):
            if a[k] != b[k]: changes.append({"kind": bucket, "change": "changed", "before": a[k], "after": b[k]})
    high = [c for c in changes if any(row and str(row.get("risk", "")).lower() in ("high", "critical") for row in (c.get("before"), c.get("after")))]
    return {"added": sum(c["change"] == "added" for c in changes), "removed": sum(c["change"] == "removed" for c in changes), "changed": sum(c["change"] == "changed" for c in changes), "high_risk": high, "changes": changes}


def write_manifest(path, manifest):
    Path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
