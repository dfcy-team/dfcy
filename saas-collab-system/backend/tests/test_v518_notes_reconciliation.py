import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[2] / "deploy/production-control/release_notes.py"
SPEC = importlib.util.spec_from_file_location("release_notes_gate", MODULE)
rn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rn)
PRODUCTION_HISTORY_SHA = rn.V518_HISTORY_SHA
PRODUCTION_BASE_SHA = rn.V518_BASE_SHA


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_controller_git_root_decodes_utf8_for_non_ascii_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "候选源码"
    repo.mkdir()
    git(repo, "init", "-q")
    module = repo / "saas-collab-system/deploy/production-control/release_notes.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(rn, "__file__", str(module))
    actual = subprocess.check_output
    def explicit_encoding(command, **kwargs):
        if "--show-toplevel" in command:
            assert kwargs.get("encoding") == "utf-8"
        return actual(command, **kwargs)
    monkeypatch.setattr(rn.subprocess, "check_output", explicit_encoding)
    assert rn.repo_root() == repo.resolve()


def test_source_manifest_excludes_notes_and_normalizes_text_lf(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    notes = repo / "saas-collab-system/frontend/src/data/releaseNotes.json"
    notes.parent.mkdir(parents=True)
    notes.write_bytes(b"original")
    source = repo / "saas-collab-system/src.vue"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"one\r\ntwo\r\n")
    binary = repo / "saas-collab-system/blob.dat"
    binary.write_bytes(b"\0\r\n")
    git(repo, "add", "saas-collab-system/src.vue")
    git(repo, "commit", "-qm", "base")
    initial = rn.source_material_sha256(repo, notes)
    notes.write_bytes(b"changed notes ignored")
    assert rn.source_material_sha256(repo, notes) == initial
    source.write_bytes(b"one\ntwo\n")
    assert rn.source_material_sha256(repo, notes) == initial
    binary.write_bytes(b"\0\n")
    assert rn.source_material_sha256(repo, notes) != initial
    binary.write_bytes(b"\0\r\n")
    source.write_text("changed\n", encoding="utf-8")
    assert rn.source_material_sha256(repo, notes) != initial
    source.write_bytes(b"one\n")
    untracked = repo / "saas-collab-system/untracked.mjs"
    untracked.write_text("new\n", encoding="utf-8")
    changed = rn.source_material_sha256(repo, notes)
    untracked.write_text("newer\n", encoding="utf-8")
    assert rn.source_material_sha256(repo, notes) != changed


def test_unpaired_gate_and_draft_binding_are_rejected(tmp_path):
    class Args:
        reconciliation_binding = str(tmp_path / "binding.json")
        reconciliation_authorization = None

    with pytest.raises(ValueError, match="supplied together"):
        rn.reconciliation(Args())


