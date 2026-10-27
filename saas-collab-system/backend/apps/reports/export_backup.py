"""Copy authorized-by-operator report records into a new, private backup package.

This is an explicit local maintenance operation, not an HTTP download bypass or
an automatic retention task. Database snapshot coordination is still required.
"""
import hashlib
import json
from pathlib import Path
from django.utils import timezone

from .object_storage import open_verified_export


def build_package(records, destination):
    destination = Path(destination)
    # Never overwrite, merge into, or follow an existing package directory.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    try:
        for record in records:
            item = {key: getattr(record, key) for key in (
                "id", "tenant_id", "requested_by_id", "report_type", "file_format",
                "storage_alias", "storage_key", "file_size", "file_sha256", "content_type")}
            item["expires_at"] = record.expires_at.isoformat() if record.expires_at else None
            if record.expires_at and record.expires_at <= timezone.now():
                item["state"] = "expired_metadata_only"
            elif not record.storage_key:
                item["state"] = "no_file"
            else:
                # DB ownership and scope must be restored from the paired DB
                # snapshot. This package never extends an export's expiry.
                name = f"export-{int(record.pk)}.bin"
                with open_verified_export(record) as source, (destination / name).open("xb") as target:
                    digest, size = hashlib.sha256(), 0
                    while chunk := source.read(64 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                item.update(state="verified", package_file=name,
                            backup_size=size, backup_sha256=digest.hexdigest())
            entries.append(item)
        manifest = {"schema": 1, "kind": "report-export-backup", "complete": True,
                    "created_at": timezone.now().isoformat(), "exports": entries,
                    "requires_paired_database_snapshot": True}
        with (destination / "manifest.json").open("x", encoding="utf-8") as out:
            json.dump(manifest, out, ensure_ascii=False, indent=2)
        return manifest
    except Exception:
        # Keep partial evidence, with no complete manifest. Never remove source
        # files or remotely delete uncertain writes as a side effect.
        raise


def verify_package(directory):
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if directory.is_symlink() or manifest_path.is_symlink() or manifest_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Invalid report backup package")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "report-export-backup" or manifest.get("schema") != 1 or manifest.get("complete") is not True:
        raise ValueError("Incomplete report backup package")
    seen = set()
    for entry in manifest["exports"]:
        if entry["state"] not in {"verified", "expired_metadata_only", "no_file"}:
            raise ValueError("Invalid report backup entry")
        if entry["state"] != "verified":
            continue
        expected = f"export-{int(entry['id'])}.bin"
        if entry.get("package_file") != expected or expected in seen:
            raise ValueError("Invalid report backup path")
        seen.add(expected)
        path = directory / expected
        if path.is_symlink() or not path.is_file():
            raise ValueError("Invalid report backup file")
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if (digest.hexdigest() != entry["backup_sha256"] or digest.hexdigest() != entry["file_sha256"]
                or size != entry["backup_size"] or (entry["file_size"] is not None and size != entry["file_size"])):
            raise ValueError("Report backup integrity mismatch")
    return manifest
