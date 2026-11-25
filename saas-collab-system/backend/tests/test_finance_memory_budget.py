from pathlib import Path

import pytest

from apps.finance.summary_memory import MemoryBudgetExceeded, node_heap_mb


MIB = 1024 * 1024


def write_limit(directory: Path, limit: int | str, usage: int, *, v2: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    names = ("memory.max", "memory.current") if v2 else ("memory.limit_in_bytes", "memory.usage_in_bytes")
    (directory / names[0]).write_text(str(limit))
    (directory / names[1]).write_text(str(usage))


@pytest.mark.parametrize("limit_mb,expected", [(1792, 1075), (2560, 1612)])
def test_heap_budget_for_container_sizes(tmp_path, limit_mb, expected):
    leaf = tmp_path / "cg" / "job"
    write_limit(leaf, limit_mb * MIB, 0)
    assert node_heap_mb(cgroup_dir=leaf) == expected


def test_ancestor_limit_caps_heap(tmp_path):
    parent = tmp_path / "cg"
    leaf = parent / "job"
    write_limit(parent, 1024 * MIB, 0)
    write_limit(leaf, 4 * 1024 * MIB, 0)
    assert node_heap_mb(cgroup_dir=leaf) == 537


def test_unbounded_cgroup_preserves_configuration(tmp_path):
    leaf = tmp_path / "cg" / "job"
    write_limit(leaf, "max", 0)
    assert node_heap_mb(cgroup_dir=leaf) == 2048


def test_v1_fallback(tmp_path):
    leaf = tmp_path / "cg" / "job"
    write_limit(leaf, 1792 * MIB, 0, v2=False)
    assert node_heap_mb(cgroup_dir=leaf) == 1075


def test_v1_mountinfo_uses_super_options_for_memory_controller(tmp_path):
    proc = tmp_path / "proc"
    self_dir = proc / "self"
    self_dir.mkdir(parents=True)
    mount = tmp_path / "cgmount"
    leaf = mount / "task"
    write_limit(leaf, 1792 * MIB, 0, v2=False)
    (self_dir / "cgroup").write_text("5:memory:/task\n")
    (self_dir / "mountinfo").write_text(f"29 23 0:26 / {mount} rw - cgroup cgroup rw,memory\n")
    assert node_heap_mb(proc_root=proc) == 1075


def test_v2_namespace_root_maps_to_mountpoint_and_uses_ancestor(tmp_path):
    proc = tmp_path / "proc"
    self_dir = proc / "self"
    self_dir.mkdir(parents=True)
    mount = tmp_path / "cgmount"
    leaf = mount / "job"
    write_limit(mount, 1024 * MIB, 0)
    write_limit(leaf, 4096 * MIB, 0)
    (self_dir / "cgroup").write_text("0::/\n")
    (self_dir / "mountinfo").write_text(f"29 23 0:26 /host/subtree {mount} rw - cgroup2 cgroup rw\n")
    assert node_heap_mb(proc_root=proc) == 537


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_configured_heap_must_be_positive_integer(value):
    with pytest.raises(ValueError):
        node_heap_mb(value)


def test_insufficient_memory_raises_instead_of_forcing_minimum(tmp_path):
    leaf = tmp_path / "cg" / "job"
    write_limit(leaf, 300 * MIB, 200 * MIB)
    with pytest.raises(MemoryBudgetExceeded):
        node_heap_mb(cgroup_dir=leaf)


def test_unknown_platform_keeps_configured_heap(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    assert node_heap_mb(512, proc_root=proc) == 512
