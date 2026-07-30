import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VECTOR = (
    ROOT
    / "docs"
    / "00_stage0"
    / "review"
    / "assets"
    / "scm_f2_label_font_bundle_digest_vector_v1.json"
)


def test_sc_f2_font_bundle_digest_fixed_vector():
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    payload = json.dumps(
        vector["payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(payload) == vector["canonical_payload_bytes"]
    assert hashlib.sha256(payload).hexdigest() == vector["expected_sha256"]


def test_sc_f2_font_toolchain_controlled_script_hashes():
    lock_path = (
        ROOT
        / "docs"
        / "00_stage0"
        / "review"
        / "assets"
        / "scm_f2_label_font_toolchain_lock_v1.json"
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    for record in lock["controlled_scripts"]:
        payload = (ROOT / record["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"]
