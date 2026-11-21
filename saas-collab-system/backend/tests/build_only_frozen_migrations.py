"""Read migration sources from the explicitly approved historical Git trees."""
import io
import tempfile
import subprocess
import tarfile
from pathlib import Path

from scripts.production_build_only import migration_digest

FROZEN_SOURCES = {
    "9fa0d8ac4906c260801541d34585cb2e93eab8d6": (
        "3b10a0cb541b55ee9df955ebd4c5681aa698a948",
        "21eadb03414e1baa9fc71a9e5f56126e2a885bac790c476334deb9b36b1f9838",
    ),
    "278b8f8759fc427510d57bbdd7bc23297a5b3e80": (
        "2305aca1d6b50df256cf386dfe46b888ca5a8ac0",
        "f4837ab083886904019f352dc40a4fbb14f9fcbfd86352ecad0514c2b50cc649",
    ),
    "96dd97a2bd3ea51ef57ae6e1e40741e078122753": (
        "c1460c97e619ad4a35c36f9a8e523dc3ab239755",
        "f4837ab083886904019f352dc40a4fbb14f9fcbfd86352ecad0514c2b50cc649",
    ),
}


def frozen_migration_digest(repo_root, commit, tmp_path):
    """Hash only migration files from a fixed commit using the production algorithm."""
    if commit not in FROZEN_SOURCES:
        raise ValueError("Unregistered frozen source")
    expected_tree, _ = FROZEN_SOURCES[commit]
    tree = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=repo_root,
                          check=True, capture_output=True, text=True).stdout.strip()
    if tree != expected_tree:
        raise ValueError("Frozen tree does not match approved tree")
    proc = subprocess.run(
        ["git", "archive", "--format=tar", commit, "saas-collab-system/backend/apps"],
        cwd=repo_root, check=True, capture_output=True,
    )
    count = 0
    destination = Path(tempfile.mkdtemp(dir=tmp_path))
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            name = member.name
            if name.startswith("./"):
                name = name[2:]
            parts = name.split("/")
            if name.startswith("/") or ".." in parts:
                raise ValueError("Unsafe archive member")
            if member.issym() or member.islnk():
                raise ValueError("Archive symlinks are forbidden")
            if not (len(parts) == 6 and parts[:3] == ["saas-collab-system", "backend", "apps"]
                    and parts[4] == "migrations" and parts[5].endswith(".py")):
                continue
            if not member.isfile():
                raise ValueError("Unsupported archive member type")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError("Missing archive member data")
            target = destination.joinpath(*parts[2:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(extracted.read())
            count += 1
    if count == 0:
        raise ValueError("Missing frozen migrations")
    return migration_digest(destination)