def test_symlink_in_source_material_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    notes = repo / "saas-collab-system/frontend/src/data/releaseNotes.json"
    notes.parent.mkdir(parents=True)
    notes.write_text("[]", encoding="utf-8")
    (repo / "link.txt").symlink_to(notes)
    with pytest.raises(ValueError, match="symlink or junction forbidden"):
        rn.source_material_sha256(repo, notes)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def gate_case(tmp_path, monkeypatch):
    repo = tmp_path / "clone"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    root = repo / "saas-collab-system"
    notes = root / "frontend/src/data/releaseNotes.json"
    notes.parent.mkdir(parents=True)
    history = [{"version": "2.44.518", "date": "2026-11-20", "changes": ["old"]}]
    for n in range(57):
        history.append({"version": f"2.44.{517-n}", "date": "2026-11-19", "changes": [f"h{n}"]})
    history_raw = (json.dumps(history, ensure_ascii=False, indent=2) + "\n").encode()
    history_path = tmp_path / "history.json"
    history_path.write_bytes(history_raw)
    append = ["approved addition"]
    expected = [dict(history[0], changes=["old", *append]), *history[1:]]
    expected_raw = (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode()
    before = [{"version": "2.44.518", "date": "2026-11-20", "changes": ["VM candidate"]}, *history[1:]]
    before_raw = (json.dumps(before, ensure_ascii=False, indent=2) + "\n").encode()
    notes.write_bytes(before_raw)
    (root / "source.vue").write_bytes(b"vue\r\n")
    (root / "blob.dat").write_bytes(b"\x00\r\n")
    git(repo, "add", "saas-collab-system")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(rn, "repo_root", lambda: repo)
    monkeypatch.setattr(rn, "V518_BASE_SHA", base)
    monkeypatch.setattr(rn, "V518_HISTORY_SHA", _sha(history_raw))
    material = rn.source_material_sha256(repo, notes)
    binding = {"status": "REVIEWED_SAME_VERSION_RECONCILIATION", "version": rn.V518_VERSION,
               "release_date": "2026-11-21", "base_source_sha": base,
               "history_sha256": _sha(history_raw), "append_changes": append,
               "append_changes_sha256": _sha(json.dumps(append, ensure_ascii=False, separators=(",", ":")).encode()),
               "expected_notes_sha256": _sha(expected_raw), "source_material_sha256": material,
               "candidate_notes_before_sha256": _sha(before_raw)}
    binding_raw = json.dumps(binding, ensure_ascii=False, separators=(",", ":")).encode()
    binding_path, auth_path = tmp_path / "binding.json", tmp_path / "auth.json"
    binding_path.write_bytes(binding_raw)
    auth_path.write_text(json.dumps({"status": "AUTHORIZED", "scope": rn.V518_SCOPE,
                                    "human_message": "Reviewed and approved", "binding_sha256": _sha(binding_raw)}), encoding="utf-8")
    changes_path = tmp_path / "changes.json"
    changes_path.write_text(json.dumps(append), encoding="utf-8")
    return {"repo": repo, "notes": notes, "history": history_path, "binding": binding_path,
            "auth": auth_path, "changes": changes_path, "expected": expected_raw, "before": before_raw,
            "binding_obj": binding, "auth_obj": json.loads(auth_path.read_text())}


def _args(case, **overrides):
    values = dict(notes=str(case["notes"]), history=str(case["history"]), version=rn.V518_VERSION,
                  changes_file=str(case["changes"]), date="2026-11-21",
                  reconciliation_binding=str(case["binding"]), reconciliation_authorization=str(case["auth"]))
    values.update(overrides)
    return type("Args", (), values)()


def test_prepare_check_preserves_history_and_is_idempotent(gate_case):
    case = gate_case
    assert PRODUCTION_HISTORY_SHA == "0174464f65c46597576477cad0fce6a6eaad1097861b0b4036fc50f32c3a147f"
    assert PRODUCTION_BASE_SHA == "9728c548cce4c21d9cbc99aea7407298b4056fc7"
    rn.prepare(_args(case))
    assert case["notes"].read_bytes() == case["expected"]
    git(case["repo"], "add", "saas-collab-system/frontend/src/data/releaseNotes.json")
    git(case["repo"], "commit", "-qm", "synthetic prepared source")
    rn.check(_args(case))
    rn.prepare(_args(case))
    assert case["notes"].read_bytes() == case["expected"]


def resign_fixture(case):
    raw = json.dumps(case["binding_obj"], ensure_ascii=False, separators=(",", ":")).encode()
    case["binding"].write_bytes(raw)
    case["auth_obj"]["binding_sha256"] = _sha(raw)
    case["auth"].write_text(json.dumps(case["auth_obj"]), encoding="utf-8")


def test_prepare_accepts_exact_cloud_history_input(gate_case):
    case = gate_case
    case["notes"].write_bytes(case["history"].read_bytes())
    rn.prepare(_args(case))
    assert case["notes"].read_bytes() == case["expected"]
    rn.check(_args(case))


@pytest.mark.parametrize("append", [[" "], [None], [12], [{}]])
def test_direct_check_rejects_invalid_append_even_with_matching_hashes(gate_case, append):
    case = gate_case
    original = json.loads(case["history"].read_bytes())
    original[0]["changes"].extend(append)
    data = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()
    case["binding_obj"]["append_changes"] = append
    case["binding_obj"]["append_changes_sha256"] = _sha(json.dumps(append, ensure_ascii=False, separators=(",", ":")).encode())
    case["binding_obj"]["expected_notes_sha256"] = _sha(data)
    case["notes"].write_bytes(data)
    resign_fixture(case)
    with pytest.raises(ValueError, match="non-empty strings"):
        rn.reconciliation(_args(case), require_result=True)
    assert case["notes"].read_bytes() == data


@pytest.mark.parametrize("before_sha", [None, "bad", 12])
def test_direct_check_requires_reviewed_before_digest(gate_case, before_sha):
    case = gate_case
    case["notes"].write_bytes(case["expected"])
    if before_sha is None:
        case["binding_obj"].pop("candidate_notes_before_sha256")
    else:
        case["binding_obj"]["candidate_notes_before_sha256"] = before_sha
    resign_fixture(case)
    with pytest.raises(ValueError, match="candidate-before SHA"):
        rn.reconciliation(_args(case), require_result=True)


def test_source_material_rejects_parent_directory_link(gate_case, tmp_path):
    case = gate_case
    parent = case["repo"] / "linked-parent"
    parent.mkdir()
    (parent / "file.txt").write_text("source", encoding="utf-8")
    git(case["repo"], "add", "linked-parent/file.txt")
    (parent / "file.txt").unlink()
    parent.rmdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "file.txt").write_text("outside", encoding="utf-8")
    parent.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink or junction forbidden"):
        rn.source_material_sha256(case["repo"], case["notes"])


