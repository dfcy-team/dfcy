import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.urls import get_resolver

from apps.permissions.catalog import runtime_permission_definitions
from apps.permissions.catalog_governance import build_manifest, canonical_json, classify_endpoint, manifest_diff, write_manifest


class Command(BaseCommand):
    help = "Generate, compare, or check the versioned permission endpoint manifest."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--write", metavar="PATH")
        group.add_argument("--check", metavar="PATH")
        group.add_argument("--compare", metavar="PATH")

    def handle(self, *args, **opts):
        definitions = list(runtime_permission_definitions())
        codes = [d.get("code") for d in definitions]
        if None in codes or len(codes) != len(set(codes)):
            raise CommandError("Permission catalog contains duplicate or missing codes")
        by_code = {d["code"]: d for d in definitions}
        endpoints = []
        for pattern in get_resolver().url_patterns:
            self._walk(pattern, "", by_code, endpoints)
        current = build_manifest(definitions, endpoints)
        mode, path = next((k, opts[k]) for k in ("write", "check", "compare") if opts[k])
        target = Path(path)
        if mode == "write":
            write_manifest(target, current)
            self.stdout.write(f"Wrote {len(current['permissions'])} permissions and {len(current['endpoints'])} endpoint methods; hash={current['catalog_hash']}")
            return
        try:
            snapshot = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read manifest {target}: {exc}")
        diff = manifest_diff(snapshot, current)
        if mode == "check":
            if canonical_json(snapshot) != canonical_json(current):
                raise CommandError(f"Permission manifest drift: added={diff['added']} removed={diff['removed']} changed={diff['changed']}")
            self.stdout.write("Permission manifest matches current catalog and routes.")
        else:
            self.stdout.write(json.dumps({k: diff[k] for k in ("added", "removed", "changed")}, ensure_ascii=False))
            for row in diff["changes"][:20]: self.stdout.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            self.stdout.write(f"high_risk={len(diff['high_risk'])}; shown_changes={min(20, len(diff['changes']))}")

    def _walk(self, pattern, prefix, catalog, output):
        from django.urls import URLPattern, URLResolver
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            for child in pattern.url_patterns: self._walk(child, route, catalog, output)
        elif isinstance(pattern, URLPattern):
            output.extend(classify_endpoint(route, pattern.callback, catalog))
