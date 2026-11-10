import os

import pytest
from cryptography.fernet import Fernet

from apps.integrations.custody_service import EncryptedFileCredentialStore
from apps.integrations.file_custody import FileCustodyError, FileCustodyNotFoundError


def _store(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    if os.name != "nt":
        os.chmod(key, 0o400)
    return EncryptedFileCredentialStore(tmp_path / "records", key)


def _write(store, name, token, secret="value"):
    store._write(name, {
        "credential_id": name, "token_id": token, "version": 1,
        "status": "active", "credentials": {"api_key": secret},
    })


def test_warm_lookup_decrypts_only_target_and_invalidates_changed_files(tmp_path, monkeypatch):
    store = _store(tmp_path)
    for i in range(120):
        _write(store, f"cred_{i:04d}", f"tok_{i:04d}")

    decrypts = 0
    original = store._decrypt_values

    def counted(value):
        nonlocal decrypts
        decrypts += 1
        return original(value)

    monkeypatch.setattr(store, "_decrypt_values", counted)
    assert store._resolve_credentials("tok_0119") == {"api_key": "value"}
    assert decrypts == 120  # first request authenticates preceding records
    decrypts = 0
    assert store._resolve_credentials("tok_0119") == {"api_key": "value"}
    assert decrypts == 1

    # Updating an earlier record invalidates only that entry; lookup still authenticates its prefix.
    _write(store, "cred_0001", "tok_replaced")
    decrypts = 0
    assert store._resolve_credentials("tok_0119") == {"api_key": "value"}
    assert decrypts == 2  # changed prefix plus selected target
    with pytest.raises(FileCustodyNotFoundError):
        store._resolve_credentials("tok_0001")
    assert store._resolve_credentials("tok_replaced") == {"api_key": "value"}


def test_lookup_tracks_add_delete_duplicate_and_revoke(tmp_path):
    store = _store(tmp_path)
    _write(store, "cred_a", "tok_same", "first")
    _write(store, "cred_b", "tok_same", "second")
    assert store._resolve_credentials("tok_same")["api_key"] == "first"
    (store.path / "cred_a.json").unlink()
    assert store._resolve_credentials("tok_same")["api_key"] == "second"
    _write(store, "cred_0", "tok_new", "new")
    assert store._resolve_credentials("tok_new")["api_key"] == "new"
    store.revoke("tok_new")
    with pytest.raises(FileCustodyError):
        store._resolve_credentials("tok_new")


@pytest.mark.skipif(os.name == "nt", reason="POSIX file-mode and symlink behavior")
def test_permission_change_and_symlink_fail_closed(tmp_path):
    store = _store(tmp_path)
    _write(store, "cred_a", "tok_a")
    assert store._resolve_credentials("tok_a")
    target = store.path / "cred_a.json"
    os.chmod(target, 0o644)
    with pytest.raises(FileCustodyError):
        store._resolve_credentials("tok_a")
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_text("{}")
    target.symlink_to(outside)
    with pytest.raises(FileCustodyError):
        store._resolve_credentials("tok_a")


def test_changed_bad_prefix_fails_but_bad_suffix_does_not(tmp_path):
    store = _store(tmp_path)
    _write(store,"cred_a","tok_a")
    _write(store,"cred_b","tok_b")
    assert store._resolve_credentials("tok_b")
    (store.path/"cred_a.json").write_text("{broken")
    with pytest.raises(FileCustodyError): store._resolve_credentials("tok_b")
    _write(store,"cred_a","tok_a")
    (store.path/"cred_b.json").write_text("{broken")
    assert store._resolve_credentials("tok_a")


def test_separate_instance_rotation_and_revocation_invalidate_warm_index(tmp_path):
    store = _store(tmp_path)
    _write(store,"cred_a","tok_old")
    assert store._resolve_credentials("tok_old")
    writer = EncryptedFileCredentialStore(store.path,tmp_path/"key")
    ref = writer.rotate("tok_old",{"api_key":"rotated"},expected_version=1)
    with pytest.raises(FileCustodyNotFoundError): store._resolve_credentials("tok_old")
    assert store._resolve_credentials(ref["token_id"]) == {"api_key":"rotated"}
    writer.revoke(ref["token_id"])
    with pytest.raises(FileCustodyError): store._resolve_credentials(ref["token_id"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_directory_permission_change_fails_even_on_direct_reference(tmp_path):
    store = _store(tmp_path)
    _write(store,"cred_a","tok_a")
    assert store._resolve_credentials("tok_a")
    store.path.chmod(0o755)
    try:
        with pytest.raises(FileCustodyError): store._resolve_credentials("tok_a")
        with pytest.raises(FileCustodyError): store._resolve_credentials("cred_a")
    finally: store.path.chmod(0o700)


def test_disappearing_suffix_does_not_break_prior_hit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _write(store,"cred_a","tok_a")
    _write(store,"cred_b","tok_b")
    paths=store._paths()
    def listing():
        paths[1].unlink(missing_ok=True)
        return paths
    monkeypatch.setattr(store,"_paths",listing)
    assert store._resolve_credentials("tok_a")