def test_actual_unrelated_head_is_rejected(gate_case):
    case = gate_case
    tree = subprocess.check_output(["git", "-C", str(case["repo"]), "hash-object", "-t", "tree", "--stdin"], input=b"").decode().strip()
    unrelated = git(case["repo"], "commit-tree", tree, "-m", "synthetic unrelated head")
    git(case["repo"], "update-ref", "--no-deref", "HEAD", unrelated)
    with pytest.raises(ValueError, match="not an ancestor"):
        rn.reconciliation(_args(case))


def test_prepare_only_writes_validated_path_with_ignored_link_and_dotdot(gate_case, tmp_path, monkeypatch):
    case = gate_case
    external_parent = tmp_path / "outside"
    target = external_parent / "link-target"
    target.mkdir(parents=True)
    outside_notes = external_parent / "saas-collab-system/frontend/src/data/releaseNotes.json"
    outside_notes.parent.mkdir(parents=True)
    outside_notes.write_bytes(case["before"])
    (case["repo"] / ".gitignore").write_text("ignored-link\n", encoding="utf-8")
    (case["repo"] / "ignored-link").symlink_to(target, target_is_directory=True)
    raw_notes = case["repo"] / "ignored-link" / ".." / "saas-collab-system/frontend/src/data/releaseNotes.json"
    case["binding_obj"]["source_material_sha256"] = rn.source_material_sha256(case["repo"], case["notes"])
    resign_fixture(case)
    actual_write = rn.atomic_write
    writes = []
    def checked_write(path, data):
        assert Path(path) == case["notes"]
        writes.append(Path(path))
        return actual_write(path, data)
    monkeypatch.setattr(rn, "atomic_write", checked_write)
    rn.prepare(_args(case, notes=str(raw_notes)))
    assert writes == [case["notes"]]
    assert case["notes"].read_bytes() == case["expected"]
    assert outside_notes.read_bytes() == case["before"]


def test_bad_append_and_notes_drift_reject_without_write(gate_case):
    case = gate_case
    original = case["notes"].read_bytes()
    case["changes"].write_text('["different"]', encoding="utf-8")
    with pytest.raises(ValueError, match="changes-file"):
        rn.prepare(_args(case))
    assert case["notes"].read_bytes() == original
    case["changes"].write_text('["approved addition"]', encoding="utf-8")
    case["notes"].write_bytes(b"[]\n")
    original = case["notes"].read_bytes()
    with pytest.raises(ValueError):
        rn.prepare(_args(case))
    assert case["notes"].read_bytes() == original


