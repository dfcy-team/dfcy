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


