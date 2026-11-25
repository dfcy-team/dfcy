"""Bounded, advisory cgroup-aware Node heap sizing for finance workers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

_MIB = 1024 * 1024
_NATIVE_RESERVE_MB = 256
_HEAP_FRACTION = 0.7
_MIN_HEAP_MB = 128


class MemoryBudgetExceeded(RuntimeError):
    """The available cgroup memory cannot safely support a Node heap."""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _budget_for_limits(directory: Path, limit_name: str, usage_name: str,
                       read_text: Callable[[Path], str]) -> int | None:
    budgets: list[int] = []
    current = directory
    while True:
        try:
            limit = read_text(current / limit_name).strip()
            usage = int(read_text(current / usage_name).strip())
            if limit.lower() != "max":
                available_mb = max(0, int(limit) - usage) // _MIB
                budgets.append(int(max(0, available_mb - _NATIVE_RESERVE_MB) * _HEAP_FRACTION))
        except (OSError, ValueError):
            pass
        if current.parent == current:
            break
        current = current.parent
    return min(budgets) if budgets else None


def _unescape_mount_path(value: str) -> str:
    return value.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def _discover_cgroup(proc_root: Path) -> tuple[Path, str] | None:
    try:
        cgroups = (proc_root / "self/cgroup").read_text(encoding="utf-8").splitlines()
        mounts = (proc_root / "self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    v2_path = next((line.split(":", 2)[2] for line in cgroups if line.startswith("0::")), None)
    memory_path = None
    for line in cgroups:
        parts = line.split(":", 2)
        if len(parts) == 3 and "memory" in parts[1].split(","):
            memory_path = parts[2]
            break
    for line in mounts:
        fields = line.split()
        if "-" not in fields:
            continue
        sep = fields.index("-")
        fs_type = fields[sep + 1]
        root, mountpoint = Path(_unescape_mount_path(fields[3])), Path(_unescape_mount_path(fields[4]))
        if fs_type == "cgroup2" and v2_path:
            cg_path = Path(v2_path)
            relative = cg_path.relative_to(root) if cg_path.is_relative_to(root) else Path()
            return mountpoint / relative, "v2"
        if fs_type == "cgroup" and memory_path and len(fields) > sep + 3 and "memory" in fields[sep + 3].split(","):
            cg_path = Path(memory_path)
            relative = cg_path.relative_to(root) if cg_path.is_relative_to(root) else Path()
            return mountpoint / relative, "v1"
    return None


def node_heap_mb(configured_mb: int = 2048, *, proc_root: str | Path = "/proc",
                 cgroup_dir: str | Path | None = None,
                 read_text: Callable[[Path], str] | None = None) -> int:
    """Return an advisory heap cap; native allocations can still exceed this budget."""
    if isinstance(configured_mb, bool) or not isinstance(configured_mb, int) or configured_mb <= 0:
        raise ValueError("configured_mb must be a positive integer")
    reader = read_text or _read_text
    if cgroup_dir is not None:
        directory = Path(cgroup_dir)
        v2 = any((parent / "memory.max").exists() for parent in (directory, *directory.parents))
        names = ("memory.max", "memory.current") if v2 else ("memory.limit_in_bytes", "memory.usage_in_bytes")
    else:
        found = _discover_cgroup(Path(proc_root))
        if found is None:
            return configured_mb
        directory, version = found
        names = ("memory.max", "memory.current") if version == "v2" else ("memory.limit_in_bytes", "memory.usage_in_bytes")
    budget = _budget_for_limits(directory, *names, reader)
    if budget is None:
        return configured_mb
    result = min(configured_mb, budget)
    if result < _MIN_HEAP_MB:
        raise MemoryBudgetExceeded(f"available cgroup memory permits only {result} MiB Node heap")
    return result