def test_binding_raw_bytes_and_unrelated_base_are_rejected(gate_case):
    case = gate_case
    raw = case["binding"].read_bytes()
    case["binding"].write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="exact binding"):
        rn.reconciliation(_args(case))
    case["binding"].write_bytes(raw)
    case["binding_obj"]["base_source_sha"] = "f" * 40
    changed = json.dumps(case["binding_obj"], separators=(",", ":")).encode()
    case["binding"].write_bytes(changed)
    case["auth_obj"]["binding_sha256"] = _sha(changed)
    case["auth"].write_text(json.dumps(case["auth_obj"]), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed V518 base"):
        rn.reconciliation(_args(case))


def test_aliyun_wrapper_forwards_pair_rejects_cross_day_build_and_allows_late_confirm(tmp_path, monkeypatch):
    wrapper_path = MODULE.with_name("aliyun_notes.py")
    spec = importlib.util.spec_from_file_location("aliyun_notes_gate", wrapper_path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    frontend = tmp_path / "frontend"
    notes = frontend / "src/data/releaseNotes.json"
    notes.parent.mkdir(parents=True)
    notes.write_bytes(b"expected bytes")
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps({"release_date": "2000-01-01"}), encoding="utf-8")
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text("[]", encoding="utf-8")
    calls = []
    monkeypatch.setattr(wrapper, "HERE", tmp_path)
    monkeypatch.setattr(wrapper, "FRONTEND", frontend)
    monkeypatch.setattr(wrapper, "NOTES", notes)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(sys, "argv", ["aliyun_notes.py", "build", "--version", rn.V518_VERSION, "--history", str(history), "--reconciliation-binding", str(binding), "--reconciliation-authorization", str(auth)])
    with pytest.raises(ValueError, match="binding Beijing release date"):
        wrapper.main()
    assert len(calls) == 1 and calls[0][1:3] == [str(tmp_path / "release_notes.py"), "check"]
    assert "--reconciliation-binding" in calls[0] and "--reconciliation-authorization" in calls[0]

    receipt = tmp_path / "deploy-pass.json"
    receipt.write_text(json.dumps({"status": "PASS", "version": rn.V518_VERSION}), encoding="utf-8")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return notes.read_bytes()
    monkeypatch.setattr(wrapper.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["aliyun_notes.py", "confirm", "--version", rn.V518_VERSION, "--history", str(history), "--reconciliation-binding", str(binding), "--reconciliation-authorization", str(auth), "--deployment-receipt", str(receipt), "--url", "https://example.invalid/notes.json", "--output", str(tmp_path / "out.json")])
    wrapper.main()
    assert len(calls) == 2
    assert "--reconciliation-binding" in calls[0] and "--reconciliation-authorization" in calls[0]
    assert calls[1][1:3] == [str(tmp_path / "release_notes.py"), "finalize"]


@pytest.mark.parametrize("mutate", ["draft", "message", "binding_hash", "history_hash", "append_hash", "append_text", "expected_hash", "date", "source", "notes", "version", "base"])
def test_prepare_rejects_unapproved_drift_without_writing(gate_case, mutate):
    case = gate_case
    if mutate == "draft": case["binding_obj"]["status"] = "DRAFT_NOT_AUTHORIZED_NOT_APPLIED"
    elif mutate == "message": case["auth_obj"].pop("human_message")
    elif mutate == "binding_hash": case["auth_obj"]["binding_sha256"] = "0" * 64
    elif mutate == "history_hash": case["binding_obj"]["history_sha256"] = "0" * 64
    elif mutate == "append_hash": case["binding_obj"]["append_changes_sha256"] = "0" * 64
    elif mutate == "append_text": case["binding_obj"]["append_changes"] = ["tampered"]
    elif mutate == "expected_hash": case["binding_obj"]["expected_notes_sha256"] = "0" * 64
    elif mutate == "date": case["binding_obj"]["release_date"] = "2026-11-20"
    elif mutate == "source": (case["repo"] / "saas-collab-system/source.vue").write_text("changed", encoding="utf-8")
    elif mutate == "notes": case["notes"].write_bytes(b"[]\n")
    elif mutate == "version": pass
    elif mutate == "base": case["binding_obj"]["base_source_sha"] = "0" * 40
    if mutate not in {"source", "notes"}:
        raw = json.dumps(case["binding_obj"], ensure_ascii=False, separators=(",", ":")).encode()
        case["binding"].write_bytes(raw)
        case["auth_obj"]["binding_sha256"] = _sha(raw)
        if mutate == "binding_hash": case["auth_obj"]["binding_sha256"] = "0" * 64
    case["auth"].write_text(json.dumps(case["auth_obj"]), encoding="utf-8")
    original = case["notes"].read_bytes()
    args = _args(case, version="2.44.517" if mutate == "version" else rn.V518_VERSION)
    with pytest.raises((ValueError, OSError)):
        rn.prepare(args)
    assert case["notes"].read_bytes() == original
