from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT.parents[2] / ".github/workflows/developer-a-production-release.yml").read_text(encoding="utf-8")
DISPATCH = (ROOT / "bin/developer-a-ci-dispatch").read_text(encoding="utf-8")


def test_legacy_batch_actions_are_not_selectable_or_accepted():
    allowlist = WORKFLOW.split('case "$action" in', 1)[1].split(';;', 1)[0]
    choices = WORKFLOW.split("options:", 1)[1].split("transport:", 1)[0]
    assert "batch317-320" not in allowlist
    assert "batch317-320" not in choices
    assert "preflight-batch317-320)" not in DISPATCH
    assert "preflight-v330)" in DISPATCH
    assert "PREFLIGHT_V330_BIN" in DISPATCH
    assert "--build-run-id=*" in DISPATCH
    assert "deploy-v330-manifest-reuse" in choices
    assert '"preflight-v330 --build-run-id=' in WORKFLOW


def test_dispatcher_still_has_generic_reject_fallback():
    assert "Production release request rejected." in DISPATCH
    assert "  *)\n    reject" in DISPATCH


def installed_preflight(tmp_path):
    import json
    import sys
    import types
    from unittest.mock import patch
    control = tmp_path / "unified" / "ci-control"
    (control / "bin").mkdir(parents=True)
    (control / "config").mkdir()
    installed = control / "bin" / "production-image-preflight-v330"
    installed.write_bytes((ROOT / "bin/production-image-preflight-v330").read_bytes())
    identity = json.loads((ROOT / "ci/v330-release-identity.json").read_text(encoding="utf-8"))
    (control / "config/v330-release-identity.json").write_text(json.dumps(identity), encoding="utf-8")
    namespace = {"__file__": str(installed), "__name__": "installed_preflight_test"}
    with patch.dict(sys.modules, {"fcntl": types.ModuleType("fcntl")}):
        exec(compile(installed.read_text(encoding="utf-8"), str(installed), "exec"), namespace)
    namespace["load_identity"]()
    metadata = {"release_sha": identity["source_parent"], "migration_sha256": identity["baseline_migration_sha256"]}
    (control / "current.json").write_text(json.dumps(metadata), encoding="utf-8")
    ledger = {"git_commit": identity["source_parent"], "current_release_version": "2.44.315"}
    for path in (control.parent / "ledger/current-version.json", tmp_path / "shared-version-ledger/current-version.json"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(ledger), encoding="utf-8")
    namespace["command"] = lambda args: json.dumps([{"Id": args[-1], "State": {"Running": True}, "RestartCount": 0}])
    return namespace, control


def test_installed_layout_loads_identity_and_separate_ledger_schemas(tmp_path):
    namespace, control = installed_preflight(tmp_path)
    assert namespace["C"] == control
    assert namespace["LOCKS"][-1] == tmp_path / "shared-version-ledger/shared-version-ledger.lock"
    before = namespace["snapshot"]()
    assert before["control_sha256"] != before["ledger_sha256"]
    path = control / "current.json"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    after = namespace["snapshot"]()
    assert before["ledger_sha256"] == after["ledger_sha256"]
    assert before["control_sha256"] != after["control_sha256"]


def test_installed_layout_rejects_divergent_version_ledgers(tmp_path):
    import pytest
    namespace, _ = installed_preflight(tmp_path)
    (tmp_path / "shared-version-ledger/current-version.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        namespace["snapshot"]()


def test_installed_layout_rejects_wrong_control_baseline(tmp_path):
    import json
    import pytest
    namespace, control = installed_preflight(tmp_path)
    path = control / "current.json"
    metadata = json.loads(path.read_text())
    metadata["migration_sha256"] = "0" * 64
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError):
        namespace["snapshot"]()


def test_official_redis_short_repo_digest_matches_canonical_reference(tmp_path):
    namespace, _ = installed_preflight(tmp_path)
    digest = "sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
    ref = "docker.io/library/redis@" + digest
    assert namespace["repo_digest_matches"]("redis", ref, ["redis@" + digest])
    assert namespace["repo_digest_matches"]("redis", ref, [ref])


def test_redis_repo_digest_match_rejects_wrong_digest_and_other_registries(tmp_path):
    namespace, _ = installed_preflight(tmp_path)
    digest = "sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
    ref = "docker.io/library/redis@" + digest
    assert not namespace["repo_digest_matches"]("redis", ref, ["redis@sha256:" + "0" * 64])
    assert not namespace["repo_digest_matches"](
        "redis", ref, ["registry.example/library/redis@" + digest])
