"""Small, explainable role permission packages.

The package layer is a presentation/convenience layer over the canonical
permission catalog.  It never creates a second permission registry: every
expanded code must already exist in ``ALL_PERMISSION_DEFINITIONS`` and the
role still stores the normal ``Permission`` many-to-many relation.
"""

from .catalog import ALL_PERMISSION_DEFINITIONS


PACKAGE_LEVELS = ("none", "read", "operate", "admin")

# These actions have materially higher impact than routine module operation.
# They are intentionally excluded from both ``operate`` and ``admin`` package
# expansion and must be supplied through explicit extra_permission_codes.
HIGH_RISK_ACTION_PARTS = {
    "delete",
    "review",
    "approve",
    "export",
    "credential",
    "authorize",
    "revoke",
    "rollback",
    "publish",
    "production",
    "confirm",
    "freeze",
    "rotate",
    "disable",
    "verify",
    "cancel",
    "clear",
    "run_live_readonly",
    "execute",
    "start",
    "resume",
    "record",
    "deploy",
    "restore",
}

# Management capabilities are privilege-escalating even when their action
# suffix is the otherwise routine-looking ``manage``.  Keep this explicit so
# a broad module package can never silently grant control of the RBAC surface,
# tenant user assignments, or system configuration.
HIGH_RISK_PERMISSION_CODES = {
    "system.roles.manage",
    "system.users.manage",
    "system.organization.manage",
    "config.system.manage",
}


def _permission_type(definition):
    return definition.get("permission_type", "action")


def _is_high_risk(definition):
    return is_high_risk_permission(
        definition.get("code"),
        action=definition.get("action"),
        permission_type=_permission_type(definition),
    )


def is_high_risk_permission(code, *, action=None, permission_type="action"):
    """Classify one permission using the same policy as package expansion.

    ``code`` may come from an existing database row that is not currently in
    the catalog.  Falling back to its trusted action metadata keeps legacy
    permission-code requests fail-closed instead of allowing an unregistered
    high-impact action to bypass explicit confirmation.
    """
    if permission_type != "action":
        return False
    if code in HIGH_RISK_PERMISSION_CODES:
        return True
    parts = set(str(action or "").split("."))
    return bool(parts & HIGH_RISK_ACTION_PARTS)


def _definitions_by_module():
    grouped = {}
    for definition in ALL_PERMISSION_DEFINITIONS:
        grouped.setdefault(definition["module"], []).append(definition)
    return grouped


def permission_package_catalog():
    """Return package metadata for the role quick-assignment UI/API."""
    packages = []
    for module, definitions in sorted(_definitions_by_module().items()):
        menus = [d["code"] for d in definitions if _permission_type(d) == "menu"]
        fields = [d["code"] for d in definitions if _permission_type(d) == "field"]
        actions = [d for d in definitions if _permission_type(d) == "action"]
        high_risk = [d["code"] for d in actions if _is_high_risk(d)]
        routine_actions = [d["code"] for d in actions if not _is_high_risk(d)]
        read_actions = [
            d["code"] for d in actions
            if str(d.get("action") or "").split(".")[-1] == "view"
        ]
        # Menu and non-sensitive field grants accompany the module's read
        # package.  Routine actions accompany the module-admin package, while
        # the ordinary operation package deliberately leaves ``*.manage``
        # capabilities for an explicit administrator-level choice.
        read_codes = sorted(set(menus + fields + read_actions))
        operate_actions = [
            d["code"] for d in actions
            if not _is_high_risk(d)
            and str(d.get("action") or "").rsplit(".", 1)[-1] != "manage"
        ]
        admin_codes = sorted(set(read_codes + routine_actions))
        operate_codes = sorted(set(read_codes + operate_actions))
        packages.append({
            "module": module,
            "levels": {
                "none": [],
                "read": read_codes,
                "operate": operate_codes,
                "admin": admin_codes,
            },
            "high_risk_codes": sorted(high_risk),
            "available_codes": sorted(d["code"] for d in definitions),
        })
    return packages


def package_index():
    return {item["module"]: item for item in permission_package_catalog()}


def expand_package_selections(selections, extra_permission_codes=()):
    """Expand validated module levels into canonical permission codes.

    ``selections`` is a mapping of module name to one of the four levels.  A
    non-empty selection is intentionally required to be a known catalog
    module; this makes newly-added modules visible in sync/check and prevents
    silently accepting a typo from an administrator UI.
    """
    if selections is None:
        selections = {}
    if not isinstance(selections, dict):
        raise ValueError("package_selections must be an object mapping modules to levels")
    index = package_index()
    unknown = sorted(set(selections) - set(index))
    if unknown:
        raise ValueError(f"Unknown permission package modules: {', '.join(unknown)}")
    invalid = sorted(
        f"{module}:{level}"
        for module, level in selections.items()
        if level not in PACKAGE_LEVELS
    )
    if invalid:
        raise ValueError(f"Invalid permission package levels: {', '.join(invalid)}")
    codes = set()
    for module, level in selections.items():
        codes.update(index[module]["levels"][level])

    extras = set(extra_permission_codes or ())
    all_codes = {
        code
        for item in index.values()
        for code in item["available_codes"]
    }
    unknown_extra = sorted(extras - all_codes)
    if unknown_extra:
        raise ValueError(f"Unknown extra permission codes: {', '.join(unknown_extra)}")
    all_high_risk = {code for item in index.values() for code in item["high_risk_codes"]}
    non_risk_extras = sorted(extras - all_high_risk)
    if non_risk_extras:
        raise ValueError(
            "extra_permission_codes may contain only high-risk permissions: "
            + ", ".join(non_risk_extras)
        )
    definition_by_code = {
        code: definition
        for definition in ALL_PERMISSION_DEFINITIONS
        for code in [definition["code"]]
    }
    selected_modules = set(selections)
    extra_modules = {
        definition_by_code[code]["module"]
        for code in extras
    }
    missing_modules = sorted(extra_modules - selected_modules)
    if missing_modules:
        raise ValueError(
            "extra_permission_codes require an explicit package selection for modules: "
            + ", ".join(missing_modules)
        )
    none_modules = sorted(
        module for module in extra_modules
        if selections.get(module) == "none"
    )
    if none_modules:
        raise ValueError(
            "extra_permission_codes cannot be granted when the module level is none: "
            + ", ".join(none_modules)
        )
    codes.update(extras)
    return sorted(codes)


def high_risk_codes_for_modules(modules):
    index = package_index()
    return sorted({
        code
        for module in modules
        if module in index
        for code in index[module]["high_risk_codes"]
    })


def high_risk_permission_codes():
    """Return the catalog-derived high-risk action permission codes."""
    return {
        code
        for item in permission_package_catalog()
        for code in item["high_risk_codes"]
    }
