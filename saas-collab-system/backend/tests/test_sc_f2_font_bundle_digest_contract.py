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


def test_sc_f2_font_ci_and_memory_evidence_matches_lock():
    lock_path = (
        ROOT
        / "docs"
        / "00_stage0"
        / "review"
        / "assets"
        / "scm_f2_label_font_toolchain_lock_v1.json"
    )
    evidence_path = (
        ROOT
        / "docs"
        / "00_stage0"
        / "review"
        / "assets"
        / "scm_f2_label_font_ci_evidence_v1.json"
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    frozen = lock["budget_evidence"]["ci_rehearsal"]
    budgets = lock["budgets"]
    memory = evidence["memory_probe"]

    assert len(evidence_bytes) == frozen["evidence_bytes"]
    assert hashlib.sha256(evidence_bytes).hexdigest() == frozen["evidence_sha256"]
    assert evidence["result"] == "PASS"
    assert evidence["violations"] == []
    assert evidence["ci_environment_variable"] == "true"
    assert evidence["candidate"]["bundle_digest"] == lock["candidate"][
        "bundle_digest_sha256"
    ]
    assert evidence["two_page_probe"]["pdf_sha256"] == lock[
        "cross_environment_evidence"
    ]["probe_pdf_sha256_on_windows_linux_ci"]
    assert memory["first_and_steady"]["first_render_peak_rss_kib"] <= budgets[
        "first_render_process_max_rss_kib"
    ]
    assert memory["first_and_steady"][
        "steady_current_growth_from_first_kib"
    ] <= budgets["steady_state_rss_growth_max_kib"]
    assert memory["concurrent"]["workers"] == budgets[
        "memory_probe_concurrent_workers"
    ]
    assert max(memory["concurrent"]["worker_current_rss_kib"]) <= budgets[
        "concurrent_worker_rss_max_kib"
    ]
    assert memory["concurrent"]["aggregate_worker_rss_kib"] <= budgets[
        "concurrent_aggregate_worker_rss_max_kib"
    ]
    assert memory["concurrent"]["aggregate_with_controller_rss_kib"] <= budgets[
        "concurrent_total_rss_max_kib"
    ]
